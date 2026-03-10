"""
Tests for .spignore, --exclude CLI patterns, and import line numbers in cycles.
"""
import tempfile
import shutil
from pathlib import Path


def _make_repo(files: dict) -> str:
    d = tempfile.mkdtemp()
    for name, content in files.items():
        p = Path(d, name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def _cleanup(path: str):
    shutil.rmtree(path, ignore_errors=True)


# ── SpIgnore unit tests ───────────────────────────────────────────────────────

def t_spignore_directory_pattern():
    """'tests/' pattern should exclude files under tests/ directory."""
    from structurepulse.ignore import SpIgnore
    ig = SpIgnore(["tests/"], "/workspace")
    ig._root = Path("/workspace")

    assert ig.matches("/workspace/tests/test_foo.py")
    assert ig.matches("/workspace/src/tests/test_bar.py")
    assert not ig.matches("/workspace/src/main.py")


def t_spignore_glob_filename():
    """'test_*.py' should exclude files matching the glob."""
    from structurepulse.ignore import SpIgnore
    ig = SpIgnore(["test_*.py"], "/workspace")
    ig._root = Path("/workspace")

    assert ig.matches("/workspace/src/test_auth.py")
    assert ig.matches("/workspace/test_main.py")
    assert not ig.matches("/workspace/src/auth.py")


def t_spignore_negation():
    """!src/ should un-ignore files in src/ even if tests/ would exclude them."""
    from structurepulse.ignore import SpIgnore
    ig = SpIgnore(["tests/", "!src/tests/"], "/workspace")
    ig._root = Path("/workspace")

    assert ig.matches("/workspace/tests/test_foo.py")
    assert not ig.matches("/workspace/src/tests/test_foo.py")   # negated


def t_spignore_exact_dir_component():
    """'migrations' (no slash) should match any segment in path."""
    from structurepulse.ignore import SpIgnore
    ig = SpIgnore(["migrations"], "/workspace")
    ig._root = Path("/workspace")

    assert ig.matches("/workspace/src/migrations/0001_initial.py")
    assert not ig.matches("/workspace/src/auth.py")


def t_spignore_load_from_file():
    """SpIgnore.load() reads .spignore file and applies patterns."""
    d = tempfile.mkdtemp()
    try:
        (Path(d) / ".spignore").write_text("tests/\n# comment\ntest_*.py\n")
        from structurepulse.ignore import SpIgnore
        ig = SpIgnore.load(d)

        assert ig.matches(str(Path(d) / "tests" / "test_foo.py"))
        assert ig.matches(str(Path(d) / "test_auth.py"))
        assert not ig.matches(str(Path(d) / "src" / "auth.py"))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_spignore_builtin_excludes_venv():
    """venv/ is excluded by default even without .spignore."""
    d = tempfile.mkdtemp()
    try:
        from structurepulse.ignore import SpIgnore
        ig = SpIgnore.load(d)  # no .spignore file
        assert ig.matches(str(Path(d) / "venv" / "lib" / "site.py"))
        assert not ig.matches(str(Path(d) / "src" / "main.py"))
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── Integration: parse_path respects ignore ───────────────────────────────────

def t_parse_path_excludes_test_files_by_default():
    """parse_path must exclude tests/ by default (builtin rules)."""
    files = {
        "src/main.py":         "def main(): return 1\n",
        "tests/test_main.py":  "from src.main import main\ndef test_it(): assert main() == 1\n",
    }
    d = _make_repo(files)
    try:
        from structurepulse.parser import parse_path
        results = parse_path(d)
        parsed_files = [Path(r.file).name for r in results]
        assert "main.py" in parsed_files, f"main.py missing: {parsed_files}"
        assert "test_main.py" not in parsed_files, f"test_main.py should be excluded: {parsed_files}"
    finally:
        _cleanup(d)


def t_parse_path_extra_patterns_flag():
    """extra_patterns=['fixtures/'] should exclude that directory."""
    files = {
        "src/app.py":              "def run(): return 'ok'\n",
        "fixtures/sample_data.py": "DATA = [1, 2, 3]\n",
    }
    d = _make_repo(files)
    try:
        from structurepulse.parser import parse_path
        results = parse_path(d, extra_patterns=["fixtures/"])
        parsed_files = [Path(r.file).name for r in results]
        assert "app.py" in parsed_files
        assert "sample_data.py" not in parsed_files, f"fixtures not excluded: {parsed_files}"
    finally:
        _cleanup(d)


def t_spignore_file_overrides_builtin_test_exclude():
    """!tests/ in .spignore should un-exclude the tests directory."""
    files = {
        "src/main.py":         "def main(): return 1\n",
        "tests/test_main.py":  "def test_it(): return True\n",
        ".spignore":           "!tests/\n",
    }
    d = _make_repo(files)
    try:
        from structurepulse.parser import parse_path
        results = parse_path(d)
        parsed_files = [Path(r.file).name for r in results]
        assert "test_main.py" in parsed_files, (
            f"tests/ should be un-excluded by !tests/ in .spignore: {parsed_files}"
        )
    finally:
        _cleanup(d)


# ── Import line numbers in cycles ─────────────────────────────────────────────

def t_import_lines_stored_in_graph():
    """Import edges must carry line numbers, and import_lines populated in GraphResult."""
    files = {
        "alpha.py": "# header\nimport os\nfrom beta import fn_b\ndef fn_a(): return fn_b()\n",
        "beta.py":  "def fn_b(): return 42\n",
    }
    d = _make_repo(files)
    try:
        from structurepulse.parser import parse_path
        from structurepulse.graph.builder import GraphBuilder

        pr = parse_path(d)
        graph = GraphBuilder().build(pr)

        # Find specifically the alpha→beta edge (not alpha→os)
        alpha_beta = next(
            (k for k in graph.import_lines
             if Path(k[0]).name == "alpha.py" and Path(k[1]).name == "beta.py"),
            None,
        )
        assert alpha_beta is not None, f"alpha→beta edge not in import_lines: {graph.import_lines}"
        line = graph.import_lines[alpha_beta]
        assert line == 3, f"expected line 3 for 'from beta import fn_b', got {line}"
    finally:
        _cleanup(d)


def t_cycle_output_includes_line_numbers():
    """Dependency cycles in GraphResult must reference import_lines."""
    files = {
        "a.py": "from b import fn_b\ndef fn_a(): return fn_b()\n",
        "b.py": "from a import fn_a\ndef fn_b(): return fn_a()\n",
    }
    d = _make_repo(files)
    try:
        from structurepulse.parser import parse_path
        from structurepulse.graph.builder import GraphBuilder

        pr = parse_path(d, extra_patterns=[])  # no exclude — include everything
        graph = GraphBuilder().build(pr)

        assert graph.cycle_count >= 1, "cycle not detected"
        # At least one pair in the cycle must have a line number
        cycle = graph.dependency_cycles[0]
        has_line = any(
            graph.import_lines.get((cycle[i], cycle[(i+1) % len(cycle)]), 0) > 0
            for i in range(len(cycle))
        )
        assert has_line, f"no line numbers in cycle: {graph.import_lines}"
    finally:
        _cleanup(d)
