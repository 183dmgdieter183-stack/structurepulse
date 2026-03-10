#!/usr/bin/env python3
"""
StructurePulse CLI
Usage:
  structurepulse scan [PATH]          Full structural analysis
  structurepulse diff [COMMIT_RANGE]  Structural diff (requires git)
  structurepulse log [--last N]       Show decision store
  structurepulse decide               Interactively log a decision
"""
import sys
import os
import json
import argparse
from pathlib import Path
from dataclasses import asdict

# allow running from repo root without install
sys.path.insert(0, str(Path(__file__).parent.parent))

from structurepulse.parser import parse_path
from structurepulse.graph.builder import GraphBuilder
from structurepulse.metrics.engine import MetricsEngine
from structurepulse.diff.structural_diff import StructuralDiffer, format_diff_cli
from dataclasses import asdict
from structurepulse.store.decision_store import DecisionStore, format_decisions_cli


# ── ANSI colours ──────────────────────────────────────────────────────────
def _c(text, code): return f"\033[{code}m{text}\033[0m"
GREEN  = lambda t: _c(t, "32")
GOLD   = lambda t: _c(t, "33")
RED    = lambda t: _c(t, "31")
CYAN   = lambda t: _c(t, "36")
DIM    = lambda t: _c(t, "2")
BOLD   = lambda t: _c(t, "1")
WHITE  = lambda t: _c(t, "37")


def cmd_scan(args):
    path = args.path or "."
    path = os.path.abspath(path)
    json_out = getattr(args, "json", False)

    if not json_out:
        print(BOLD(CYAN(f"\n  StructurePulse — scanning {path}")))
        print(DIM("  " + "─" * 52))

    # 1. parse
    parse_results = parse_path(path)
    if not parse_results:
        print(RED("  No Python or TypeScript files found."))
        sys.exit(1)

    # 2. graph
    builder = GraphBuilder()
    graph = builder.build(parse_results)

    # 3. metrics
    engine = MetricsEngine()
    metrics = engine.compute(graph)

    # 4. assemble output
    output = {
        "path": path,
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
        "modules": {
            ms.path: {
                "loc": ms.loc_code,
                "nodes": ms.node_count,
                "coupling": ms.coupling,
                "cohesion": ms.cohesion,
                "avg_complexity": ms.avg_complexity,
                "import_count": ms.import_count,
                "errors": ms.parse_errors,
            }
            for ms in graph.module_stats.values()
        },
        "dependency_cycles": graph.dependency_cycles,
        "parse_errors": [
            {"file": pr.file, "errors": pr.errors}
            for pr in parse_results if pr.errors
        ],
    }

    if json_out:
        print(json.dumps(output, indent=2))
        return

    # ── human output ──────────────────────────────────────────────────────
    fp = graph.fingerprint
    m = metrics

    status_color = GREEN if m.status == "stable" else (GOLD if m.status == "warning" else RED)

    print(f"\n  {BOLD('FINGERPRINT')}")
    print(f"  languages:    {', '.join(fp.get('languages', []))}")
    print(f"  modules:      {fp.get('modules', 0)}")
    print(f"  total nodes:  {fp.get('total_nodes', 0)}")
    print(f"  avg LOC/mod:  {fp.get('avg_module_loc', 0)}")
    print(f"  architecture: {fp.get('architecture_style', '?')}")
    print()

    print(f"  {BOLD('STRUCTURAL HEALTH')}")
    print(f"  fd:           {m.fd}  [{_fd_bar(m.fd)}]  {m.fd_status}")
    print(f"  shi:          {m.shi}  {status_color(m.status.upper())}")
    print(f"  coupling:     {m.coupling_density}")
    print(f"  cycles:       {m.cycle_count}")
    print(f"  entropy:      {m.graph_entropy}")
    print(f"  complexity:   {m.avg_complexity}")
    print()

    if graph.dependency_cycles:
        print(f"  {GOLD('⚠ DEPENDENCY CYCLES')}")
        for cycle in graph.dependency_cycles[:5]:
            print(f"  → {' → '.join(Path(c).name for c in cycle)}")
        print()

    errors = [pr for pr in parse_results if pr.errors]
    if errors:
        print(f"  {DIM('PARSE ERRORS')}")
        for pr in errors:
            for e in pr.errors:
                print(f"  {Path(pr.file).name}: {e}")
        print()

    print(DIM("  " + "─" * 52))
    print(f"  {DIM('run with --json for machine-readable output')}\n")


def cmd_diff(args):
    path = os.path.abspath(getattr(args, "path", ".") or ".")
    commit_range = getattr(args, "range", "HEAD~1..HEAD") or "HEAD~1..HEAD"
    json_out = getattr(args, "json", False)

    from structurepulse.diff.git_integration import GitIntegration, parse_commit_range

    try:
        git = GitIntegration(path)
    except ValueError as e:
        print(RED(f"  {e}"))
        print(DIM("  structurepulse diff requires a git repository."))
        sys.exit(1)

    ref_before, ref_after = parse_commit_range(commit_range)

    try:
        commit_before = git.resolve_commit(ref_before)[:8]
        commit_after  = git.resolve_commit(ref_after)[:8]
    except ValueError as e:
        print(RED(f"  {e}"))
        sys.exit(1)

    if not json_out:
        print(BOLD(CYAN("\n  StructurePulse -- structural diff")))
        print(DIM(f"  {ref_before} ({commit_before}) -> {ref_after} ({commit_after})"))
        print(DIM("  " + "─" * 52))

    engine = MetricsEngine()

    try:
        metrics_before, graph_before = git.scan_at_commit(ref_before, engine)
        metrics_after,  graph_after  = git.scan_at_commit(ref_after,  engine)
    except Exception as e:
        print(RED(f"  scan failed: {e}"))
        sys.exit(1)

    # enrich with time-series FD if history available
    history = git.get_commit_history(limit=20)
    if len(history) >= 6:
        # add node_count per commit for FD time-series
        for entry in history:
            entry["node_count"] = graph_after.total_nodes  # approximation; full per-commit scan = Sprint 2
        metrics_before.fd = engine._higuchi_fd(
            [c["insertions"] + 1 for c in reversed(history)], k_max=4
        )
        metrics_before.fd = max(1.0, min(2.0, metrics_before.fd))

    changed_files = git.get_changed_files(ref_before, ref_after)
    msg_after = git.get_commit_message(ref_after)

    differ = StructuralDiffer()
    diff = differ.diff(metrics_before, metrics_after, commit_before, commit_after)

    if json_out:
        def _df(f): return {"before": f.before, "after": f.after,
                            "delta": f.delta, "severity": f.severity}
        print(json.dumps({
            "commit_before": commit_before,
            "commit_after":  commit_after,
            "message": msg_after,
            "changed_files": changed_files,
            "fd":       _df(diff.fd),
            "shi":      _df(diff.shi),
            "coupling": _df(diff.coupling),
            "cycles":   _df(diff.cycles),
            "complexity": _df(diff.avg_complexity),
            "verdict":  diff.verdict,
            "reasons":  diff.verdict_reasons,
        }, indent=2))
        return

    if msg_after:
        print(f"  commit: {GOLD(msg_after)}")
    if changed_files:
        print(f"  files:  {len(changed_files)} changed ({', '.join(Path(f).name for f in changed_files[:4])}{'...' if len(changed_files)>4 else ''})")
    print()
    print(format_diff_cli(diff))

    verdict_color = GREEN if diff.verdict == "ok" else (GOLD if diff.verdict == "warn" else RED)
    print(f"\n  overall: {verdict_color(diff.verdict.upper())}\n")


def cmd_log(args):
    path = os.path.abspath(getattr(args, "path", ".") or ".")
    limit = getattr(args, "last", None)
    module = getattr(args, "module", None)

    store = DecisionStore(path)
    decisions = store.filter(module=module, limit=limit)

    print(BOLD(CYAN(f"\n  StructurePulse — decision log ({len(decisions)} entries)")))
    print(DIM("  " + "─" * 52))
    print(format_decisions_cli(decisions))


def cmd_decide(args):
    path = os.path.abspath(getattr(args, "path", ".") or ".")
    store = DecisionStore(path)

    print(BOLD(CYAN("\n  StructurePulse — log architectural decision")))
    print(DIM("  (Ctrl+C to cancel)\n"))

    context  = input("  Context  (what situation?): ").strip()
    decision = input("  Decision (what was chosen?): ").strip()
    module   = input("  Module   (affected file, optional): ").strip()
    alts     = input("  Alternatives considered (comma-sep, optional): ").strip()
    tags     = input("  Tags (comma-sep, optional): ").strip()

    alt_list = [a.strip() for a in alts.split(",") if a.strip()]
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    d = store.auto_log(
        context=context,
        decision=decision,
        module=module,
        alternatives=alt_list,
        tags=tag_list,
    )
    print(GREEN(f"\n  ✓ logged as {d.id}\n"))


# ── FD visualisation bar ──────────────────────────────────────────────────
def _fd_bar(fd: float) -> str:
    """ASCII bar showing FD position in [1.0, 2.0] with optimal zone."""
    total = 20
    pos = int((fd - 1.0) * total)
    pos = max(0, min(total - 1, pos))
    bar = list("." * total)
    # mark optimal zone 1.7–1.9 = pos 14–18
    for i in range(14, 19):
        bar[i] = "░"
    bar[pos] = "█"
    return "".join(bar) + f"  1.0←[{'░░░░░'}]→2.0"


def cmd_install_hook(args):
    path = os.path.abspath(getattr(args, "path", ".") or ".")
    pre_push = getattr(args, "pre_push", False)
    from structurepulse.hooks.install import HookInstaller
    try:
        installer = HookInstaller(path)
    except ValueError as e:
        print(RED(f"  {e}"))
        sys.exit(1)
    results = installer.install(pre_push=pre_push)
    print(BOLD(CYAN("\n  StructurePulse — hook installation")))
    for hook, status in results.items():
        icon = GREEN("✓") if "installed" in status else GOLD("!")
        print(f"  {icon}  {hook}: {status}")
    print(DIM("\n  Every commit will now show a structural diff."))
    if pre_push:
        print(DIM("  Pushes with BLOCK verdict will be rejected (override: git push --no-verify)."))
    print()


def cmd_remove_hook(args):
    path = os.path.abspath(getattr(args, "path", ".") or ".")
    from structurepulse.hooks.install import HookInstaller
    try:
        installer = HookInstaller(path)
    except ValueError as e:
        print(RED(f"  {e}"))
        sys.exit(1)
    results = installer.remove()
    print(BOLD(CYAN("\n  StructurePulse — hook removal")))
    for hook, status in results.items():
        print(f"  {DIM(hook)}: {status}")
    print()


def cmd_hook_status(args):
    path = os.path.abspath(getattr(args, "path", ".") or ".")
    from structurepulse.hooks.install import HookInstaller
    try:
        installer = HookInstaller(path)
    except ValueError as e:
        print(RED(f"  {e}"))
        sys.exit(1)
    results = installer.status()
    print(BOLD(CYAN("\n  StructurePulse — hook status")))
    for hook, status in results.items():
        color = GREEN if status == "installed" else DIM
        print(f"  {hook}: {color(status)}")
    print()



# ── Sprint 2 commands ─────────────────────────────────────────────────────────

def cmd_lib(args):
    sub = args.lib_command
    path = os.path.abspath(getattr(args, "path", ".") or ".")
    from structurepulse.library.agent_library import AgentLibrary, format_library_cli
    from structurepulse.agent.api import AgentAPI

    lib = AgentLibrary(path)
    api = AgentAPI(path)

    if sub == "list":
        entries = lib.search(limit=50)
        print(BOLD(CYAN(f"\n  StructurePulse Library ({len(entries)} entries)")))
        print(DIM("  " + "-" * 52))
        print(format_library_cli(entries))

    elif sub == "add":
        src = getattr(args, "source", None)
        if not src:
            print(RED("  --source required")); return
        name = getattr(args, "name", None) or Path(src).stem
        desc = getattr(args, "desc", "") or ""
        tags = [t.strip() for t in (getattr(args, "tags", "") or "").split(",") if t.strip()]
        result = api.library_add(src, name, description=desc, tags=tags)
        entry = result["added"]
        print(GREEN(f"\n  Added: {entry['id']} — {entry['name']}  SHI={entry['shi']:.2f}\n"))

    elif sub == "search":
        q = getattr(args, "query", "") or ""
        lang = getattr(args, "language", None)
        results = lib.search(query=q, language=lang, limit=10)
        print(BOLD(CYAN(f"\n  Library search: '{q}' ({len(results)} results)")))
        print(format_library_cli(results))

    elif sub == "show":
        entry_id = getattr(args, "id", None)
        entry = lib.get(entry_id) if entry_id else None
        if not entry:
            print(RED(f"  Not found: {entry_id}")); return
        print(json.dumps(asdict(entry) if hasattr(entry,"__dataclass_fields__") else vars(entry), indent=2, default=str))


def cmd_sandbox(args):
    sub = args.sandbox_command
    path = os.path.abspath(getattr(args, "path", ".") or ".")
    from structurepulse.sandbox.sandbox_lab import SandboxLab, format_sandbox_cli
    from structurepulse.agent.api import AgentAPI

    sandbox = SandboxLab(path)
    api = AgentAPI(path)

    if sub == "list":
        experiments = sandbox.read_all()
        print(BOLD(CYAN(f"\n  StructurePulse Sandbox ({len(experiments)} experiments)")))
        print(DIM("  " + "-" * 52))
        print(format_sandbox_cli(experiments))

    elif sub == "create":
        sources = getattr(args, "sources", None) or []
        name = getattr(args, "name", "") or "experiment"
        hyp = getattr(args, "hypothesis", "") or ""
        result = api.sandbox_create(name=name, source_paths=sources, hypothesis=hyp)
        exp = result["experiment"]
        print(GREEN(f"\n  Created sandbox: {exp['id']}"))
        print(f"  Path: {exp['sandbox_path']}")
        print(DIM(f"  {result['next_step']}\n"))

    elif sub == "scan":
        exp_id = getattr(args, "id", None)
        if not exp_id:
            print(RED("  experiment id required")); return
        result = api.sandbox_scan(exp_id)
        print(json.dumps(result, indent=2))

    elif sub == "promote":
        exp_id = getattr(args, "id", None)
        lib_name = getattr(args, "name", "") or exp_id
        if not exp_id:
            print(RED("  experiment id required")); return
        result = api.sandbox_promote(exp_id, library_name=lib_name)
        print(GREEN(f"\n  Promoted {exp_id} -> library/{result['library_id']}\n"))


def cmd_plan(args):
    path = os.path.abspath(getattr(args, "path", ".") or ".")
    problem = " ".join(getattr(args, "problem", []) or [])
    sources = getattr(args, "sources", None) or []
    lang = getattr(args, "language", None)
    json_out = getattr(args, "json", False)
    auto_sb = getattr(args, "sandbox", False)

    from structurepulse.agent.api import AgentAPI
    api = AgentAPI(path)
    result = api.plan(problem, source_paths=sources or None,
                      language=lang, auto_sandbox=auto_sb)

    if json_out:
        print(json.dumps(result, indent=2))
        return

    from structurepulse.planner.agent_planner import PlannerResult, format_planner_cli
    pr = PlannerResult(**result)
    print(BOLD(CYAN("\n  StructurePulse Planner")))
    print(DIM("  " + "-" * 52))
    for line in format_planner_cli(pr):
        print(line)
    print(BOLD("  Agent Prompt:"))
    print(DIM("  " + "-" * 52))
    for line in result.get("agent_prompt","").splitlines():
        print(f"  {line}")
    print()


def cmd_agent(args):
    """Entry point for all agent sub-commands — always outputs JSON."""
    sub = args.agent_command
    path = os.path.abspath(getattr(args, "path", ".") or ".")
    from structurepulse.agent.api import AgentAPI
    api = AgentAPI(path)

    if sub == "scan":
        print(json.dumps(api.scan(path), indent=2))

    elif sub == "plan":
        problem = " ".join(getattr(args, "problem", []) or [])
        sources = getattr(args, "sources", None) or []
        result = api.plan(problem, source_paths=sources or None,
                          auto_sandbox=getattr(args, "sandbox", False))
        print(json.dumps(result, indent=2))

    elif sub == "prompt":
        problem = " ".join(getattr(args, "problem", []) or [])
        sources = getattr(args, "sources", None) or []
        result = api.generate_prompt(problem, source_paths=sources or None)
        print(json.dumps(result, indent=2))

    elif sub == "search":
        q = " ".join(getattr(args, "query", []) or [])
        result = api.library_search(q, language=getattr(args, "language", None))
        print(json.dumps(result, indent=2))

    else:
        print(json.dumps({"error": f"unknown agent sub-command: {sub}"}))


# ── Sprint 3 commands ─────────────────────────────────────────────────────────

def cmd_pattern(args):
    sub = args.pattern_command
    path = os.path.abspath(getattr(args, "path", ".") or ".")
    from structurepulse.library.pattern_library import PatternLibrary, format_patterns_cli

    lib = PatternLibrary(path)

    if sub == "list":
        tag  = getattr(args, "tag", None)
        lang = getattr(args, "language", None)
        arch = getattr(args, "arch", None)
        patterns = lib.list(tag=tag, language=lang, architecture=arch)
        print(BOLD(CYAN(f"\n  StructurePulse Pattern Library ({len(patterns)} patterns)")))
        print(DIM("  " + "-" * 52))
        print(format_patterns_cli(patterns))

    elif sub == "use":
        pid    = getattr(args, "id", None)
        outdir = getattr(args, "output", None)
        if not pid or not outdir:
            print(RED("  pattern id and --output required")); return
        try:
            created = lib.instantiate(pid, outdir)
            pattern = lib.get(pid)
            print(GREEN(f"\n  Pattern '{pid}' instantiated -> {outdir}"))
            for fname in created:
                print(f"  + {fname}")
            if pattern:
                print(DIM(f"\n  Invariants:"))
                for inv in pattern.invariants:
                    print(f"  · {inv}")
            print()
        except ValueError as e:
            print(RED(f"  {e}"))

    elif sub == "show":
        pid = getattr(args, "id", None)
        p = lib.get(pid)
        if not p:
            print(RED(f"  Pattern not found: {pid}")); return
        print(BOLD(CYAN(f"\n  {p.name}")))
        print(f"  {p.description}")
        print(f"  architecture: {p.architecture}  |  FD target: {p.fd_target}  |  SHI min: {p.shi_min}")
        print(DIM("\n  Invariants:"))
        for inv in p.invariants:
            print(f"  · {inv}")
        print(DIM("\n  Files:"))
        for fname in p.structure:
            print(f"  · {fname}")
        print()


def cmd_claude(args):
    sub = args.claude_command
    path = os.path.abspath(getattr(args, "path", ".") or ".")
    from structurepulse.integrations.claude_code import (
        CLAUDE_CODE_TOOLS, CLAUDE_CODE_SYSTEM_PROMPT, generate_claude_md
    )

    if sub == "tools":
        print(json.dumps({"tools": CLAUDE_CODE_TOOLS}, indent=2))

    elif sub == "prompt":
        print(CLAUDE_CODE_SYSTEM_PROMPT)

    elif sub == "init":
        # write CLAUDE.md into the target repo
        claude_md = generate_claude_md(str(Path(__file__).parent.parent.parent))
        dest = Path(path) / "CLAUDE.md"
        dest.write_text(claude_md, encoding="utf-8")
        print(GREEN(f"\n  CLAUDE.md written to {dest}"))
        print(DIM("  Claude Code will read this file automatically.\n"))

    elif sub == "run":
        # direct subprocess call to a tool
        tool_name = getattr(args, "tool", None)
        raw_args  = getattr(args, "args", None) or "{}"
        if not tool_name:
            print(RED("  --tool required")); return
        from structurepulse.integrations.claude_code import _run_tool
        result = _run_tool(tool_name, json.loads(raw_args))
        print(json.dumps(result, indent=2))


# ── Sprint 4 commands ─────────────────────────────────────────────────────────

def cmd_network(args):
    sub = args.network_command
    path = os.path.abspath(getattr(args, "path", ".") or ".")
    json_out = getattr(args, "json", False)

    from structurepulse.library.agent_library import AgentLibrary
    from structurepulse.network.peer_registry import PeerRegistry, format_peers_cli
    from structurepulse.network.sync_engine import SyncEngine, format_sync_log_cli
    from structurepulse.network.bundle import BundleBuilder, BundleReader

    library = AgentLibrary(path)
    registry = PeerRegistry(path)
    engine = SyncEngine(path)

    # ── export ──────────────────────────────────────────────────────────
    if sub == "export":
        shi = getattr(args, "min_shi", 0.65) or 0.65
        out = getattr(args, "output", None)

        if out:
            # explicit output path
            builder = BundleBuilder()
            manifest = builder.build(
                library=library,
                output_path=out,
                shi_threshold=shi,
            )
            print(GREEN(f"\n  Bundle written: {out}"))
            print(f"  entries: {manifest.entry_count}  |  SHI threshold: {shi}")
            print(f"  merkle:  {manifest.merkle_root[:16]}...\n")
        else:
            # auto-export to .structurepulse/export.sptgz
            bundle_path = registry.auto_export(library, shi_threshold=shi)
            print(GREEN(f"\n  Auto-export: {bundle_path}"))
            print(DIM("  Peers with file transport pointing to this repo can now sync.\n"))

    # ── add-peer ─────────────────────────────────────────────────────────
    elif sub == "add-peer":
        name    = getattr(args, "name", "") or "unnamed"
        address = getattr(args, "address", "")
        trust   = getattr(args, "trust", "low") or "low"
        min_shi = getattr(args, "min_shi", 0.65) or 0.65
        tags    = [t.strip() for t in (getattr(args, "tags", "") or "").split(",") if t.strip()]

        if not address:
            print(RED("  --address required")); return

        transport = "http" if address.startswith("http") else "file"
        peer = registry.add(name=name, address=address, transport=transport,
                            trust_level=trust, min_shi=min_shi, tags_filter=tags)
        print(GREEN(f"\n  Peer added: {peer.id} — {peer.name}"))
        print(f"  {peer.transport}://{peer.address}  |  trust: {peer.trust_level}  |  min_shi: {peer.min_shi}\n")

    # ── remove-peer ───────────────────────────────────────────────────────
    elif sub == "remove-peer":
        peer_id = getattr(args, "id", None)
        if registry.remove(peer_id):
            print(GREEN(f"\n  Removed: {peer_id}\n"))
        else:
            print(RED(f"\n  Not found: {peer_id}\n"))

    # ── peers ─────────────────────────────────────────────────────────────
    elif sub == "peers":
        peers = registry.read_all()
        print(BOLD(CYAN(f"\n  StructurePulse Network ({len(peers)} peers)")))
        print(DIM("  " + "-" * 52))
        print(format_peers_cli(peers))

    # ── sync ──────────────────────────────────────────────────────────────
    elif sub == "sync":
        peer_id  = getattr(args, "peer", None)
        dry_run  = getattr(args, "dry_run", False)

        if peer_id:
            peer = registry.get(peer_id)
            if not peer:
                print(RED(f"  Peer not found: {peer_id}")); return
            print(BOLD(CYAN(f"\n  Syncing from {peer.name}...")))
            event = engine.sync_peer(peer, registry, library, dry_run=dry_run)
            events = [event]
        else:
            print(BOLD(CYAN("\n  Syncing from all active peers...")))
            events = engine.sync_all(registry, library, dry_run=dry_run)

        for event in events:
            ok_color = GREEN if event.validation_passed else RED
            print(f"  {event.peer_name}: "
                  f"{ok_color('OK') if event.validation_passed else ok_color('FAIL')}  "
                  f"+{event.entries_imported} imported  ~{event.entries_skipped} skipped")
            if event.errors:
                for e in event.errors:
                    print(f"    {RED('!')} {e}")
        if dry_run:
            print(DIM("\n  (dry run — nothing actually imported)"))
        print()

    # ── validate ──────────────────────────────────────────────────────────
    elif sub == "validate":
        bundle_path = getattr(args, "bundle", None)
        if not bundle_path:
            print(RED("  bundle path required")); return
        reader = BundleReader()
        result = reader.validate(bundle_path)
        if json_out:
            print(json.dumps(result, indent=2))
            return
        status = GREEN("VALID") if result["valid"] else RED("INVALID")
        print(f"\n  {status}  {bundle_path}")
        print(f"  entries: {result['entry_count']}  |  SHI threshold: {result['shi_threshold']}")
        if result["errors"]:
            for e in result["errors"]: print(f"  {RED('!')} {e}")
        if result["warnings"]:
            for w in result["warnings"]: print(f"  {GOLD('~')} {w}")
        print()

    # ── import ────────────────────────────────────────────────────────────
    elif sub == "import":
        bundle_path = getattr(args, "bundle", None)
        min_shi     = getattr(args, "min_shi", 0.0) or 0.0
        dry_run     = getattr(args, "dry_run", False)
        if not bundle_path:
            print(RED("  bundle path required")); return
        reader = BundleReader()
        result = reader.import_into(bundle_path, library,
                                    min_shi=min_shi, dry_run=dry_run)
        if json_out:
            print(json.dumps(result, indent=2))
            return
        if not result["success"]:
            print(RED(f"  Import failed: {result['errors']}"))
            return
        print(GREEN(f"\n  Imported: {result['imported']}  |  Skipped: {result['skipped']}"))
        for d in result["details"]["imported"]:
            print(f"  + {d['id']}  {d['name']}")
        if dry_run:
            print(DIM("  (dry run)"))
        print()

    # ── log ───────────────────────────────────────────────────────────────
    elif sub == "log":
        limit = getattr(args, "limit", 20) or 20
        events = engine.read_log(limit=limit)
        print(BOLD(CYAN(f"\n  Sync log ({len(events)} entries)")))
        print(DIM("  " + "-" * 52))
        print(format_sync_log_cli(events))

    # ── status ────────────────────────────────────────────────────────────
    elif sub == "serve":
        from structurepulse.network.http_server import BundleServer
        server = BundleServer(
            workspace_root=args.path,
            port=args.port,
            host=args.host,
            min_shi=args.min_shi,
        )
        url = server.url()
        print(BOLD(CYAN(f"\n  StructurePulse — bundle server")))
        print(f"  {GREEN('●')} listening on {BOLD(url)}")
        print(f"  {DIM('endpoints:')}")
        print(f"  {DIM(url + '/api/status')}")
        print(f"  {DIM(url + '/api/manifest?min_shi=' + str(args.min_shi))}")
        print(f"  {DIM(url + '/api/bundle?min_shi=' + str(args.min_shi))}")
        print(f"  {DIM('Ctrl-C to stop')}\n")
        try:
            server.start(background=False)
        except KeyboardInterrupt:
            print("\n  stopped.")
    elif sub == "status":
        stats = engine.stats()
        peers = registry.read_all()
        active = sum(1 for p in peers if p.active)
        print(BOLD(CYAN("\n  Meta-Library Network Status")))
        print(DIM("  " + "-" * 52))
        print(f"  peers:          {len(peers)} ({active} active)")
        print(f"  total syncs:    {stats['total_syncs']}")
        print(f"  total imported: {stats['total_imported']}")
        print(f"  last sync:      {stats['last_sync']}")
        print()


# ── main ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog="structurepulse",
        description="StructurePulse — structural health for software."
    )
    sub = parser.add_subparsers(dest="command")

    p_scan = sub.add_parser("scan", help="Full structural analysis")
    p_scan.add_argument("path", nargs="?", default=".", help="Repository path")
    p_scan.add_argument("--json", action="store_true", help="JSON output")

    p_diff = sub.add_parser("diff", help="Structural diff between commits")
    p_diff.add_argument("range", nargs="?", default="HEAD~1..HEAD")
    p_diff.add_argument("--path", default=".")
    p_diff.add_argument("--json", action="store_true")

    p_log = sub.add_parser("log", help="Show decision store")
    p_log.add_argument("--path", default=".")
    p_log.add_argument("--last", type=int, default=None)
    p_log.add_argument("--module", default=None)

    p_dec = sub.add_parser("decide", help="Log an architectural decision")
    p_dec.add_argument("--path", default=".")

    p_ih = sub.add_parser("install-hook", help="Install git post-commit hook")
    p_ih.add_argument("--path", default=".")
    p_ih.add_argument("--pre-push", action="store_true", help="Also install pre-push blocker")

    p_rh = sub.add_parser("remove-hook", help="Remove StructurePulse git hooks")
    p_rh.add_argument("--path", default=".")

    p_hs = sub.add_parser("hook-status", help="Show hook installation status")
    p_hs.add_argument("--path", default=".")

    # ── Sprint 2 ──────────────────────────────────────────────────────────
    # lib
    p_lib = sub.add_parser("lib", help="Manage agent library")
    p_lib.add_argument("--path", default=".")
    lib_sub = p_lib.add_subparsers(dest="lib_command")
    lib_sub.add_parser("list")
    p_la = lib_sub.add_parser("add")
    p_la.add_argument("--source", required=True)
    p_la.add_argument("--name", default=None)
    p_la.add_argument("--desc", default="")
    p_la.add_argument("--tags", default="")
    p_ls = lib_sub.add_parser("search")
    p_ls.add_argument("query", nargs="?", default="")
    p_ls.add_argument("--language", default=None)
    p_lsh = lib_sub.add_parser("show")
    p_lsh.add_argument("id")

    # sandbox
    p_sb = sub.add_parser("sandbox", help="Sandbox experiment lab")
    p_sb.add_argument("--path", default=".")
    sb_sub = p_sb.add_subparsers(dest="sandbox_command")
    sb_sub.add_parser("list")
    p_sbc = sb_sub.add_parser("create")
    p_sbc.add_argument("--name", default="experiment")
    p_sbc.add_argument("--sources", nargs="+", default=[])
    p_sbc.add_argument("--hypothesis", default="")
    p_sbs = sb_sub.add_parser("scan")
    p_sbs.add_argument("id")
    p_sbp = sb_sub.add_parser("promote")
    p_sbp.add_argument("id")
    p_sbp.add_argument("--name", default="")

    # plan
    p_plan = sub.add_parser("plan", help="Agent planning loop")
    p_plan.add_argument("problem", nargs="+")
    p_plan.add_argument("--path", default=".")
    p_plan.add_argument("--sources", nargs="+", default=[])
    p_plan.add_argument("--language", default=None)
    p_plan.add_argument("--sandbox", action="store_true")
    p_plan.add_argument("--json", action="store_true")

    # agent (JSON-only API)
    p_ag = sub.add_parser("agent", help="JSON API for agents (Claude Code, Cursor)")
    p_ag.add_argument("--path", default=".")
    ag_sub = p_ag.add_subparsers(dest="agent_command")
    p_ags = ag_sub.add_parser("scan"); p_ags.add_argument("--path", default=".")
    p_agp = ag_sub.add_parser("plan"); p_agp.add_argument("problem", nargs="+"); p_agp.add_argument("--sources", nargs="+", default=[]); p_agp.add_argument("--sandbox", action="store_true")
    p_agpr = ag_sub.add_parser("prompt"); p_agpr.add_argument("problem", nargs="+"); p_agpr.add_argument("--sources", nargs="+", default=[])
    p_agse = ag_sub.add_parser("search"); p_agse.add_argument("query", nargs="+"); p_agse.add_argument("--language", default=None)

    # ── Sprint 3 ──────────────────────────────────────────────────────────
    # pattern
    p_pat = sub.add_parser("pattern", help="Architecture pattern library")
    p_pat.add_argument("--path", default=".")
    pat_sub = p_pat.add_subparsers(dest="pattern_command")
    p_pl = pat_sub.add_parser("list")
    p_pl.add_argument("--tag", default=None)
    p_pl.add_argument("--language", default=None)
    p_pl.add_argument("--arch", default=None)
    p_pu = pat_sub.add_parser("use")
    p_pu.add_argument("id")
    p_pu.add_argument("--output", required=True)
    p_ps = pat_sub.add_parser("show")
    p_ps.add_argument("id")

    # claude
    p_cl = sub.add_parser("claude", help="Claude Code integration")
    p_cl.add_argument("--path", default=".")
    cl_sub = p_cl.add_subparsers(dest="claude_command")
    cl_sub.add_parser("tools")
    cl_sub.add_parser("prompt")
    p_cl_init = cl_sub.add_parser("init")
    p_cl_init.add_argument("--path", default=".")
    p_clr = cl_sub.add_parser("run")
    p_clr.add_argument("--tool", required=True)
    p_clr.add_argument("--args", default="{}")

    # ── Sprint 4 ──────────────────────────────────────────────────────────
    p_net = sub.add_parser("network", help="Meta-library network (cross-repo sharing)")
    p_net.add_argument("--path", default=".")
    p_net.add_argument("--json", action="store_true")
    net_sub = p_net.add_subparsers(dest="network_command")

    p_nex = net_sub.add_parser("export")
    p_nex.add_argument("--min-shi", dest="min_shi", type=float, default=0.65)
    p_nex.add_argument("--output", default=None)

    p_nap = net_sub.add_parser("add-peer")
    p_nap.add_argument("--name", required=True)
    p_nap.add_argument("--address", required=True)
    p_nap.add_argument("--trust", default="low")
    p_nap.add_argument("--min-shi", dest="min_shi", type=float, default=0.65)
    p_nap.add_argument("--tags", default="")

    p_nrp = net_sub.add_parser("remove-peer")
    p_nrp.add_argument("id")

    net_sub.add_parser("peers")

    p_nsy = net_sub.add_parser("sync")
    p_nsy.add_argument("--peer", default=None)
    p_nsy.add_argument("--dry-run", dest="dry_run", action="store_true")

    p_nva = net_sub.add_parser("validate")
    p_nva.add_argument("bundle")

    p_nim = net_sub.add_parser("import")
    p_nim.add_argument("bundle")
    p_nim.add_argument("--min-shi", dest="min_shi", type=float, default=0.0)
    p_nim.add_argument("--dry-run", dest="dry_run", action="store_true")

    p_nlg = net_sub.add_parser("log")
    p_nlg.add_argument("--limit", type=int, default=20)

    net_sub.add_parser("status")
    p_nsv = net_sub.add_parser("serve")
    p_nsv.add_argument("--port",    type=int,   default=8765,        help="Port (default: 8765)")
    p_nsv.add_argument("--host",    type=str,   default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    p_nsv.add_argument("--min-shi", type=float, default=0.65,        dest="min_shi", help="Minimum SHI to export (default: 0.65)")

    args = parser.parse_args()

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "diff":
        cmd_diff(args)
    elif args.command == "log":
        cmd_log(args)
    elif args.command == "decide":
        cmd_decide(args)
    elif args.command == "install-hook":
        cmd_install_hook(args)
    elif args.command == "remove-hook":
        cmd_remove_hook(args)
    elif args.command == "hook-status":
        cmd_hook_status(args)
    elif args.command == "lib":
        cmd_lib(args)
    elif args.command == "sandbox":
        cmd_sandbox(args)
    elif args.command == "plan":
        cmd_plan(args)
    elif args.command == "agent":
        cmd_agent(args)
    elif args.command == "pattern":
        cmd_pattern(args)
    elif args.command == "claude":
        cmd_claude(args)
    elif args.command == "network":
        cmd_network(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
