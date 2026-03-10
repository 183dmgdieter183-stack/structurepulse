# StructurePulse

**Structural health monitor for AI-generated software.**

> Code kann lügen. Struktur nicht.

StructurePulse scans a codebase and tells you if its architecture is healthy —
before it becomes unmaintainable. It works on Python and TypeScript, requires
zero dependencies, and runs in under a second on most projects.

---

## Install

```bash
pip install structurepulse
```

Or from source:

```bash
git clone https://github.com/fractalsense/structurepulse
cd structurepulse
pip install -e .
```

**Requirements:** Python 3.11+. No other dependencies.

---

## First scan (30 seconds)

```bash
cd your-project
sp scan . --explain
```

Example output:

```
  StructurePulse — scanning /your-project

  FINGERPRINT
  languages:    python
  modules:      34
  total nodes:  218

  STRUCTURAL HEALTH
  fd:      1.81  [optimal]
  shi:     0.712  WARNING
  coupling: 0.31
  cycles:  3

  ⚠ DEPENDENCY CYCLES
  → app.py:12 → config.py:4 → app.py → ...

  ROOT CAUSE ANALYSIS
  ⚠  3 dependency cycle(s). First: app.py:12 → config.py:4 → app.py
     To fix: introduce a shared interface module both sides depend on.
  ⚠  SHI 0.712 (warning, target ≥ 0.80). Gap: -0.088
     Biggest drag: Coupling (weight 25%, score 0.52).
```

---

## Core commands

### Scan
```bash
sp scan .                          # basic scan
sp scan . --explain                # + root cause analysis
sp scan . --json                   # machine-readable output
sp scan . --exclude "tests/" "venv/"   # skip directories
```

### Watch (live reload)
```bash
sp watch .                         # re-scans on every file change
sp watch . --min-shi 0.7           # alert when SHI drops below threshold
sp watch . --explain               # show root cause on each update
```

### CI/CD enforcement
```bash
sp scan . --fail-on cycles                    # exit 1 if any cycles
sp scan . --fail-on "shi<0.7"                 # exit 1 if SHI below 0.7
sp scan . --fail-on inconsistencies           # exit 1 if role smells found
sp scan . --fail-on cycles --fail-on "shi<0.7"  # multiple conditions
```

### Diff (git-aware)
```bash
sp diff HEAD~1..HEAD               # structural changes between commits
sp diff HEAD~1..HEAD --visual      # ANSI graph in terminal
sp diff HEAD~1..HEAD --html out.html   # Mermaid HTML report
```

### Language Server (IDE integration)
```bash
sp lsp                             # start LSP server on stdio
sp lsp --workspace . --min-shi 0.65 --log-file /tmp/sp.log
```

### Agent Workbench
```bash
sp pattern use rest_api --output ./src   # scaffold from architecture pattern
sp lib search "auth"                      # search curated architecture library
sp plan "Implement OAuth2 flow"           # generate implementation plan
sp sandbox create --name "experiment"     # isolated experiment environment
```

### P2P Network
```bash
sp network serve --port 8000       # share your library with peers
sp network add-peer --name "alice" --address "http://alice:8000"
sp network sync                    # pull high-quality patterns from peers
```

---

## What StructurePulse measures

| Metric | Target | What it means |
|--------|--------|---------------|
| **FD** (Fractal Dimension) | 1.7 – 1.9 | Complexity signal. Below 1.7 = too rigid. Above 1.9 = chaotic. |
| **SHI** (Structural Health Index) | ≥ 0.80 | Composite score. Weighted sum of FD, entropy, coupling, cycles, test topology. |
| **Coupling** | < 0.40 | Import-graph density. High coupling = one change breaks many files. |
| **Cycles** | 0 | Circular imports. Each cycle is a potential import error and a refactoring trap. |
| **Smells** | 0 | Role-inconsistency heuristics: Hidden Hubs, Layer Inversions, Responsibility Leaks, Dead Weight. |

**SHI thresholds:**

| Score | Status | Meaning |
|-------|--------|---------|
| ≥ 0.80 | ✓ Healthy | Architecture is maintainable |
| 0.65 – 0.79 | ⚠ Warning | Technical debt accumulating |
| < 0.65 | ✗ Critical | Refactoring required before scaling |

---

## Ignoring files (.spignore)

Create `.spignore` in your project root (gitignore-style):

```
# Ignore test directories
tests/
test/

# Ignore generated files
migrations/
*_generated.py

# Un-ignore a specific subdirectory
!src/tests/integration/
```

**Built-in defaults** (always excluded unless overridden):
`venv/`, `.venv/`, `__pycache__/`, `node_modules/`, `.git/`, `migrations/`,
`tests/`, `test/`, `dist/`, `build/`

Or use the CLI flag:
```bash
sp scan . --exclude "tests/" "docs/" "*.generated.py"
```

---

## CI/CD (GitHub Actions)

```yaml
# .github/workflows/structurepulse.yml
name: Architecture Gate
on: [pull_request]
jobs:
  architecture:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install structurepulse
      - run: sp scan . --fail-on cycles --fail-on "shi<0.7" --fail-on inconsistencies
```

---

## Git hooks

```bash
sp install-hook --path .           # installs pre-commit hook
```

The hook runs `sp scan . --fail-on cycles --fail-on "shi<0.7"` before every
commit. If the architecture degrades, the commit is blocked.

---

## Python API (for agents and scripts)

```python
from structurepulse.agent.api import AgentAPI

result = AgentAPI("/path/to/project").scan()

print(result["shi"])           # float: 0.0 – 1.0
print(result["cycle_count"])   # int
print(result["inconsistencies"])  # list of role smell dicts
print(result["verdict"])       # "healthy" | "warning" | "critical"
```

---

FractalSense Robotics — 2026
