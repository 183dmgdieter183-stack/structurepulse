"""
StructurePulse — Graph Builder
Converts ParseResults into three graph types:
  1. Dependency Graph  — module-level import relationships
  2. Call Graph        — function-level call relationships
  3. Module Graph      — coupling/cohesion per module (file)
Output: GraphResult with JSON-serializable adjacency data.
"""
import os
from pathlib import Path
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional


@dataclass
class ModuleStats:
    path: str
    name: str                    # short name (filename without ext)
    language: str
    loc: int = 0
    loc_code: int = 0
    node_count: int = 0          # functions + methods + classes
    avg_complexity: float = 1.0
    internal_edges: int = 0      # calls within this module
    external_edges: int = 0      # calls leaving this module
    import_count: int = 0
    coupling: float = 0.0        # external / (internal + external)
    cohesion: float = 1.0        # internal / total calls (LCOM proxy)
    parse_errors: list = field(default_factory=list)


@dataclass
class GraphResult:
    # adjacency lists
    dependency_graph: dict = field(default_factory=dict)   # module → [modules it imports]
    call_graph: dict = field(default_factory=dict)         # node_id → [called node_ids]
    module_stats: dict = field(default_factory=dict)       # module_path → ModuleStats

    # aggregate
    total_modules: int = 0
    total_nodes: int = 0
    total_edges: int = 0
    total_loc: int = 0
    total_loc_code: int = 0
    languages: list = field(default_factory=list)

    # cycles
    dependency_cycles: list = field(default_factory=list)  # list of cycle paths
    cycle_count: int = 0

    # coupling density (global)
    coupling_density: float = 0.0

    # fingerprint (repo identity)
    fingerprint: dict = field(default_factory=dict)


class GraphBuilder:
    def build(self, parse_results: list) -> GraphResult:
        result = GraphResult()

        # ── index all nodes by id ──────────────────────────────────────────
        node_index: dict[str, dict] = {}
        module_nodes: dict[str, list] = defaultdict(list)

        for pr in parse_results:
            for n in pr.nodes:
                node_index[n["id"]] = n
                module_nodes[pr.file].append(n)

        # ── module stats ──────────────────────────────────────────────────
        for pr in parse_results:
            mname = Path(pr.file).stem
            ms = ModuleStats(
                path=pr.file,
                name=mname,
                language=pr.language,
                loc=pr.loc_total,
                loc_code=pr.loc_code,
                node_count=len([n for n in pr.nodes if n["kind"] in ("function","method","class")]),
                parse_errors=pr.errors,
            )
            if pr.nodes:
                complexities = [n.get("complexity", 1) for n in pr.nodes if n.get("complexity")]
                ms.avg_complexity = round(sum(complexities) / len(complexities), 2) if complexities else 1.0

            result.module_stats[pr.file] = ms

        # ── dependency graph (module level) ──────────────────────────────
        module_files = set(result.module_stats.keys())
        dep_graph: dict[str, set] = defaultdict(set)

        for pr in parse_results:
            for e in pr.edges:
                if e["kind"] == "import":
                    dep_graph[pr.file].add(e["dst"])

        result.dependency_graph = {k: sorted(list(v)) for k, v in dep_graph.items()}

        # ── call graph (function level) ────────────────────────────────────
        call_graph: dict[str, set] = defaultdict(set)

        for pr in parse_results:
            for e in pr.edges:
                if e["kind"] == "call":
                    call_graph[e["src"]].add(e["dst"])
                    # update module internal/external edge counts
                    src_module = pr.file
                    # try to resolve dst to a known node
                    dst_node = node_index.get(e["dst"])
                    if dst_node:
                        dst_module = dst_node["file"]
                        if dst_module == src_module:
                            result.module_stats[src_module].internal_edges += 1
                        else:
                            result.module_stats[src_module].external_edges += 1
                    else:
                        result.module_stats[src_module].external_edges += 1

        result.call_graph = {k: sorted(list(v)) for k, v in call_graph.items()}

        # ── import counts (per module) ─────────────────────────────────────
        for pr in parse_results:
            ms = result.module_stats[pr.file]
            ms.import_count = sum(1 for e in pr.edges if e["kind"] == "import")

        # ── cycle detection (dependency graph) ────────────────────────────
        result.dependency_cycles = self._find_cycles(result.dependency_graph)
        result.cycle_count = len(result.dependency_cycles)

        # ── aggregates ────────────────────────────────────────────────────
        result.total_modules = len(result.module_stats)
        result.total_nodes = sum(ms.node_count for ms in result.module_stats.values())
        result.total_edges = sum(
            len(v) for v in result.call_graph.values()
        ) + sum(len(v) for v in result.dependency_graph.values())
        result.total_loc = sum(ms.loc for ms in result.module_stats.values())
        result.total_loc_code = sum(ms.loc_code for ms in result.module_stats.values())
        result.languages = sorted(set(ms.language for ms in result.module_stats.values()))

        # ── coupling density (import-graph level, not call-level) ──────────
        # Measures: actual inter-module import edges / max possible edges
        # For n modules: max directed edges = n*(n-1)
        # A perfectly layered chain of 4 = 3/12 = 0.25  ✓
        # A fully connected mess of 4 = 12/12 = 1.0     ✗
        n = result.total_modules
        if n > 1:
            # count import edges that cross known module boundaries
            known_modules = set(result.module_stats.keys())
            # build a module-name lookup (stem → full path) for resolving relative imports
            stem_to_path = {}
            for path in known_modules:
                from pathlib import Path as _Path
                stem_to_path[_Path(path).stem] = path

            cross_edges = set()  # (src_module, dst_module) pairs
            for pr in parse_results:
                for e in pr.edges:
                    if e["kind"] != "import":
                        continue
                    dst_name = e["dst"].split(".")[-1] if "." in e["dst"] else e["dst"]
                    dst_module = stem_to_path.get(dst_name)
                    if dst_module and dst_module != pr.file:
                        cross_edges.add((pr.file, dst_module))

            max_edges = n * (n - 1)
            result.coupling_density = round(len(cross_edges) / max_edges, 3) if max_edges else 0.0

            # per-module coupling: out-degree / (n-1)
            out_degree = defaultdict(int)
            for src, dst in cross_edges:
                out_degree[src] += 1
            for path, ms in result.module_stats.items():
                ms.coupling = round(out_degree[path] / (n - 1), 3)
                ms.cohesion = round(1.0 - ms.coupling, 3)
        else:
            result.coupling_density = 0.0

        # ── repo fingerprint ──────────────────────────────────────────────
        result.fingerprint = self._fingerprint(result)

        return result

    # ── cycle detection (DFS) ─────────────────────────────────────────────
    def _find_cycles(self, graph: dict) -> list:
        visited = set()
        rec_stack = set()
        cycles = []

        def dfs(node, path):
            visited.add(node)
            rec_stack.add(node)
            for neighbor in graph.get(node, []):
                # only track cycles between known modules
                if neighbor not in graph:
                    continue
                if neighbor not in visited:
                    dfs(neighbor, path + [neighbor])
                elif neighbor in rec_stack:
                    # found cycle
                    cycle_start = path.index(neighbor) if neighbor in path else 0
                    cycle = path[cycle_start:] + [neighbor]
                    if cycle not in cycles:
                        cycles.append(cycle)
            rec_stack.discard(node)

        for node in list(graph.keys()):
            if node not in visited:
                dfs(node, [node])

        return cycles

    # ── repo fingerprint ──────────────────────────────────────────────────
    def _fingerprint(self, r: GraphResult) -> dict:
        modules = list(r.module_stats.values())
        avg_loc = round(r.total_loc_code / r.total_modules, 1) if r.total_modules else 0
        avg_complexity = round(
            sum(ms.avg_complexity for ms in modules) / len(modules), 2
        ) if modules else 1.0

        # rough architecture style heuristic
        style = "unknown"
        if r.cycle_count == 0 and r.coupling_density < 0.25:
            style = "layered"
        elif r.cycle_count > 3:
            style = "tangled"
        elif r.coupling_density < 0.4:
            style = "modular"
        else:
            style = "monolithic"

        return {
            "languages": r.languages,
            "modules": r.total_modules,
            "total_nodes": r.total_nodes,
            "avg_module_loc": avg_loc,
            "avg_complexity": avg_complexity,
            "dependency_cycles": r.cycle_count,
            "coupling_density": r.coupling_density,
            "architecture_style": style,
        }
