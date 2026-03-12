"""
StructurePulse — Python Parser
Extracts structural graph from Python source using built-in ast module.
Output: nodes (functions/classes/modules) + edges (calls/imports/dependencies)
"""
import ast
import os
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Node:
    id: str                    # unique: file::class::function
    kind: str                  # module | class | function | method
    name: str
    file: str
    line_start: int
    line_end: int
    loc: int                   # lines of code
    complexity: int = 1        # cyclomatic complexity
    params: int = 0


@dataclass
class Edge:
    src: str                   # node id
    dst: str                   # node id or external name
    kind: str                  # call | import | inherit | instantiate
    resolved: bool = False     # True if dst maps to a known node


@dataclass
class ParseResult:
    file: str
    language: str = "python"
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    loc_total: int = 0
    loc_code: int = 0
    is_boilerplate: bool = False   # True for __init__.py, config.py, etc. with no logic


class PythonParser:
    def parse_file(self, path: str) -> ParseResult:
        result = ParseResult(file=path)
        try:
            source = Path(path).read_text(encoding="utf-8", errors="replace")
            lines = source.splitlines()
            result.loc_total = len(lines)
            result.loc_code = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))
            tree = ast.parse(source, filename=path)
            visitor = _StructureVisitor(path)
            visitor.visit(tree)
            result.nodes = [asdict(n) for n in visitor.nodes]
            result.edges = [asdict(e) for e in visitor.edges]
        except SyntaxError as e:
            result.errors.append(f"SyntaxError: {e}")
        except Exception as e:
            result.errors.append(f"ParseError: {e}")

        # ── boilerplate detection ──────────────────────────────────────────
        fname = Path(path).name
        _bp_names = {"__init__.py", "conftest.py", "setup.py", "manage.py"}
        _bp_prefixes = ("config", "settings", "constants", "types", "models")
        fn_count = sum(1 for n in result.nodes if n.get("kind") in ("function", "method"))
        class_count = sum(1 for n in result.nodes if n.get("kind") == "class")
        is_bp_name = fname in _bp_names or (
            fn_count == 0 and class_count == 0 and any(fname.startswith(p) for p in _bp_prefixes)
        )
        result.is_boilerplate = is_bp_name and fn_count == 0 and result.loc_code <= 30
        return result

    def parse_directory(self, root: str) -> list[ParseResult]:
        results = []
        for path in Path(root).rglob("*.py"):
            # skip venv, __pycache__, migrations, generated
            parts = path.parts
            if any(p in parts for p in ("venv", ".venv", "__pycache__", "node_modules", ".git", "migrations")):
                continue
            results.append(self.parse_file(str(path)))
        return results


class _StructureVisitor(ast.NodeVisitor):
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.rel = filepath  # used as prefix for node ids
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self._scope: list[str] = []  # current class/function stack

    # ── helpers ──────────────────────────────────────────────────────────────
    def _node_id(self, name: str) -> str:
        scope = "::".join(self._scope)
        prefix = f"{self.rel}::{scope}::" if scope else f"{self.rel}::"
        return f"{prefix}{name}"

    def _current_scope_id(self) -> Optional[str]:
        if not self._scope:
            return None
        return f"{self.rel}::{'::'.join(self._scope)}"

    def _end_line(self, node: ast.AST) -> int:
        return getattr(node, "end_lineno", node.lineno)

    def _cyclomatic(self, node: ast.AST) -> int:
        """Count decision points: if/elif/for/while/except/with/assert/bool-ops"""
        count = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler,
                                   ast.With, ast.Assert, ast.comprehension)):
                count += 1
            elif isinstance(child, ast.BoolOp):
                count += len(child.values) - 1
        return count

    # ── visitors ─────────────────────────────────────────────────────────────
    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.edges.append(Edge(
                src=self._current_scope_id() or self.rel,
                dst=alias.name,
                kind="import"
            ))

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = node.module or ""
        self.edges.append(Edge(
            src=self._current_scope_id() or self.rel,
            dst=module,
            kind="import"
        ))

    def visit_ClassDef(self, node: ast.ClassDef):
        nid = self._node_id(node.name)
        n = Node(
            id=nid, kind="class", name=node.name,
            file=self.filepath,
            line_start=node.lineno,
            line_end=self._end_line(node),
            loc=self._end_line(node) - node.lineno + 1,
        )
        self.nodes.append(n)

        # inheritance edges
        for base in node.bases:
            base_name = ast.unparse(base) if hasattr(ast, "unparse") else getattr(base, "id", "?")
            self.edges.append(Edge(src=nid, dst=base_name, kind="inherit"))

        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._visit_func(node)

    def _visit_func(self, node):
        kind = "method" if self._scope else "function"
        nid = self._node_id(node.name)
        n = Node(
            id=nid,
            kind=kind,
            name=node.name,
            file=self.filepath,
            line_start=node.lineno,
            line_end=self._end_line(node),
            loc=self._end_line(node) - node.lineno + 1,
            complexity=self._cyclomatic(node),
            params=len(node.args.args),
        )
        self.nodes.append(n)

        self._scope.append(node.name)
        # collect calls within this function
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                call_name = self._resolve_call(child)
                if call_name:
                    self.edges.append(Edge(src=nid, dst=call_name, kind="call"))
        self._scope.pop()

    def _resolve_call(self, node: ast.Call) -> Optional[str]:
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            obj = ast.unparse(func.value) if hasattr(ast, "unparse") else "?"
            return f"{obj}.{func.attr}"
        return None
