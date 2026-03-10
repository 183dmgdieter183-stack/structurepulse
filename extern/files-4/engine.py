"""
StructurePulse — Metrics Engine
Computes FD (Higuchi Fractal Dimension) + SHI (Structural Health Index).

FD is computed on the commit time-series of structural signals.
For a single snapshot (no git history), FD is estimated from
module-level complexity distribution as a spatial series.

SHI = w1*FD_norm + w2*entropy_norm + w3*coupling_norm +
      w4*volatility_norm + w5*test_topology_norm
"""
import math
from dataclasses import dataclass, field
from structurepulse.graph.builder import GraphResult


# ── FD Band constants ──────────────────────────────────────────────────────
FD_MIN = 1.0
FD_MAX = 2.0
FD_OPTIMAL_LOW  = 1.7
FD_OPTIMAL_HIGH = 1.9

# ── SHI weights (default, configurable) ───────────────────────────────────
DEFAULT_WEIGHTS = {
    "fd":           0.30,
    "entropy":      0.20,
    "coupling":     0.25,
    "volatility":   0.15,
    "test_topology":0.10,
}


@dataclass
class MetricsResult:
    # raw
    fd: float = 0.0
    graph_entropy: float = 0.0
    coupling_density: float = 0.0
    avg_complexity: float = 1.0
    cycle_count: int = 0

    # normalised [0,1] — higher = healthier
    fd_score: float = 0.0
    entropy_score: float = 0.0
    coupling_score: float = 0.0
    volatility_score: float = 1.0     # 1.0 if no history
    test_score: float = 0.5           # 0.5 if unknown

    # composite
    shi: float = 0.0
    status: str = "unknown"           # stable | warning | critical | rigid | chaos
    fd_status: str = "unknown"        # optimal | rigid | chaos

    weights: dict = field(default_factory=dict)
    explanation: list = field(default_factory=list)  # human-readable root cause lines
    boilerplate_excluded: int = 0   # number of boilerplate modules excluded from FD
    inconsistencies: list = field(default_factory=list)  # InconsistencyWarning list

    def explain_text(self) -> str:
        """Return full explanation as a formatted string."""
        if not self.explanation:
            return "  No issues detected."
        return "\n".join(f"  {line}" for line in self.explanation)


class MetricsEngine:
    def __init__(self, weights: dict = None):
        self.weights = weights or DEFAULT_WEIGHTS

    def compute(self, graph: GraphResult,
                commit_series: list[dict] = None) -> MetricsResult:
        r = MetricsResult(weights=self.weights)

        # ── FD ────────────────────────────────────────────────────────────
        if commit_series and len(commit_series) >= 6:
            # FD on structural signal over time
            series = [c.get("node_count", 0) for c in commit_series]
            r.fd = self._higuchi_fd(series, k_max=4)
        else:
            # snapshot estimate: FD on complexity distribution across modules
            # exclude boilerplate modules (empty __init__.py etc.) — they flatten the signal
            complexities = [
                ms.avg_complexity for ms in graph.module_stats.values()
                if not getattr(ms, "is_boilerplate", False)
            ]
            # fall back to all modules if filtering leaves too few
            if len(complexities) < 2:
                complexities = [ms.avg_complexity for ms in graph.module_stats.values()]
            if len(complexities) >= 8:
                r.fd = self._higuchi_fd(complexities, k_max=min(4, len(complexities)//2))
            elif len(complexities) >= 4:
                # small repo: reduce k_max to avoid noise amplification
                r.fd = self._higuchi_fd(complexities, k_max=2)
                # clamp to plausible range for small repos
                r.fd = max(1.6, min(1.95, r.fd))
            else:
                r.fd = 1.8  # insufficient data → assume optimal band

        r.fd_status = self._fd_status(r.fd)
        r.fd_score = self._fd_score(r.fd)

        # ── Graph Entropy ─────────────────────────────────────────────────
        degrees = [len(v) for v in graph.dependency_graph.values()]
        r.graph_entropy = self._shannon_entropy(degrees)
        # normalise: entropy 0 (star/chain) → 1 (balanced) → 2+ (chaotic)
        # healthy range: 0.3–1.2 nats
        r.entropy_score = self._clamp(1.0 - abs(r.graph_entropy - 0.75) / 1.5)

        # ── Coupling ──────────────────────────────────────────────────────
        r.coupling_density = graph.coupling_density
        r.cycle_count = graph.cycle_count
        # coupling 0 = perfect, 1 = maximally coupled
        # cycle penalty: each cycle reduces score by 0.05
        raw_coupling_score = 1.0 - r.coupling_density
        cycle_penalty = min(0.4, r.cycle_count * 0.05)
        r.coupling_score = self._clamp(raw_coupling_score - cycle_penalty)

        # ── Avg Complexity (used in SHI via coupling proxy) ───────────────
        all_c = [ms.avg_complexity for ms in graph.module_stats.values()]
        r.avg_complexity = round(sum(all_c) / len(all_c), 2) if all_c else 1.0

        # ── SHI ───────────────────────────────────────────────────────────
        w = self.weights
        r.shi = round(
            w["fd"]           * r.fd_score +
            w["entropy"]      * r.entropy_score +
            w["coupling"]     * r.coupling_score +
            w["volatility"]   * r.volatility_score +
            w["test_topology"]* r.test_score,
            3
        )

        # ── Status ────────────────────────────────────────────────────────
        if r.shi >= 0.80:
            r.status = "stable"
        elif r.shi >= 0.65:
            r.status = "warning"
        else:
            r.status = "critical"

        # override if FD is clearly out of band
        if r.fd < 1.5:
            r.status = "rigid"
        elif r.fd > 1.95:
            r.status = "chaos"

        # ── Explanation (root cause analysis) ────────────────────────────
        r.explanation = self._explain(r, graph)

        # ── Role-Inconsistency Heuristics ─────────────────────────────────
        from structurepulse.metrics.heuristics import run_all as _heuristics
        r.inconsistencies = _heuristics(graph)

        return r

    def _explain(self, r: "MetricsResult", graph: "GraphResult") -> list[str]:
        """Translate metric values into human-readable root cause sentences."""
        lines = []
        n_modules = len(graph.module_stats)

        # ── FD ────────────────────────────────────────────────────────────
        if r.fd_status == "rigid":
            complexities = [ms.avg_complexity for ms in graph.module_stats.values()
                            if not getattr(ms, "is_boilerplate", False)]
            c_range = max(complexities) - min(complexities) if len(complexities) >= 2 else 0
            lines.append(
                f"FD {r.fd:.2f} (rigid, target 1.7–1.9): complexity signal is too uniform."
            )
            if c_range < 2.0:
                lines.append(
                    f"  All {n_modules} modules have similar complexity (range: {c_range:.1f}). "
                    f"The Higuchi algorithm needs asymmetry to produce FD > 1.7."
                )
            if n_modules < 6:
                lines.append(
                    f"  Only {n_modules} modules — Higuchi needs 6+ data points for a reliable signal. "
                    f"FD will normalise as the codebase grows."
                )
            if True:  # no time-series history (would be populated by git integration)
                lines.append(
                    "  No commit history detected. With 6+ commits the time-series mode activates, "
                    "which is more reliable than the snapshot estimate."
                )
            lines.append(
                "  To improve: add a core module with heavier logic (complexity 5+), or "
                "split uniform modules into a thin handler + a fat processor."
            )

        elif r.fd_status == "chaos":
            lines.append(
                f"FD {r.fd:.2f} (chaos, target 1.7–1.9): complexity is wildly uneven."
            )
            complexities = sorted(
                [(name, ms.avg_complexity) for name, ms in graph.module_stats.items()],
                key=lambda x: x[1], reverse=True
            )
            if complexities:
                top = complexities[0]
                lines.append(
                    f"  Hotspot: '{top[0]}' has avg complexity {top[1]:.1f}, "
                    f"much higher than the rest. Consider splitting it."
                )
            lines.append(
                "  To improve: break the highest-complexity module into smaller, "
                "focused modules until complexity variance is more even."
            )

        else:
            lines.append(
                f"FD {r.fd:.2f} (optimal band 1.7–1.9). ✓"
            )

        # ── Coupling ──────────────────────────────────────────────────────
        if r.coupling_density > 0.50:
            lines.append(
                f"Coupling {r.coupling_density:.2f} (target < 0.4): modules are too interconnected."
            )
            if r.cycle_count > 0:
                lines.append(
                    f"  {r.cycle_count} dependency cycle(s) detected. Each cycle compounds "
                    f"the coupling score. Resolve cycles first."
                )
            lines.append(
                "  To improve: identify which module imports the most others and extract "
                "its dependencies behind an interface or service layer."
            )
        elif r.coupling_density > 0.25:
            lines.append(f"Coupling {r.coupling_density:.2f} (moderate). Monitor as codebase grows.")

        # ── Cycles ────────────────────────────────────────────────────────
        if r.cycle_count > 0:
            cycles = graph.dependency_cycles
            if cycles:
                first = " → ".join(str(n) for n in cycles[0][:4])
                if len(cycles[0]) > 4:
                    first += " → ..."
                lines.append(
                    f"{r.cycle_count} dependency cycle(s). First cycle: {first}"
                )
            lines.append(
                "  To fix: introduce a shared interface module that both sides depend on, "
                "breaking the circular chain."
            )

        # ── SHI ───────────────────────────────────────────────────────────
        if r.shi < 0.65:
            gap = round(0.80 - r.shi, 3)
            lines.append(
                f"SHI {r.shi:.3f} (critical, target ≥ 0.8). Gap to stable: {gap}."
            )
            # Identify the biggest drag on SHI
            w = r.weights
            scores = {
                "FD":        (w.get("fd", 0.30),         r.fd_score),
                "Coupling":  (w.get("coupling", 0.25),   r.coupling_score),
                "Entropy":   (w.get("entropy", 0.20),    r.entropy_score),
                "Volatility":(w.get("volatility", 0.15), r.volatility_score),
                "Tests":     (w.get("test_topology",0.10),r.test_score),
            }
            worst = min(scores.items(), key=lambda x: x[1][0] * x[1][1])
            lines.append(
                f"  Biggest drag: {worst[0]} (weight {worst[1][0]:.0%}, score {worst[1][1]:.2f}). "
                f"Improving this component has the highest SHI impact."
            )
        elif r.shi < 0.80:
            gap = round(0.80 - r.shi, 3)
            lines.append(
                f"SHI {r.shi:.3f} (warning). {gap} short of stable threshold (0.8)."
            )

        return lines

    # ── Higuchi Fractal Dimension ──────────────────────────────────────────
    def _higuchi_fd(self, series: list[float], k_max: int = 4) -> float:
        """
        Higuchi (1988) algorithm.
        Returns FD in [1.0, 2.0].
        """
        N = len(series)
        if N < 4:
            return 1.8

        lk_vals = []
        k_vals = []

        for k in range(1, k_max + 1):
            lm = []
            for m in range(1, k + 1):
                # number of terms
                n_terms = (N - m) // k
                if n_terms < 1:
                    continue
                inner = sum(
                    abs(series[m - 1 + i * k] - series[m - 1 + (i - 1) * k])
                    for i in range(1, n_terms + 1)
                )
                norm = (N - 1) / (n_terms * k)
                lm.append(inner * norm / k)

            if lm:
                lk_vals.append(math.log(sum(lm) / len(lm)) if sum(lm)/len(lm) > 0 else 0)
                k_vals.append(math.log(1.0 / k))

        if len(k_vals) < 2:
            return 1.8

        # linear regression slope = FD
        fd = self._linreg_slope(k_vals, lk_vals)
        return round(self._clamp(fd, 1.0, 2.0), 4)

    def _fd_status(self, fd: float) -> str:
        if fd < FD_OPTIMAL_LOW:
            return "rigid"
        if fd > FD_OPTIMAL_HIGH:
            return "chaos"
        return "optimal"

    def _fd_score(self, fd: float) -> float:
        """Score 1.0 at centre of optimal band, falling toward edges."""
        centre = (FD_OPTIMAL_LOW + FD_OPTIMAL_HIGH) / 2   # 1.8
        half = (FD_OPTIMAL_HIGH - FD_OPTIMAL_LOW) / 2      # 0.1
        dist = abs(fd - centre)
        score = 1.0 - (dist / (half + 0.3))
        return round(self._clamp(score), 3)

    # ── Shannon Entropy ───────────────────────────────────────────────────
    def _shannon_entropy(self, counts: list[int]) -> float:
        total = sum(counts)
        if total == 0:
            return 0.0
        probs = [c / total for c in counts if c > 0]
        return round(-sum(p * math.log(p) for p in probs), 4)

    # ── Linear Regression Slope ───────────────────────────────────────────
    def _linreg_slope(self, x: list, y: list) -> float:
        n = len(x)
        if n < 2:
            return 1.8
        sx = sum(x)
        sy = sum(y)
        sxy = sum(xi * yi for xi, yi in zip(x, y))
        sxx = sum(xi * xi for xi in x)
        denom = n * sxx - sx * sx
        if denom == 0:
            return 1.8
        return (n * sxy - sx * sy) / denom

    def _clamp(self, val: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, val))
