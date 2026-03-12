"""
StructurePulse — sp watch
File-system watcher. Re-scans on every save, prints SHI delta + violations.

Stdlib only: uses polling (no watchdog dependency).
Polling interval: 1.5s (configurable via --interval).

Usage:
  structurepulse watch [path] [--interval 1.5] [--min-shi 0.8] [--explain]
"""
import time
import os
import sys
import math
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime

# ── ANSI (same as cli/main.py) ───────────────────────────────────────────────
RESET = "\033[0m"
def _c(code): return lambda s: f"\033[{code}m{s}{RESET}"
RED   = _c("31"); GREEN = _c("32"); GOLD  = _c("33")
CYAN  = _c("36"); BOLD  = _c("1");  DIM   = _c("2")


@dataclass
class WatchState:
    shi: float = 0.0
    fd: float = 0.0
    coupling: float = 0.0
    cycles: int = 0
    status: str = "unknown"
    explanation: list = field(default_factory=list)
    mtimes: dict = field(default_factory=dict)   # path → mtime


def _collect_mtimes(root: str) -> dict:
    """Return {filepath: mtime} for all .py/.ts/.tsx files under root."""
    mtimes = {}
    for dirpath, dirnames, files in os.walk(root):
        # skip generated dirs
        dirnames[:] = [d for d in dirnames if d not in
                       ("venv", ".venv", "__pycache__", "node_modules", ".git", "migrations")]
        for f in files:
            if f.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
                p = os.path.join(dirpath, f)
                try:
                    mtimes[p] = os.path.getmtime(p)
                except OSError:
                    pass
    return mtimes


def _scan(root: str):
    """Run a full StructurePulse scan and return (metrics, graph, parse_results)."""
    from structurepulse.parser import parse_path
    from structurepulse.graph.builder import GraphBuilder
    from structurepulse.metrics.engine import MetricsEngine

    pr = parse_path(root)
    if not pr:
        return None, None, []
    graph = GraphBuilder().build(pr)
    metrics = MetricsEngine().compute(graph)
    return metrics, graph, pr


def _render_delta(prev: WatchState, curr_shi: float, curr_fd: float,
                  curr_coupling: float, curr_cycles: int) -> str:
    """Build Δ suffix strings."""
    def d(a, b, invert=False):
        diff = b - a
        if abs(diff) < 0.001:
            return DIM("  ±0.000")
        sign = "+" if diff > 0 else ""
        color = (GREEN if diff > 0 else RED) if not invert else (RED if diff > 0 else GREEN)
        return color(f"  {sign}{diff:+.3f}")

    return (
        f"shi {curr_shi:.3f}{d(prev.shi, curr_shi)}"
        f"  fd {curr_fd:.2f}{d(prev.fd, curr_fd)}"
        f"  coupling {curr_coupling:.2f}{d(prev.coupling, curr_coupling, invert=True)}"
        f"  cycles {curr_cycles}{d(prev.cycles, curr_cycles, invert=True)}"
    )


def _status_line(status: str, shi: float, min_shi: float) -> str:
    if shi >= min_shi:
        return GREEN(f"● HEALTHY  ({status.upper()})")
    elif shi >= min_shi - 0.15:
        return GOLD(f"▲ WARNING  ({status.upper()})")
    else:
        return RED(f"✗ CRITICAL  ({status.upper()})")


def run_watch(root: str, interval: float = 1.5, min_shi: float = 0.8,
              explain: bool = False, clear: bool = True):
    """
    Main watch loop. Blocks until Ctrl-C.
    """
    root = os.path.abspath(root)
    print(BOLD(CYAN(f"\n  StructurePulse — watching {root}")))
    print(DIM(f"  interval: {interval}s  |  min-SHI: {min_shi}  |  Ctrl-C to stop\n"))

    prev = WatchState()
    prev_mtimes: dict = {}
    last_scan_time: float = 0.0
    first_run = True

    while True:
        try:
            current_mtimes = _collect_mtimes(root)

            changed = (
                first_run or
                set(current_mtimes.keys()) != set(prev_mtimes.keys()) or
                any(current_mtimes.get(p) != prev_mtimes.get(p) for p in current_mtimes)
            )

            if changed:
                scan_start = time.time()
                metrics, graph, parse_results = _scan(root)
                scan_ms = int((time.time() - scan_start) * 1000)
                prev_mtimes = current_mtimes

                if metrics is None:
                    print(GOLD("  ⚠ no source files found"))
                    time.sleep(interval)
                    continue

                ts = datetime.now().strftime("%H:%M:%S")

                if clear and not first_run:
                    # move cursor up to overwrite previous output
                    lines_back = 7 + (len(prev.explanation) if explain and prev.explanation else 0)
                    sys.stdout.write(f"\033[{lines_back}A\033[J")
                    sys.stdout.flush()

                print(f"  {DIM(ts)}  {_status_line(metrics.status, metrics.shi, min_shi)}")
                print(f"  {_render_delta(prev, metrics.shi, metrics.fd, metrics.coupling_density, metrics.cycle_count)}")
                print()

                # Module table (top 5 by coupling)
                modules = sorted(
                    graph.module_stats.values(),
                    key=lambda m: m.coupling, reverse=True
                )[:5]
                mod_hdr = DIM("MODULE"); shi_hdr = DIM("SHI-FACTOR"); cp_hdr = DIM("COUPLING"); cx_hdr = DIM("COMPLEX"); bp_hdr = DIM("BP")
                print(f"  {mod_hdr:<32}  {shi_hdr:>12}  {cp_hdr:>10}  {cx_hdr:>8}  {bp_hdr:>4}")
                for ms in modules:
                    bp = DIM("bp") if getattr(ms, "is_boilerplate", False) else "  "
                    coupling_color = RED if ms.coupling > 0.5 else (GOLD if ms.coupling > 0.25 else DIM)
                    name = Path(ms.path).name[:30]
                    print(f"  {name:<32}  {' ':>12}  {coupling_color(f'{ms.coupling:.3f}'):>10}  {ms.avg_complexity:>8.1f}  {bp:>4}")

                print()

                if explain and metrics.explanation:
                    print(f"  {BOLD('WHY:')}")
                    for line in metrics.explanation[:4]:  # cap at 4 in watch mode
                        if "✓" in line:
                            print(f"  {GREEN('✓')}  {line}")
                        elif any(w in line for w in ("rigid","chaos","critical","cycle","Coupling")):
                            print(f"  {RED('⚠')}  {line}")
                        else:
                            print(f"  {GOLD('→')}  {line}")
                    print()

                if graph.dependency_cycles:
                    for cyc in graph.dependency_cycles[:2]:
                        chain = " → ".join(Path(c).name for c in cyc[:4])
                        print(f"  {RED('✗ CYCLE:')} {chain}")
                    print()

                # SHI threshold breach alert
                if metrics.shi < min_shi and prev.shi >= min_shi:
                    print(RED(f"  ↘ SHI DROPPED BELOW {min_shi} — architecture violation detected"))
                    print()
                elif metrics.shi >= min_shi and prev.shi < min_shi and not first_run:
                    print(GREEN(f"  ↗ SHI recovered above {min_shi}"))
                    print()

                # update state
                prev.shi = metrics.shi
                prev.fd = metrics.fd
                prev.coupling = metrics.coupling_density
                prev.cycles = metrics.cycle_count
                prev.status = metrics.status
                prev.explanation = metrics.explanation
                first_run = False

            time.sleep(interval)

        except KeyboardInterrupt:
            print(f"\n  {DIM('stopped.')}\n")
            break
        except Exception as e:
            print(RED(f"  scan error: {e}"))
            time.sleep(interval * 2)
