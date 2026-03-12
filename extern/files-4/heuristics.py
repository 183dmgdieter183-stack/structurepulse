"""
StructurePulse — Role-Inconsistency Detection (Sprint 19)

Checks naming conventions against graph topology.
The graph never lies; names do.

Four heuristic families:

  H1  Hidden Hub         — helper/utils with disproportionate centrality
  H2  Layer Inversion    — data-layer modules importing controller/service code
  H3  Responsibility Leak — config/settings calling business logic
  H4  Dead Weight        — *_service / *_handler with zero outgoing edges

Each check returns a list of InconsistencyWarning objects.
The public entry point is `run_all(graph)`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


# ── Warning model ─────────────────────────────────────────────────────────────

@dataclass
class InconsistencyWarning:
    code:      str   # H1 / H2 / H3 / H4
    kind:      str   # Human label, e.g. "Hidden Hub"
    module:    str   # Short filename
    module_path: str # Full path
    message:   str   # What was detected
    detail:    str   # Evidence (coupling value, offending edge, etc.)
    severity:  str = "warning"   # "warning" | "info"

    def __str__(self) -> str:
        return f"[{self.code}] {self.kind} — {self.module}: {self.message}"


# ── Name-classification helpers ───────────────────────────────────────────────

# Patterns that imply "I am a utility, I should stay thin"
_UTIL_PREFIXES   = ("helper", "util", "utils", "misc", "common", "shared", "tools")
_UTIL_SUFFIXES   = ("_helper", "_util", "_utils", "_helpers", "_misc", "_common")

# Data / entity layer — should not import up the stack
_DATA_PREFIXES   = ("model", "entity", "schema", "dto", "domain", "record")
_DATA_SUFFIXES   = ("_model", "_entity", "_schema", "_dto", "_domain")

# Controller / service layer — data modules must not depend on these
_LOGIC_PREFIXES  = ("controller", "service", "handler", "use_case", "usecase",
                    "interactor", "command", "query", "view", "router", "endpoint")
_LOGIC_SUFFIXES  = ("_controller", "_service", "_handler", "_use_case",
                    "_interactor", "_command", "_query", "_view", "_router")

# Config — should be purely passive
_CONFIG_PREFIXES = ("config", "settings", "conf", "env", "configuration")
_CONFIG_SUFFIXES = ("_config", "_settings", "_conf", "_env")

# Services / handlers that should have outgoing edges (do real work)
_ACTIVE_SUFFIXES = ("_service", "_handler", "_manager", "_processor",
                    "_worker", "_executor", "_job", "_task")


def _stem(path: str) -> str:
    """Return lowercase stem without extension: /a/b/my_service.py → 'my_service'"""
    return Path(path).stem.lower()


def _name(path: str) -> str:
    return Path(path).name


def _matches(stem: str, prefixes: tuple, suffixes: tuple) -> bool:
    return stem.startswith(prefixes) or stem.endswith(suffixes)


# ── Reverse graph ─────────────────────────────────────────────────────────────

def _reverse(dep_graph: dict) -> dict:
    """Return {module: set_of_modules_that_import_it}."""
    rev: dict[str, set] = {}
    for src, dsts in dep_graph.items():
        for dst in dsts:
            rev.setdefault(dst, set()).add(src)
    return rev


# ── H1: Hidden Hub ────────────────────────────────────────────────────────────

def check_hidden_hubs(graph) -> list[InconsistencyWarning]:
    """
    A module named helper/util that:
      (a) is imported by more than 50% of all other modules, OR
      (b) has coupling_density > 0.35

    Either pattern means it has grown into a God Object.
    """
    warnings: list[InconsistencyWarning] = []
    n = graph.total_modules
    if n < 3:
        return warnings   # too small to be meaningful

    rev = _reverse(graph.dependency_graph)
    all_modules = list(graph.module_stats.keys())

    for path, ms in graph.module_stats.items():
        if getattr(ms, "is_boilerplate", False):
            continue
        stem = _stem(path)
        if not _matches(stem, _UTIL_PREFIXES, _UTIL_SUFFIXES):
            continue

        importers = rev.get(path, set())
        import_ratio = len(importers) / max(n - 1, 1)
        high_coupling = ms.coupling > 0.35
        high_fan_in   = import_ratio > 0.40   # >40% of peers importing a "util" = hub smell

        if high_fan_in or high_coupling:
            if high_fan_in:
                detail = (
                    f"imported by {len(importers)}/{n-1} modules "
                    f"({import_ratio:.0%})"
                )
            else:
                detail = f"coupling_density={ms.coupling:.2f} (threshold: 0.35)"

            warnings.append(InconsistencyWarning(
                code="H1",
                kind="Hidden Hub",
                module=_name(path),
                module_path=path,
                message=(
                    f"'{_name(path)}' is named as a utility but behaves like "
                    f"a central hub."
                ),
                detail=detail,
            ))

    return warnings


# ── H2: Layer Inversion ───────────────────────────────────────────────────────

def check_layer_inversions(graph) -> list[InconsistencyWarning]:
    """
    A data/model module that imports from a controller/service module.
    This reverses the dependency arrow that clean architecture requires.
    """
    warnings: list[InconsistencyWarning] = []

    for path, ms in graph.module_stats.items():
        if getattr(ms, "is_boilerplate", False):
            continue
        stem = _stem(path)
        if not _matches(stem, _DATA_PREFIXES, _DATA_SUFFIXES):
            continue

        outgoing = graph.dependency_graph.get(path, [])
        for dep in outgoing:
            dep_stem = _stem(dep)
            if _matches(dep_stem, _LOGIC_PREFIXES, _LOGIC_SUFFIXES):
                warnings.append(InconsistencyWarning(
                    code="H2",
                    kind="Layer Inversion",
                    module=_name(path),
                    module_path=path,
                    message=(
                        f"Data-layer module '{_name(path)}' imports "
                        f"logic-layer '{_name(dep)}'."
                    ),
                    detail=(
                        f"Edge: {_name(path)} → {_name(dep)}. "
                        f"Data should never depend on controllers or services."
                    ),
                ))
                break   # one warning per module is enough

    return warnings


# ── H3: Responsibility Leak ───────────────────────────────────────────────────

def check_responsibility_leaks(graph) -> list[InconsistencyWarning]:
    """
    A config/settings module that has outgoing edges to business logic.
    Config is data; it should not call anyone.
    """
    warnings: list[InconsistencyWarning] = []

    for path, ms in graph.module_stats.items():
        # Note: do NOT skip boilerplate here — a config.py with zero functions
        # is still a config file and must be checked for responsibility leaks.
        stem = _stem(path)
        if not _matches(stem, _CONFIG_PREFIXES, _CONFIG_SUFFIXES):
            continue

        outgoing = [
            dep for dep in graph.dependency_graph.get(path, [])
            if not _matches(_stem(dep), _CONFIG_PREFIXES, _CONFIG_SUFFIXES)
        ]
        # Only flag imports that are project-internal files (exist in module_stats).
        # stdlib and third-party imports (pathlib, os, tempfile, etc.) are not leaks.
        project_paths = set(graph.module_stats.keys())
        non_trivial = [
            dep for dep in outgoing
            if dep in project_paths
        ]

        if non_trivial:
            targets = ", ".join(_name(d) for d in non_trivial[:3])
            if len(non_trivial) > 3:
                targets += f" (+{len(non_trivial)-3} more)"
            warnings.append(InconsistencyWarning(
                code="H3",
                kind="Responsibility Leak",
                module=_name(path),
                module_path=path,
                message=(
                    f"Config module '{_name(path)}' has outgoing imports "
                    f"to non-config modules."
                ),
                detail=f"Leaks to: {targets}.",
            ))

    return warnings


# ── H4: Dead Weight ───────────────────────────────────────────────────────────

def check_dead_weight(graph) -> list[InconsistencyWarning]:
    """
    A *_service / *_handler / *_manager with zero outgoing edges.
    Real services call repositories, clients, or other services.
    A service that calls nothing is either anemic or dead code.
    """
    warnings: list[InconsistencyWarning] = []

    if graph.total_modules < 3:
        return warnings

    for path, ms in graph.module_stats.items():
        if getattr(ms, "is_boilerplate", False):
            continue
        stem = _stem(path)
        if not stem.endswith(_ACTIVE_SUFFIXES):
            continue

        outgoing = graph.dependency_graph.get(path, [])
        node_count = ms.node_count   # functions + classes

        if len(outgoing) == 0 and node_count > 0:
            warnings.append(InconsistencyWarning(
                code="H4",
                kind="Dead Weight",
                module=_name(path),
                module_path=path,
                message=(
                    f"'{_name(path)}' is named as an active component but has "
                    f"no outgoing dependencies."
                ),
                detail=(
                    f"{node_count} node(s) defined, 0 outgoing edges. "
                    f"Either extract its logic or remove it."
                ),
                severity="info",
            ))

    return warnings


# ── Entry point ───────────────────────────────────────────────────────────────

def run_all(graph) -> list[InconsistencyWarning]:
    """Run all four heuristic families and return a merged list."""
    results: list[InconsistencyWarning] = []
    results.extend(check_hidden_hubs(graph))
    results.extend(check_layer_inversions(graph))
    results.extend(check_responsibility_leaks(graph))
    results.extend(check_dead_weight(graph))
    # Sort by severity (warnings before info), then by code
    results.sort(key=lambda w: (0 if w.severity == "warning" else 1, w.code))
    return results
