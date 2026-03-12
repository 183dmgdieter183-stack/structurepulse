# StructurePulse — Quickstart (5 minutes)

This guide takes you from zero to your first real architectural insight.

---

## Step 1: Install

```bash
pip install structurepulse
```

Verify:
```bash
sp --version
```

**No virtual environment needed.** StructurePulse has zero runtime dependencies
and installs globally like `black` or `ruff`.

---

## Step 2: Scan your project

Navigate to any Python or TypeScript project and run:

```bash
cd /path/to/your-project
sp scan . --explain
```

If the output is noisy with test files or vendored code, exclude them:

```bash
sp scan . --explain --exclude "tests/" "venv/" "migrations/"
```

---

## Step 3: Read the output

```
  STRUCTURAL HEALTH
  fd:      1.81  [optimal]       ← complexity signal, target: 1.7–1.9
  shi:     0.712  WARNING        ← overall health, target: ≥ 0.80
  coupling: 0.31                 ← import density, target: < 0.40
  cycles:  3                     ← circular imports, target: 0
```

**What to focus on first:**
1. `cycles > 0` — fix these before anything else. The line numbers tell you exactly where.
2. `shi < 0.65` — CRITICAL. Read the ROOT CAUSE ANALYSIS section below the metrics.
3. `[!] ROLE INCONSISTENCY` — architectural smells. Review each one; some may be intentional.

---

## Step 4: Watch mode (optional, for active development)

```bash
sp watch . --min-shi 0.7
```

StructurePulse re-scans every 1.5 seconds. When SHI drops below your threshold,
it alerts you immediately — before you commit.

---

## Step 5: Add to CI/CD (optional)

```bash
sp scan . --fail-on cycles --fail-on "shi<0.7"
```

Exit code `1` if violations found, `0` if clean. Drop this into any pipeline.

---

## Create a .spignore file

In your project root, create `.spignore` to permanently exclude directories:

```
tests/
venv/
migrations/
docs/
```

This is read automatically on every scan. No need for `--exclude` flags.

---

## Common questions

**Q: My SHI dropped when I excluded tests/ — is that normal?**
Yes. Tests are typically cleaner and more isolated than application code.
Excluding them reveals the true health of your core architecture.

**Q: Flask/Django got SHI 0.5. Is that bad?**
Legacy frameworks often have intentional coupling by design. Use StructurePulse
to track *change* over time rather than absolute scores on inherited codebases.
Focus on: are cycles increasing? Is coupling growing?

**Q: What is FD and why 1.7–1.9?**
Higuchi Fractal Dimension measures signal complexity. Applied to code:
below 1.7 means all modules are too similar (rigid, no specialization);
above 1.9 means complexity spikes are uncontrolled (chaotic).
The 1.7–1.9 band is where maintainable, well-differentiated architectures live.

**Q: A "Dead Weight" warning on my service file — false positive?**
Check if `my_service.py` imports anything. If it has functions but zero imports,
it truly does nothing — it either needs to call a repository/client, or it should
be merged into the caller. If it's intentionally a pure utility, rename it
(e.g., `my_utils.py`) so the heuristic doesn't flag it.

---

## Next steps

- `sp diff HEAD~1..HEAD` — see how the last commit affected architecture
- `sp lsp` — real-time warnings in VS Code / Neovim (see README)
- `sp plan "Implement feature X"` — let the Agent Workbench suggest a structure
