"""
StructurePulse LSP — Diagnostics producer

Runs sp scan on a workspace and converts MetricsResult + GraphResult
into LSP Diagnostic objects ready for publishDiagnostics.

Diagnostic strategy:
  - Dependency cycles → ERROR on the first import line of each participating file
  - SHI < 0.65      → WARNING on line 0 of the most-coupled module
  - Coupling > 0.6   → INFORMATION on the most-coupled module

LSP Diagnostic severity codes:
  1 = Error, 2 = Warning, 3 = Information, 4 = Hint
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Position:
    line: int       # 0-indexed
    character: int  # 0-indexed

    def to_dict(self):
        return {"line": self.line, "character": self.character}


@dataclass
class Range:
    start: Position
    end: Position

    def to_dict(self):
        return {"start": self.start.to_dict(), "end": self.end.to_dict()}


@dataclass
class Diagnostic:
    """Single LSP diagnostic attached to a URI."""
    uri: str
    message: str
    severity: int           # 1=Error, 2=Warning, 3=Info
    source: str = "StructurePulse"
    code: str = ""
    range: Range = field(default_factory=lambda: Range(
        Position(0, 0), Position(0, 0)
    ))

    def to_dict(self):
        return {
            "range": self.range.to_dict(),
            "severity": self.severity,
            "code": self.code,
            "source": self.source,
            "message": self.message,
        }


# ── Scanner ───────────────────────────────────────────────────────────────────

class DiagnosticsProducer:
    """
    Runs sp scan on workspace_root and returns a mapping:
      { file_uri: [Diagnostic, ...] }

    Called on every didOpen / didSave event.
    """

    SEVERITY_ERROR   = 1
    SEVERITY_WARNING = 2
    SEVERITY_INFO    = 3

    def __init__(self, workspace_root: str, min_shi: float = 0.65):
        self.root = Path(workspace_root).resolve()
        self.min_shi = min_shi

    def scan(self) -> dict[str, list[Diagnostic]]:
        """Return {uri: [Diagnostic]} for the workspace."""
        from structurepulse.parser import parse_path
        from structurepulse.graph.builder import GraphBuilder
        from structurepulse.metrics.engine import MetricsEngine

        try:
            parse_results = parse_path(str(self.root))
            if not parse_results:
                return {}
            graph  = GraphBuilder().build(parse_results)
            metrics = MetricsEngine().compute(graph)
        except Exception as e:
            # Scan failure → single workspace-level info diagnostic
            uri = self._file_uri(self.root / "__workspace__")
            return {uri: [Diagnostic(
                uri=uri,
                message=f"StructurePulse scan failed: {e}",
                severity=self.SEVERITY_INFO,
                code="SP000",
            )]}

        diags: dict[str, list[Diagnostic]] = {}

        # 1. Dependency cycles → ERROR
        self._emit_cycle_diagnostics(graph, diags)

        # 2. SHI below threshold → WARNING on most-coupled module
        if metrics.shi < self.min_shi:
            self._emit_shi_warning(graph, metrics, diags)

        # 3. High coupling module → INFO
        self._emit_coupling_info(graph, metrics, diags)

        return diags

    # ── private helpers ───────────────────────────────────────────────────────

    def _emit_cycle_diagnostics(self, graph, diags: dict):
        for cycle in graph.dependency_cycles:
            for module_path in cycle:
                uri = self._file_uri(module_path)
                line = self._first_import_line(module_path)
                # Describe the cycle compactly
                chain = " → ".join(Path(p).name for p in cycle) + " → ..."
                d = Diagnostic(
                    uri=uri,
                    message=f"Dependency cycle detected: {chain}",
                    severity=self.SEVERITY_ERROR,
                    code="SP-CYCLE",
                    range=Range(Position(line, 0), Position(line, 200)),
                )
                diags.setdefault(uri, []).append(d)

    def _emit_shi_warning(self, graph, metrics, diags: dict):
        # Find the most-coupled non-boilerplate module
        worst = max(
            (ms for ms in graph.module_stats.values()
             if not getattr(ms, "is_boilerplate", False)),
            key=lambda m: m.coupling,
            default=None,
        )
        if worst is None:
            return
        uri = self._file_uri(worst.path)
        gap = round(self.min_shi - metrics.shi, 3)
        d = Diagnostic(
            uri=uri,
            message=(
                f"SHI {metrics.shi:.3f} — below threshold {self.min_shi} "
                f"(gap: {gap:+.3f}). {self._shi_hint(metrics)}"
            ),
            severity=self.SEVERITY_WARNING,
            code="SP-SHI",
        )
        diags.setdefault(uri, []).append(d)

    def _emit_coupling_info(self, graph, metrics, diags: dict):
        if metrics.coupling_density <= 0.50:
            return
        worst = max(
            graph.module_stats.values(),
            key=lambda m: m.coupling,
            default=None,
        )
        if worst is None or worst.coupling <= 0.50:
            return
        uri = self._file_uri(worst.path)
        d = Diagnostic(
            uri=uri,
            message=(
                f"High coupling ({worst.coupling:.2f}): this module is heavily "
                f"connected. Consider extracting shared interfaces."
            ),
            severity=self.SEVERITY_INFO,
            code="SP-COUPLING",
        )
        diags.setdefault(uri, []).append(d)

    def _shi_hint(self, metrics) -> str:
        if metrics.cycle_count > 0:
            return f"Resolve {metrics.cycle_count} dependency cycle(s) first."
        if metrics.coupling_density > 0.5:
            return "Primary driver: high coupling density."
        if metrics.fd_status == "rigid":
            return "Primary driver: FD too rigid — modules are too homogeneous."
        return "Run `sp scan --explain` for root cause analysis."

    @staticmethod
    def _file_uri(path) -> str:
        return Path(path).as_uri()

    @staticmethod
    def _first_import_line(path) -> int:
        """Return 0-indexed line number of the first import statement."""
        try:
            lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("import ") or stripped.startswith("from "):
                    return i
        except OSError:
            pass
        return 0
