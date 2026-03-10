"""
StructurePulse — Agent API
Machine-readable JSON interface for external agents (Claude Code, Cursor, etc.)
All operations return structured JSON. No human-formatted output.

Designed to be called as:
  structurepulse agent scan --path . --json
  structurepulse agent plan "I need an auth module for Python"
  structurepulse agent library search "auth"
  structurepulse agent sandbox create --sources src/auth.py
  structurepulse agent prompt --problem "refactor payments module"
"""
import json
import sys
from pathlib import Path
from dataclasses import asdict


class AgentAPI:
    """
    Thin facade that routes agent commands and always returns JSON.
    Import this in any agent that wants to use StructurePulse as a sensor.
    """

    def __init__(self, workspace_root: str = "."):
        self.root = Path(workspace_root).resolve()

    # ── SCAN ─────────────────────────────────────────────────────────────
    def scan(self, path: str = None) -> dict:
        from structurepulse.parser import parse_path
        from structurepulse.graph.builder import GraphBuilder
        from structurepulse.metrics.engine import MetricsEngine

        target = path or str(self.root)
        parse_results = parse_path(target)
        if not parse_results:
            return {"error": f"No source files found in: {target}"}

        graph = GraphBuilder().build(parse_results)
        metrics = MetricsEngine().compute(graph)

        return {
            "path": target,
            "fingerprint": graph.fingerprint,
            "metrics": {
                "fd": metrics.fd,
                "fd_status": metrics.fd_status,
                "shi": metrics.shi,
                "status": metrics.status,
                "coupling_density": metrics.coupling_density,
                "cycle_count": metrics.cycle_count,
                "graph_entropy": metrics.graph_entropy,
                "avg_complexity": metrics.avg_complexity,
            },
            "action_required": self._action_required(metrics),
            "inconsistencies": [
                {"code": w.code, "kind": w.kind, "module": w.module,
                 "message": w.message, "detail": w.detail, "severity": w.severity}
                for w in metrics.inconsistencies
            ],
        }

    # ── PLAN ─────────────────────────────────────────────────────────────
    def plan(self,
             problem: str,
             source_paths: list[str] = None,
             language: str = None,
             auto_sandbox: bool = False) -> dict:
        from structurepulse.planner.agent_planner import AgentPlanner
        planner = AgentPlanner(str(self.root))
        result = planner.plan(
            problem=problem,
            source_paths=source_paths,
            language=language,
            auto_sandbox=auto_sandbox,
        )
        return asdict(result)

    # ── LIBRARY ──────────────────────────────────────────────────────────
    def library_search(self, query: str, language: str = None,
                       min_shi: float = 0.0, limit: int = 5) -> dict:
        from structurepulse.library.agent_library import AgentLibrary
        lib = AgentLibrary(str(self.root))
        matches = lib.search(query=query, language=language,
                             min_shi=min_shi, limit=limit)
        return {
            "query": query,
            "matches": [asdict(m) for m in matches],
            "count": len(matches),
        }

    def library_add(self, source_path: str, name: str,
                    description: str = "", tags: list = None) -> dict:
        from structurepulse.library.agent_library import AgentLibrary
        from structurepulse.parser import parse_path
        from structurepulse.graph.builder import GraphBuilder
        from structurepulse.metrics.engine import MetricsEngine

        parse_results = parse_path(source_path)
        graph = GraphBuilder().build(parse_results) if parse_results else None
        metrics = MetricsEngine().compute(graph) if graph else None

        lib = AgentLibrary(str(self.root))
        entry = lib.add(
            source_path=source_path,
            name=name,
            description=description,
            tags=tags or [],
            metrics=metrics,
            graph_result=graph,
        )
        return {"added": asdict(entry)}

    # ── SANDBOX ──────────────────────────────────────────────────────────
    def sandbox_create(self, name: str, source_paths: list[str],
                       hypothesis: str = "", tags: list = None) -> dict:
        from structurepulse.sandbox.sandbox_lab import SandboxLab
        sandbox = SandboxLab(str(self.root))
        exp = sandbox.create(name=name, source_paths=source_paths,
                             hypothesis=hypothesis, tags=tags or [])
        return {
            "experiment": asdict(exp),
            "sandbox_path": exp.sandbox_path,
            "next_step": f"Modify files in {exp.sandbox_path}, then: structurepulse agent sandbox scan {exp.id}",
        }

    def sandbox_scan(self, experiment_id: str) -> dict:
        from structurepulse.sandbox.sandbox_lab import SandboxLab
        sandbox = SandboxLab(str(self.root))
        return sandbox.scan(experiment_id)

    def sandbox_promote(self, experiment_id: str,
                        library_name: str, description: str = "") -> dict:
        from structurepulse.sandbox.sandbox_lab import SandboxLab
        from structurepulse.library.agent_library import AgentLibrary
        sandbox = SandboxLab(str(self.root))
        lib = AgentLibrary(str(self.root))
        lib_id = sandbox.promote(experiment_id, lib,
                                 name=library_name, description=description)
        return {"promoted": experiment_id, "library_id": lib_id}

    # ── PROMPT ──────────────────────────────────────────────────────────
    def generate_prompt(self, problem: str,
                        source_paths: list[str] = None) -> dict:
        """Returns a structured prompt ready for Claude Code or Cursor."""
        plan = self.plan(problem, source_paths)
        return {
            "problem": problem,
            "agent_prompt": plan.get("agent_prompt", ""),
            "recommendation": plan.get("recommendation", ""),
            "library_matches": plan.get("library_matches", []),
        }

    # ── DIFF ─────────────────────────────────────────────────────────────
    def diff(self, repo_path: str,
             ref_before: str = "HEAD~1",
             ref_after: str = "HEAD") -> dict:
        from structurepulse.diff.git_integration import GitIntegration
        from structurepulse.metrics.engine import MetricsEngine
        from structurepulse.diff.structural_diff import StructuralDiffer
        from dataclasses import asdict as _asdict

        git = GitIntegration(repo_path)
        engine = MetricsEngine()
        m_before, _ = git.scan_at_commit(ref_before, engine)
        m_after, _  = git.scan_at_commit(ref_after,  engine)

        diff = StructuralDiffer().diff(m_before, m_after, ref_before, ref_after)

        def _df(f):
            return {"before": f.before, "after": f.after,
                    "delta": f.delta, "severity": f.severity}
        return {
            "fd": _df(diff.fd), "shi": _df(diff.shi),
            "coupling": _df(diff.coupling), "cycles": _df(diff.cycles),
            "verdict": diff.verdict, "reasons": diff.verdict_reasons,
        }

    # ── helpers ──────────────────────────────────────────────────────────
    def _action_required(self, metrics) -> list[str]:
        actions = []
        if metrics.cycle_count > 0:
            actions.append(f"resolve {metrics.cycle_count} dependency cycle(s)")
        if metrics.coupling_density > 0.6:
            actions.append("reduce module coupling (currently high)")
        if metrics.fd_status == "chaos":
            actions.append("refactor: FD above chaos threshold")
        if metrics.fd_status == "rigid":
            actions.append("diversify: FD below optimal (too rigid)")
        if metrics.shi < 0.6:
            actions.append("critical: SHI below safe threshold")
        return actions
