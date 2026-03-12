#!/usr/bin/env python3
"""StructurePulse test runner — stdlib only, no pytest required.
Usage: python3 tests/run.py
"""
import sys, traceback, tempfile
from pathlib import Path

passed=[]; failed=[]; errors=[]
def run(name, fn):
    try: fn(); passed.append(name); print(f"  \033[32mPASS\033[0m  {name}")
    except AssertionError as e: failed.append((name,str(e))); print(f"  \033[31mFAIL\033[0m  {name}  →  {e}")
    except Exception as e: errors.append((name,traceback.format_exc())); print(f"  \033[33mERRR\033[0m  {name}  →  {type(e).__name__}: {e}")

from structurepulse.parser.python_parser import PythonParser, ParseResult
from structurepulse.graph.builder import GraphBuilder, GraphResult, ModuleStats
from structurepulse.metrics.engine import MetricsEngine

def t_parser_class_extraction():
    parser = PythonParser()
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write('class MyAPI:\n    def __init__(self):\n        self.ready = True\n\n    def do_work(self, data):\n        if data:\n            return sum(data)\n        return 0\n'); path = f.name
    try:
        result = parser.parse_file(path)
        assert len(result.nodes) == 3, f"expected 3 nodes, got {len(result.nodes)}"
        cls = next((n for n in result.nodes if n["kind"]=="class"), None)
        assert cls and cls["name"]=="MyAPI"
        dw = next((n for n in result.nodes if n["name"]=="do_work"), None)
        assert dw and dw["params"]==2, f"params={dw['params']}"
        assert dw["complexity"]==2, f"complexity={dw['complexity']}"
    finally: Path(path).unlink(missing_ok=True)

def t_parser_imports():
    parser = PythonParser()
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write('import os\nimport sys\nfrom third_party import module_a\n\ndef runner():\n    os.getenv("TEST")\n'); path = f.name
    try:
        result = parser.parse_file(path)
        imports = [e for e in result.edges if e["kind"]=="import"]
        assert len(imports)==3, f"expected 3, got {len(imports)}"
        dsts = {e["dst"] for e in imports}
        assert "os" in dsts and "sys" in dsts and "third_party" in dsts
        calls = [e for e in result.edges if e["kind"]=="call"]
        assert len(calls)==1 and calls[0]["dst"]=="os.getenv"
    finally: Path(path).unlink(missing_ok=True)

def t_graph_cycle_detection():
    builder = GraphBuilder()
    def pr(file, dst_stem):
        p = ParseResult(file=file, language="python"); p.nodes=[{"id":f"{file}::f","kind":"function","file":file,"line_start":1,"line_end":5,"loc":5,"complexity":1,"params":0}]; p.edges=[{"src":file,"dst":dst_stem,"kind":"import"}]; return p
    graph = builder.build([pr("module_a.py","module_b"), pr("module_b.py","module_c"), pr("module_c.py","module_a")])
    assert graph.cycle_count==1, f"expected 1 cycle, got {graph.cycle_count}: {graph.dependency_cycles}"
    assert len(graph.dependency_cycles[0]) in (3,4)

def t_graph_coupling_density():
    builder = GraphBuilder()
    pr_a=ParseResult(file="a.py",language="python"); pr_a.nodes=[]; pr_a.edges=[{"src":"a.py","dst":"b","kind":"import"}]
    pr_b=ParseResult(file="b.py",language="python"); pr_b.nodes=[]; pr_b.edges=[{"src":"b.py","dst":"a","kind":"import"}]
    graph = builder.build([pr_a, pr_b])
    assert graph.total_modules==2 and graph.coupling_density==1.0, f"got {graph.coupling_density}"

def t_fd_optimal():
    engine=MetricsEngine(); graph=GraphResult()
    graph.module_stats={f"mod{i}":ModuleStats(path=f"mod{i}",name=f"mod{i}",language="py",node_count=i*3) for i in range(1,4)}
    assert engine.compute(graph).fd>=1.0

def t_fd_chaos():
    engine=MetricsEngine(); graph=GraphResult()
    graph.module_stats={f"mod{i}":ModuleStats(path=f"mod{i}",name=f"mod{i}",language="py",avg_complexity=[100,1,80,2,50,1,120,1][i-1]) for i in range(1,9)}
    m=engine.compute(graph); assert m.fd_status=="chaos" or m.fd>1.8

def t_shi_stable():
    engine=MetricsEngine(); graph=GraphResult()
    graph.module_stats={f"mod{i}":ModuleStats(path=f"mod{i}",name=f"mod{i}",language="py",node_count=i*3+2) for i in range(1,3)}
    graph.coupling_density=0.1; graph.cycle_count=0; graph.total_modules=2
    for m in graph.module_stats.values(): m.cohesion=0.9
    result=engine.compute(graph); assert result.shi>0.8 and result.status=="stable"

print("\n\033[1m  StructurePulse Test Suite\033[0m\n  "+"─"*56)
run("parser :: class extraction",         t_parser_class_extraction)
run("parser :: imports + calls",          t_parser_imports)
run("graph  :: cycle detection A→B→C→A", t_graph_cycle_detection)
run("graph  :: coupling density (full)",  t_graph_coupling_density)
run("metrics :: fd >= 1.0 layered",       t_fd_optimal)
run("metrics :: fd chaos spiky",          t_fd_chaos)
run("metrics :: shi > 0.8 clean",         t_shi_stable)
print("  "+"─"*56)
total=len(passed)+len(failed)+len(errors)
c="\033[32m" if not failed and not errors else "\033[31m"
print(f"  {c}{len(passed)}/{total} passed  |  {len(failed)} failed  |  {len(errors)} errors\033[0m\n")
if failed or errors: sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# Sprint 5 tests: AgentAPI + Network
# ─────────────────────────────────────────────────────────────────────────────
import importlib, sys

def _load(module_path):
    spec = importlib.util.spec_from_file_location("_t", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_here = Path(__file__).parent

_api_tests = _load(_here / "test_agent_api.py")
_net_tests = _load(_here / "test_network.py")

print("\n\033[1m  Sprint 5 — AgentAPI\033[0m\n  "+"─"*56)
run("api :: scan returns metrics",          _api_tests.t_api_scan_returns_metrics)
run("api :: scan empty dir → error",        _api_tests.t_api_scan_empty_dir_returns_error)
run("api :: scan high coupling detected",   _api_tests.t_api_scan_action_required_on_high_coupling)
run("api :: library add + search",          _api_tests.t_api_library_add_and_search)
run("api :: library search empty",          _api_tests.t_api_library_search_empty_returns_zero)
run("api :: sandbox create + scan",         _api_tests.t_api_sandbox_create_and_scan)
run("api :: generate_prompt structure",     _api_tests.t_api_generate_prompt_structure)
run("api :: plan returns verdict",          _api_tests.t_api_plan_returns_library_matches_and_verdict)
print("  "+"─"*56)

print("\n\033[1m  Sprint 5 — Network\033[0m\n  "+"─"*56)
run("net :: bundle build + validate",       _net_tests.t_bundle_build_and_validate)
run("net :: bundle merkle tamper detect",   _net_tests.t_bundle_merkle_tamper_detection)
run("net :: peer registry add + list",      _net_tests.t_peer_registry_add_and_list)
run("net :: peer registry dedup",           _net_tests.t_peer_registry_deduplicates_by_address)
run("net :: file transport sync",           _net_tests.t_sync_file_transport_round_trip)
run("net :: dry-run imports nothing",       _net_tests.t_sync_dry_run_imports_nothing)
run("net :: HTTP server /api/status",       _net_tests.t_http_server_status_endpoint)
run("net :: HTTP peer sync round-trip",     _net_tests.t_http_peer_sync_round_trip)
print("  "+"─"*56)
total = len(passed)+len(failed)+len(errors)
c="\033[32m" if not failed and not errors else "\033[31m"
print(f"  {c}{len(passed)}/{total} passed  |  {len(failed)} failed  |  {len(errors)} errors\033[0m\n")
if failed or errors: sys.exit(1)
