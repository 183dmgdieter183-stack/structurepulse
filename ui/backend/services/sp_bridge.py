"""
StructurePulse Bridge — Service Layer
Single point of contact with the StructurePulse Python API.
No other module may import from `structurepulse.*` directly.
"""
import sys
from pathlib import Path

# ensure the sp package is resolvable
_SP_ROOT = str(Path(__file__).parent.parent.parent.parent / "code")
if _SP_ROOT not in sys.path:
    sys.path.insert(0, _SP_ROOT)

from structurepulse.agent.api import AgentAPI
from structurepulse.library.pattern_library import PatternLibrary


_SP_WORKSPACE = str(Path(__file__).parent.parent.parent.parent / "code")


def _api() -> AgentAPI:
    return AgentAPI(_SP_WORKSPACE)


def _patterns() -> PatternLibrary:
    return PatternLibrary(_SP_WORKSPACE)


# ── Library ──────────────────────────────────────────────────────────────

def library_list(limit: int = 80) -> dict:
    api = _api()
    return api.library_search("", limit=limit)


def library_search(query: str, language: str | None = None, limit: int = 20) -> dict:
    api = _api()
    return api.library_search(query, language=language, limit=limit)


def library_get(entry_id: str) -> dict | None:
    from structurepulse.library.agent_library import AgentLibrary
    from dataclasses import asdict
    lib = AgentLibrary(_SP_WORKSPACE)
    entry = lib.get(entry_id)
    if entry is None:
        return None
    return asdict(entry)


# ── Scanner ───────────────────────────────────────────────────────────────

def scan_path(path: str) -> dict:
    api = _api()
    return api.scan(path)


def browse_directory() -> str | None:
    """ Opens a native OS folder selection dialog (server-side). """
    try:
        if sys.platform == "darwin":
            import subprocess
            cmd = 'osascript -e "POSIX path of (choose folder with prompt \\"Select a folder to scan:\\")"'
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, _ = process.communicate()
            if process.returncode == 0:
                return stdout.decode('utf-8').strip()
            return None
        else:
            # Fallback for other OS or if osascript fails
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            folder_selected = filedialog.askdirectory()
            root.destroy()
            return folder_selected if folder_selected else None
    except Exception:
        return None


# ── Planner ───────────────────────────────────────────────────────────────

def plan_problem(problem: str, language: str | None = None) -> dict:
    api = _api()
    return api.plan(problem, language=language)


# ── Patterns ──────────────────────────────────────────────────────────────

def patterns_list() -> list[dict]:
    lib = _patterns()
    from dataclasses import asdict
    return [asdict(p) for p in lib.list()]


def pattern_get(pattern_id: str) -> dict | None:
    lib = _patterns()
    from dataclasses import asdict
    p = lib.get(pattern_id)
    return asdict(p) if p else None


def pattern_instantiate(pattern_id: str, output_dir: str) -> list[str]:
    lib = _patterns()
    return lib.instantiate(pattern_id, output_dir)
