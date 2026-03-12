from .python_parser import PythonParser, ParseResult, Node, Edge
from .ts_parser import TypeScriptParser

__all__ = ["PythonParser", "TypeScriptParser", "ParseResult", "Node", "Edge", "parse_path"]


def parse_path(path: str,
               ignore=None,
               extra_patterns: list = None) -> list[ParseResult]:
    """
    Auto-detect language and parse all matching files under path.

    Args:
        path:             File or directory to parse.
        ignore:           A SpIgnore instance. If None, loaded from workspace
                          root (.spignore if present + builtin defaults).
        extra_patterns:   Additional patterns from --exclude CLI flag.
    """
    from pathlib import Path
    from structurepulse.ignore import SpIgnore

    py = PythonParser()
    ts = TypeScriptParser()
    results = []

    p = Path(path)

    if p.is_file():
        if p.suffix == ".py":
            results.append(py.parse_file(path))
        elif p.suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
            results.append(ts.parse_file(path))
    else:
        if ignore is None:
            ignore = SpIgnore.load(str(p.resolve()), extra_patterns=extra_patterns)
        results.extend(py.parse_directory(path, ignore=ignore))
        results.extend(ts.parse_directory(path, ignore=ignore))

    return results
