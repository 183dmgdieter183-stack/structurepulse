"""
StructurePulse — .spignore

Reads a `.spignore` file (gitignore-style) and provides a fast matcher
used by all parser backends to exclude files and directories from analysis.

Supported patterns:
  tests/          directory name (trailing slash = dir only)
  test_*.py       glob against filename
  **/fixtures/**  double-star path glob
  migrations      exact directory name anywhere in path
  !src/           negation (un-ignore)
  # comment       ignored

Usage:
  ignore = SpIgnore.load(workspace_root)
  if ignore.matches(path):
      continue   # skip this file

CLI flag `--exclude` adds patterns on top of the .spignore file.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path


# ── Built-in default excludes (always active, .spignore can override) ─────────

_BUILTIN_EXCLUDES = [
    # Virtual envs
    "venv/", ".venv/", "env/", ".env/",
    # Cache
    "__pycache__/", ".mypy_cache/", ".ruff_cache/", ".pytest_cache/",
    # VCS
    ".git/", ".hg/", ".svn/",
    # Build artefacts
    "dist/", "build/", "*.egg-info/", ".eggs/", "node_modules/",
    # DB migrations (usually generated)
    "migrations/", "alembic/versions/",
    # Test discovery — excluded by default, users can un-ignore with !tests/
    "tests/", "test/", "spec/",
    # Generated / vendored
    "vendor/", "third_party/", "_vendor/",
]


class SpIgnore:
    """
    Gitignore-style ignore rules.
    Patterns are matched against:
      - the path relative to the workspace root (forward slashes)
      - the filename alone
    """

    def __init__(self, patterns: list[str], workspace_root: str):
        self._root = Path(workspace_root).resolve()
        self._includes: list[str] = []   # negated (!...) patterns
        self._excludes: list[str] = []

        for raw in patterns:
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            if raw.startswith("!"):
                self._includes.append(raw[1:].strip())
            else:
                self._excludes.append(raw)

    # ── Public interface ──────────────────────────────────────────────────────

    def matches(self, abs_path: str | Path) -> bool:
        """
        Return True if abs_path should be excluded from analysis.
        Order: negation (!patterns) takes precedence over exclude patterns.
        """
        p = Path(abs_path).resolve()
        try:
            rel = str(p.relative_to(self._root)).replace(os.sep, "/")
        except ValueError:
            rel = p.name

        # Check negations first — if any negation matches, never exclude
        for pat in self._includes:
            if self._glob_matches(rel, p.name, pat):
                return False

        # Check excludes
        for pat in self._excludes:
            if self._glob_matches(rel, p.name, pat):
                return True

        return False

    # ── Pattern matching ──────────────────────────────────────────────────────

    @staticmethod
    def _glob_matches(rel: str, name: str, pattern: str) -> bool:
        """
        Match pattern against:
          - rel:  relative path from workspace root, e.g. "src/tests/test_foo.py"
          - name: just the filename, e.g. "test_foo.py"

        Pattern rules:
          "tests/"       → matches any path component named "tests" (directory)
          "test_*.py"    → matches filename
          "**/tests/**"  → double-star path glob
          "tests"        → matches any path component named "tests"
        """
        # Directory-style: trailing slash means match a directory
        if pattern.endswith("/"):
            dir_name = pattern.rstrip("/")
            parts = rel.split("/")
            if "/" in dir_name:
                # Multi-component pattern like "src/tests/" — match prefix or substring
                return rel.startswith(dir_name + "/") or ("/" + dir_name + "/") in rel
            else:
                # Single component: match any segment of the path (except filename)
                return any(p == dir_name for p in parts[:-1]) or (
                    len(parts) >= 1 and parts[0] == dir_name
                )

        # Double-star: use fnmatch on full relative path
        if "**" in pattern:
            # Convert ** to a form fnmatch can handle
            # e.g. "**/tests/**" → match any path containing /tests/
            regex_like = pattern.replace("**/", "*/").replace("/**", "/*")
            return fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel, regex_like)

        # Plain name with glob chars: match against filename only
        if any(c in pattern for c in ("*", "?", "[")):
            return fnmatch.fnmatch(name, pattern)

        # Exact component match: "migrations" matches any segment of the path
        parts = rel.split("/")
        return pattern in parts

    # ── Factories ─────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, workspace_root: str,
             extra_patterns: list[str] | None = None) -> "SpIgnore":
        """
        Load .spignore from workspace_root (if present), merge with
        built-in defaults and any extra_patterns from CLI --exclude.
        """
        root = Path(workspace_root).resolve()
        patterns: list[str] = list(_BUILTIN_EXCLUDES)

        ignore_file = root / ".spignore"
        if ignore_file.exists():
            try:
                file_patterns = ignore_file.read_text(encoding="utf-8").splitlines()
                patterns.extend(file_patterns)
            except OSError:
                pass

        if extra_patterns:
            patterns.extend(extra_patterns)

        return cls(patterns, str(root))

    @classmethod
    def empty(cls, workspace_root: str) -> "SpIgnore":
        """Only builtin excludes, no .spignore file, no extra patterns."""
        return cls(list(_BUILTIN_EXCLUDES), workspace_root)

    # ── Utility ───────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        return {
            "exclude_patterns": len(self._excludes),
            "include_patterns": len(self._includes),
            "workspace": str(self._root),
        }
