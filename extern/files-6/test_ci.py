"""
Tests for --fail-on CI/CD enforcement (Sprint 21).

Tests the _evaluate_fail_conditions logic directly (unit),
plus subprocess integration tests for exit codes.
"""
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path


def _make_repo(files: dict) -> str:
    d = tempfile.mkdtemp()
    for name, content in files.items():
        Path(d, name).write_text(content)
    return d


def _cleanup(path: str):
    shutil.rmtree(path, ignore_errors=True)


def _sp_scan(workspace: str, *extra_args) -> tuple[int, str]:
    """Run sp scan, return (exit_code, stdout)."""
    result = subprocess.run(
        [sys.executable, "-m", "structurepulse.cli.main",
         "scan", workspace, "--exclude", "tests/", *extra_args],
        capture_output=True, text=True, cwd="/home/claude",
    )
    return result.returncode, result.stdout + result.stderr


# ── Unit tests for _evaluate_fail_conditions ─────────────────────────────────

def _make_metrics_stub(shi=0.8, coupling=0.3, fd=1.8, cycles=0, inconsistencies=0):
    """Minimal stub — only needs the attributes _evaluate_fail_conditions reads."""
    from types import SimpleNamespace
    return SimpleNamespace(
        shi=shi,
        coupling_density=coupling,
        fd=fd,
        inconsistencies=[object()] * inconsistencies,
    )


def _make_graph_stub(cycles=0):
    from types import SimpleNamespace
    return SimpleNamespace(cycle_count=cycles)


def t_unit_no_conditions_always_passes():
    from structurepulse.cli.main import _evaluate_fail_conditions
    v = _evaluate_fail_conditions([], _make_metrics_stub(), _make_graph_stub())
    assert v == [], f"expected no violations: {v}"


def t_unit_cycles_flag_triggers_on_cycle():
    from structurepulse.cli.main import _evaluate_fail_conditions
    v = _evaluate_fail_conditions(["cycles"], _make_metrics_stub(), _make_graph_stub(cycles=3))
    assert len(v) == 1 and "3" in v[0]


def t_unit_cycles_flag_passes_when_clean():
    from structurepulse.cli.main import _evaluate_fail_conditions
    v = _evaluate_fail_conditions(["cycles"], _make_metrics_stub(), _make_graph_stub(cycles=0))
    assert v == []


def t_unit_shi_threshold_triggers():
    from structurepulse.cli.main import _evaluate_fail_conditions
    v = _evaluate_fail_conditions(["shi<0.7"], _make_metrics_stub(shi=0.5), _make_graph_stub())
    assert len(v) == 1 and "shi" in v[0] and "0.5" in v[0]


def t_unit_shi_threshold_passes():
    from structurepulse.cli.main import _evaluate_fail_conditions
    v = _evaluate_fail_conditions(["shi<0.7"], _make_metrics_stub(shi=0.75), _make_graph_stub())
    assert v == []


def t_unit_shi_lte_boundary():
    from structurepulse.cli.main import _evaluate_fail_conditions
    # shi<=0.7 should trigger when shi == 0.7 exactly
    v = _evaluate_fail_conditions(["shi<=0.7"], _make_metrics_stub(shi=0.7), _make_graph_stub())
    assert len(v) == 1


def t_unit_coupling_gt_triggers():
    from structurepulse.cli.main import _evaluate_fail_conditions
    v = _evaluate_fail_conditions(["coupling>0.5"], _make_metrics_stub(coupling=0.8), _make_graph_stub())
    assert len(v) == 1 and "coupling" in v[0]


def t_unit_inconsistencies_flag_triggers():
    from structurepulse.cli.main import _evaluate_fail_conditions
    v = _evaluate_fail_conditions(["inconsistencies"],
                                  _make_metrics_stub(inconsistencies=2),
                                  _make_graph_stub())
    assert len(v) == 1 and "2" in v[0]


def t_unit_multiple_conditions_all_checked():
    from structurepulse.cli.main import _evaluate_fail_conditions
    v = _evaluate_fail_conditions(
        ["cycles", "shi<0.7", "inconsistencies"],
        _make_metrics_stub(shi=0.5, inconsistencies=1),
        _make_graph_stub(cycles=2),
    )
    assert len(v) == 3, f"expected 3 violations, got: {v}"


def t_unit_cycles_gt_N_parametric():
    from structurepulse.cli.main import _evaluate_fail_conditions
    # cycles>5 should only trigger when > 5
    v_pass = _evaluate_fail_conditions(["cycles>5"], _make_metrics_stub(), _make_graph_stub(cycles=3))
    v_fail = _evaluate_fail_conditions(["cycles>5"], _make_metrics_stub(), _make_graph_stub(cycles=6))
    assert v_pass == [], f"should pass at 3 cycles: {v_pass}"
    assert len(v_fail) == 1, f"should fail at 6 cycles: {v_fail}"


def t_unit_unknown_condition_reported():
    from structurepulse.cli.main import _evaluate_fail_conditions
    v = _evaluate_fail_conditions(["bogus_metric"], _make_metrics_stub(), _make_graph_stub())
    assert len(v) == 1 and "unknown" in v[0].lower()


# ── Integration: subprocess exit codes ───────────────────────────────────────

def t_integration_exit_0_clean_repo():
    """Clean repo → no --fail-on → exit 0."""
    d = _make_repo({
        "a.py": "def fa(): return 1\n",
        "b.py": "def fb(): return 2\n",
    })
    try:
        code, out = _sp_scan(d)
        assert code == 0, f"expected exit 0, got {code}:\n{out}"
    finally:
        _cleanup(d)


def t_integration_exit_1_on_cycles():
    """Cyclic repo + --fail-on cycles → exit 1."""
    d = _make_repo({
        "x.py": "from y import fy\ndef fx(): return fy()\n",
        "y.py": "from x import fx\ndef fy(): return fx()\n",
        "z.py": "def fz(): return 42\n",
    })
    try:
        code, out = _sp_scan(d, "--fail-on", "cycles")
        assert code == 1, f"expected exit 1, got {code}:\n{out}"
        assert "CI/CD GATE FAILED" in out or "cycles:" in out
    finally:
        _cleanup(d)


def t_integration_exit_0_cycles_but_not_flagged():
    """Cyclic repo WITHOUT --fail-on cycles → exit 0."""
    d = _make_repo({
        "x.py": "from y import fy\ndef fx(): return fy()\n",
        "y.py": "from x import fx\ndef fy(): return fx()\n",
    })
    try:
        code, _ = _sp_scan(d)   # no --fail-on
        assert code == 0, f"expected exit 0 without --fail-on: {code}"
    finally:
        _cleanup(d)


def t_integration_exit_1_shi_threshold():
    """Repo with many homogenous modules → SHI below 0.99 → exit 1."""
    files = {f"mod{i}.py": "def f(): return 1\n" for i in range(5)}
    d = _make_repo(files)
    try:
        # SHI will not be 1.0 — use a very high threshold to guarantee failure
        code, out = _sp_scan(d, "--fail-on", "shi<0.99")
        assert code == 1, f"expected exit 1 for shi<0.99, got {code}:\n{out}"
    finally:
        _cleanup(d)


def t_integration_json_ci_block_present():
    """--json output must include ci.passed and ci.violations."""
    import json
    d = _make_repo({
        "a.py": "from b import fb\ndef fa(): return fb()\n",
        "b.py": "from a import fa\ndef fb(): return fa()\n",
    })
    try:
        result = subprocess.run(
            [sys.executable, "-m", "structurepulse.cli.main",
             "scan", d, "--json", "--fail-on", "cycles"],
            capture_output=True, text=True, cwd="/home/claude",
        )
        data = json.loads(result.stdout)
        assert "ci" in data, f"'ci' block missing from JSON: {list(data.keys())}"
        assert "passed" in data["ci"]
        assert "violations" in data["ci"]
        assert data["ci"]["passed"] is False, f"expected passed=False: {data['ci']}"
        assert result.returncode == 1
    finally:
        _cleanup(d)
