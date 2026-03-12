# StructurePulse — Agent Reference

This document is written for AI agents (Claude Code, GPT-4, Copilot Workspace,
or any LLM-based coding assistant) that need to use StructurePulse as part of
a software development workflow.

Read this entire document before calling any StructurePulse commands.
It explains not just *how* to use the tool but *what mistakes agents typically make*.

---

## What StructurePulse does (in one sentence)

It scans a codebase and returns a structural health score — telling you whether
the architecture is maintainable, and specifically *why* if it is not.

---

## How to call it

### Option A: CLI subprocess (recommended for most agents)

```bash
sp scan /path/to/project --json --exclude "tests/"
```

Returns JSON to stdout. Parse it. Example:

```python
import subprocess, json

result = subprocess.run(
    ["sp", "scan", "/path/to/project", "--json", "--exclude", "tests/"],
    capture_output=True, text=True
)
data = json.loads(result.stdout)

print(data["shi"])          # float 0.0–1.0
print(data["verdict"])      # "healthy" | "warning" | "critical"
print(data["cycle_count"])  # int
```

### Option B: Python API (for agents running inside Python)

```python
from structurepulse.agent.api import AgentAPI

result = AgentAPI("/path/to/project").scan()
# result is a plain dict — same structure as --json output
```

---

## JSON output structure

```json
{
  "path": "/absolute/path/to/project",
  "shi": 0.712,
  "verdict": "warning",
  "fd": 1.81,
  "fd_status": "optimal",
  "coupling_density": 0.31,
  "cycle_count": 3,
  "entropy": 2.84,
  "avg_complexity": 2.1,
  "total_modules": 34,
  "total_nodes": 218,
  "total_loc": 4210,
  "boilerplate_excluded": 8,
  "inconsistencies": [
    {
      "code": "H1",
      "kind": "Hidden Hub",
      "module": "utils.py",
      "message": "'utils.py' is named as a utility but behaves like a central hub.",
      "detail": "imported by 22/33 modules (67%)",
      "severity": "warning"
    }
  ],
  "dependency_cycles": [
    ["/abs/path/app.py", "/abs/path/config.py"]
  ],
  "import_lines": {
    "(\"/abs/path/app.py\", \"/abs/path/config.py\")": 12
  },
  "modules": [
    {
      "path": "/abs/path/app.py",
      "name": "app.py",
      "loc": 312,
      "coupling": 0.45,
      "avg_complexity": 4.4,
      "is_boilerplate": false
    }
  ],
  "action_required": true
}
```

---

## Critical things agents get wrong

### ❌ Mistake 1: Scanning the wrong directory

```bash
# WRONG — scans from current working directory, not the project
sp scan .

# CORRECT — always use absolute path or resolve explicitly
sp scan /absolute/path/to/project --json
```

Always resolve the path before calling. Do not assume `.` is the project root.

### ❌ Mistake 2: Including tests in the scan

Test files are structurally cleaner and more isolated than application code.
Including them inflates the SHI artificially and suppresses real smells.

```bash
# WRONG — tests pollute the architectural signal
sp scan /project --json

# CORRECT — exclude tests for architectural analysis
sp scan /project --json --exclude "tests/" "test/" "spec/"
```

**Exception:** If you are specifically analyzing test architecture or
test-to-code coupling, include tests intentionally.

### ❌ Mistake 3: Treating FD = 1.81 as "needs improvement"

FD (Fractal Dimension) is NOT a score where higher is better.
The optimal range is **1.7 – 1.9**. Values outside this range are problems:

| FD value | fd_status | Meaning | Action |
|----------|-----------|---------|--------|
| < 1.7 | "rigid" | Too homogeneous. All modules look alike. | Increase specialization. |
| 1.7 – 1.9 | "optimal" | ✓ Correct. Do not change. | Nothing. |
| > 1.9 | "chaos" | Complexity spikes. One module dominates. | Split the hotspot. |

**Do not suggest refactoring when fd_status = "optimal".**

### ❌ Mistake 4: Treating SHI 0.70 as "fine"

The target is **≥ 0.80**. The thresholds:

| SHI | verdict | Meaning |
|-----|---------|---------|
| ≥ 0.80 | "healthy" | Architecture is maintainable |
| 0.65 – 0.79 | "warning" | Technical debt accumulating. Fix before adding features. |
| < 0.65 | "critical" | Refactoring required. Adding features now makes things worse. |

### ❌ Mistake 5: Ignoring cycle_count > 0

Every cycle is a real bug waiting to happen. Circular imports in Python cause
`ImportError` at runtime in certain load orders. They must be fixed.

The `dependency_cycles` array gives you the exact files involved.
The `import_lines` dict gives you the line number of each import in the cycle.

Fix strategy: introduce a shared interface module that both sides import from,
breaking the circular chain.

### ❌ Mistake 6: Treating all inconsistency warnings as false positives

The four codes and what they mean:

| Code | Name | When it's real | When it might be a false positive |
|------|------|----------------|----------------------------------|
| H1 | Hidden Hub | `utils.py` imported by >40% of modules | Intentional shared core in small projects |
| H2 | Layer Inversion | `user_model.py` imports `user_service.py` | Almost never — this is always an architecture smell |
| H3 | Responsibility Leak | `config.py` imports business logic | `conftest.py` (pytest) — exclude `tests/` to suppress |
| H4 | Dead Weight | `payment_service.py` has no imports | Service with only pure functions — rename to `_utils.py` |

**If H3 fires on `conftest.py` or `test_*.py`, you forgot `--exclude "tests/"`.**

### ❌ Mistake 7: Running sp scan in a loop on every file change

Use `sp watch` instead. It handles debouncing, terminal output, and delta display.

```bash
# WRONG — polling manually
while True:
    sp scan /project --json
    sleep 2

# CORRECT — built-in watch mode
sp watch /project --min-shi 0.7 --interval 2
```

### ❌ Mistake 8: Confusing `boilerplate_excluded` with excluded files

`boilerplate_excluded` counts files that *were parsed* but *excluded from FD
calculation* because they are empty init files or thin config files with zero
functions. These files are still included in coupling and cycle analysis.

This is different from `--exclude` which removes files entirely from the scan.

---

## Interpreting results: decision flowchart

```
scan result received
        │
        ├─ cycle_count > 0?
        │       YES → fix cycles first. everything else is secondary.
        │       NO  → continue
        │
        ├─ verdict == "critical" (shi < 0.65)?
        │       YES → do not add features. refactor first.
        │       NO  → continue
        │
        ├─ verdict == "warning" (0.65 ≤ shi < 0.80)?
        │       YES → flag to human. can proceed with caution.
        │       NO  → continue
        │
        ├─ inconsistencies present?
        │       YES → review each. H2 is always real. H3/H4 may be naming issues.
        │       NO  → continue
        │
        └─ fd_status == "chaos"?
                YES → find the hotspot module (highest avg_complexity in modules[])
                      and suggest splitting it.
                NO  → architecture is healthy. proceed.
```

---

## Using the Agent Workbench

### Get an architecture pattern

```python
from structurepulse.agent.api import AgentAPI
api = AgentAPI("/project")

# Generate a scaffolded REST API structure
api.use_pattern("rest_api", output_dir="/project/src/api")

# Available patterns: rest_api, event_driven, layered, microservice
```

### Search the curated library

The library contains 69+ elite modules (SHI ≥ 0.80) harvested from real
open-source projects. Use it to find reference implementations.

```python
results = api.library_search("auth")
# Returns list of dicts with: name, shi, tags, path, description
```

### Generate an implementation plan

```python
plan = api.plan("Implement OAuth2 flow")
# Returns: verdict, approach, recommended_patterns, estimated_shi, warnings
```

### Sandbox experiment

Use sandboxes to test architectural changes without touching the main codebase:

```python
sandbox = api.sandbox_create(name="oauth-experiment", sources=["src/auth.py"])
# Returns sandbox_id

scan_result = api.sandbox_scan(sandbox["sandbox_id"])
# Same structure as regular scan result
```

---

## CI/CD integration

### Exit codes

| Exit code | Meaning |
|-----------|---------|
| 0 | All conditions passed (or no --fail-on flags) |
| 1 | One or more --fail-on conditions violated |
| 2 | Scan error (no files found, parse failure) |

### --fail-on conditions

```bash
--fail-on cycles              # any cycle_count > 0
--fail-on "shi<0.7"           # shi below threshold
--fail-on "shi<0.8"           # stricter threshold
--fail-on inconsistencies     # any inconsistency warnings present
--fail-on "coupling>0.5"      # coupling density above threshold
```

Multiple conditions are OR'd: exit 1 if any condition is met.

### Reading exit code in an agent

```python
result = subprocess.run(
    ["sp", "scan", "/project", "--json",
     "--fail-on", "cycles", "--fail-on", "shi<0.7"],
    capture_output=True, text=True
)

if result.returncode == 1:
    data = json.loads(result.stdout)
    # Tell the human what failed
    if data["cycle_count"] > 0:
        report_cycles(data["dependency_cycles"], data["import_lines"])
    if data["shi"] < 0.7:
        report_shi(data["shi"], data["inconsistencies"])
```

---

## Language Server (for IDE agents)

```bash
sp lsp --workspace /project --min-shi 0.65 --log-file /tmp/sp-lsp.log
```

The LSP server communicates over stdin/stdout using JSON-RPC 2.0
(Content-Length framing). It responds to standard LSP events:

- `textDocument/didSave` → triggers full scan → publishes diagnostics
- `textDocument/didOpen` → same
- `textDocument/didClose` → clears diagnostics for that file

Diagnostic codes:
- `SP-CYCLE` (Error) — file participates in a dependency cycle
- `SP-SHI` (Warning) — workspace SHI below threshold
- `SP-COUPLING` (Info) — module has high coupling

---

## P2P Network (for multi-agent setups)

```bash
# Agent A (server): share its curated library
sp network serve --port 8000

# Agent B (client): pull high-quality patterns from Agent A
sp network add-peer --name "agent-a" --address "http://agent-a:8000" --min-shi 0.7
sp network sync
```

Sync only pulls modules that pass `--min-shi`. The Merkle-chain integrity
check happens automatically — tampered bundles are rejected.

---

## Quick reference card

```
sp scan /project --json --exclude "tests/"   → full structural scan
sp scan /project --fail-on cycles --fail-on "shi<0.7"   → CI gate
sp watch /project --min-shi 0.7              → live monitoring
sp diff HEAD~1..HEAD                         → commit impact
sp lsp --workspace /project                  → IDE integration
sp plan "build feature X"                    → architectural planning
sp lib search "auth"                         → find reference patterns
sp sandbox create --name "exp"               → isolated experiment
sp network sync                              → pull peer patterns
```

---

FractalSense Robotics — 2026
