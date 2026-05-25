---
phase: 15-packaging-release-v0-2
reviewed: 2026-05-24T00:00:00Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - INSTALL.md
  - packages/bagq/pyproject.toml
  - packages/bagq/src/bagq/__init__.py
  - packages/rosbagger-core/pyproject.toml
  - packages/rosbagger-core/src/rosbagger_core/__init__.py
  - packages/rosbagger-gui/pyproject.toml
  - packages/rosbagger-gui/src/rosbagger_gui/__init__.py
  - packages/rosbagger-record/pyproject.toml
  - packages/rosbagger-record/src/rosbagger_record/__init__.py
  - packages/rosbagger-replay/pyproject.toml
  - packages/rosbagger-replay/src/rosbagger_replay/__init__.py
  - pyproject.toml
  - scripts/proof_external_install.sh
findings:
  critical: 0
  warning: 4
  info: 2
  total: 6
status: issues_found
---

# Phase 15: Code Review Report

**Reviewed:** 2026-05-24
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

This is a packaging/release phase (v0.2.0): version bumps across all five
packages, inter-package dependency pins (`rosbagger-core>=0.2,<0.3`), a new
`rosbagger-gui[live]` optional-dependencies extra, root workspace `[tool.uv.sources]`,
a bash external-install proof script, and `INSTALL.md`.

The core mechanics are correct and the design is well-reasoned. Version numbers
are consistent (`0.2.0` in every `pyproject.toml` and matching `__version__`).
The offline-import invariant holds: re-exported submodules (`source`, `scheduler`,
`discovery`) import no ROS at top level, and the GUI's `_detect_ros` lazy-imports
`rclpy` inside its body. The proof script's `bagq --version` assertion (`bagq 0.2.0`)
matches the CLI's actual output (`f"bagq {__version__}"`). The shell script uses
`set -euo pipefail`, a `trap ... EXIT` cleanup, and location-independent path
resolution — all good practice.

No blockers. Findings are dependency-spec robustness gaps and doc/script
consistency issues.

## Warnings

### WR-01: Unbounded upper version pins on third-party deps in a release manifest

**File:** `packages/rosbagger-core/pyproject.toml:10`, `packages/bagq/pyproject.toml:9`
**Issue:** A release phase should pin reproducibly. Most pins are capped
(`duckdb>=1.4,<2`, `sqlglot>=27,<31`, `rosbags>=0.11,<0.12`, `textual>=8,<9`,
`typer>=0.15,<1`), but `pyarrow>=18` (core) and `rich>=13` (bagq) carry **no
upper bound**. The dev group in the root `pyproject.toml:31` similarly leaves
`pytest-cov>=6` and `matplotlib>=3.8` uncapped. A future major `pyarrow` (e.g.
20.x) or `rich` (14.x) can be pulled into a `v0.2.0` install and break it,
defeating the point of a tagged release. This is inconsistent with the
otherwise-disciplined `>=X,<Y` convention used everywhere else.
**Fix:** Cap to the next major, matching the sibling convention:
```toml
# rosbagger-core
dependencies = ["rosbags>=0.11,<0.12", "duckdb>=1.4,<2", "sqlglot>=27,<31", "pyarrow>=18,<22"]
# bagq
dependencies = ["rosbagger-core>=0.2,<0.3", "typer>=0.15,<1", "rich>=13,<15"]
```

### WR-02: Proof venv never upgrades pip — stale system pip can misbehave on path+extra/metadata

**File:** `scripts/proof_external_install.sh:40-53`
**Issue:** `python3 -m venv "${VENV}"` seeds whatever `pip` ships with the host
interpreter's `ensurepip` bundle, which on long-lived dev boxes / older distros
can be years old. The proof then installs `"${REPO_ROOT}/packages/rosbagger-gui[live]"`
(a local path **with an extra**) and relies on in-transaction resolution of bare
sibling specs. Old pip versions have known gaps handling path-with-extra syntax
and modern `pyproject.toml`/metadata. A failure here would look like a packaging
defect rather than a stale-tooling artifact, undermining the proof's value as a
gate. There is also no guard that `pip` exists (a `--without-pip` venv would fail
with a confusing error).
**Fix:** Upgrade pip in the throwaway venv before installing:
```bash
PYTHONPATH="" "${PY}" -m pip install --upgrade pip >/dev/null
```
and invoke pip as `"${PY}" -m pip ...` rather than the `"${PIP}"` shim so it works
even if the `bin/pip` script is missing.

### WR-03: Proof script step counter and INSTALL.md assertion list disagree

**File:** `scripts/proof_external_install.sh:58-90`, `INSTALL.md:185-200`
**Issue:** The script labels steps `[1/6]`…`[6/6]`, but step `[6/6]` (line 90) is
not an assertion — it is just `echo "all smoke checks passed"`. So the denominator
"6" counts a non-check, and only 5 real assertions run. Meanwhile `INSTALL.md`
section 6 (lines 188–200) documents **8** numbered checks (venv creation, one
transaction, neutral cwd, `--help`, `--version`, multi-import, offline invariant,
`tools` not importable). A reader comparing the doc to the script output sees
8 documented vs `/6` labeled — a credibility gap for the project's headline
verification gate.
**Fix:** Reconcile the counts. Either relabel the real assertions `[1/5]`…`[5/5]`
and make the final line a plain summary, or expand the script labels and the doc
list to the same enumeration. The doc and script should describe the identical
set of steps.

### WR-04: `bagq` does not co-name `rich`/`typer` extras risk — but `bagq[plot]` install path is undocumented and unproven

**File:** `INSTALL.md:82-88`, `packages/bagq/pyproject.toml:14-15`
**Issue:** `bagq` declares a `plot` extra (`matplotlib>=3.8`) and `INSTALL.md`
section 5 (root `pyproject.toml:22-24`) states CI exercises `bagq query --plot`.
But no INSTALL recipe shows how an external consumer installs `bagq[plot]`, and
the proof script never installs or exercises the `plot` extra. A consumer who
runs `bagq query --plot` after the documented `pip install ... bagq` (no extra)
will hit an `ImportError` on matplotlib with no install guidance. The release
docs cover the `gui[live]` extra thoroughly but silently omit the `bagq[plot]`
extra, which is an asymmetric gap for a v0.2.0 install guide.
**Fix:** Add a `bagq[plot]` install snippet to section 2 (co-naming
`rosbagger-core`), e.g.:
```bash
pip install \
  "rosbagger-core @ git+...#subdirectory=packages/rosbagger-core" \
  "bagq[plot]      @ git+...#subdirectory=packages/bagq"
```
and quote the path form (`"./packages/bagq[plot]"`) in section 3 as is done for
the GUI.

## Info

### IN-01: `import tools` assertion can give a false pass if any dep ships a top-level `tools`

**File:** `scripts/proof_external_install.sh:80-88`
**Issue:** Step `[5/6]` asserts `import tools` raises `ModuleNotFoundError` to prove
the dev-only `tools/` package never leaked into a wheel. The assertion is correct
today, but it is name-fragile: if any current or future transitive dependency
ships a top-level package literally named `tools`, the import would succeed and
the proof would FATAL even though rosbagger's own `tools/` did not leak. The check
proves "no module named tools is importable," not "rosbagger's tools/ is absent."
**Fix:** Optional hardening — assert on a marker unique to the dev package (e.g.
`tools.fixtures` or a known symbol) rather than the bare name, or document the
fragility inline.

### IN-02: GUI manifest relies on root `[tool.uv.sources]` for `record`/`replay` only at dev time — comment could mislead

**File:** `packages/rosbagger-gui/pyproject.toml:16-22`
**Issue:** The header comment says the live siblings are "resolved via the root
`[tool.uv.sources]` workspace source." That is true only for the development
workspace; the built wheel carries the bare `live` specs with no source, which is
exactly the resolution gap `INSTALL.md` warns about. The comment is accurate but
incomplete and could lead a maintainer to believe the wheel is self-resolving.
**Fix:** Add a half-sentence noting that, like the `rosbagger-core` spec, the
`live` specs are bare in the wheel and require co-naming at install (cross-ref
`INSTALL.md` section 5).

---

_Reviewed: 2026-05-24_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
