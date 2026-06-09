# Installing rosbagger v0.2.0

rosbagger is a monorepo of seven independently-installable packages:

| Package | Subdirectory | Role |
|---------|--------------|------|
| `rosbagger-core` | `packages/rosbagger-core` | Pure-Python offline library (no ROS dependency) |
| `bagq` | `packages/bagq` | The SQL CLI; depends on `rosbagger-core` |
| `rosbagger-record` | `packages/rosbagger-record` | Live recording (needs `rclpy`, env-provided by a sourced ROS) |
| `rosbagger-replay` | `packages/rosbagger-replay` | Live replay (needs `rclpy`) |
| `rosbagger-gui` | `packages/rosbagger-gui` | Textual cockpit; offline by default, live panels via `[live]` |
| `rosbagger-desktop` | `packages/rosbagger-desktop` | Native PySide6 desktop cockpit; pulls core + record + replay + rerun |
| `rosbagger-rerun` | `packages/rosbagger-rerun` | Bag→Rerun visualization bridge; `rerun-sdk` via the `[sdk]` extra |

All seven are at version **0.2.0**. Every package that depends on a sibling pins
it by **version spec only** (e.g. `rosbagger-core>=0.2,<0.3`) — never by a
baked-in path or git URL. That keeps each wheel source-agnostic, but it has one
consequence you must know before you install.

> **TL;DR** — from a checkout, run `./install.sh` (offline CLI) or
> `./install.sh --all` (everything); add `--user` to install into `~/.local/bin`
> (commands work from any terminal, no venv to activate). It applies the
> one-transaction rule below for you. The rest of this doc is the manual matrix
> (git, downstream uv, per-package).

## Why one command (read this first)

Every wheel declares its sibling dependency as a **bare spec**
(`rosbagger-core>=0.2,<0.3`) with **no source attached**. The workspace
`[tool.uv.sources]` table that resolves siblings during development is *dev-only
metadata and is stripped from the built wheels*. rosbagger is published to **no
package index**, so when you install one package alone, the resolver has nowhere
to find the bare `rosbagger-core` spec and fails:

```
ERROR: Could not find a version that satisfies the requirement rosbagger-core
ERROR: No matching distribution found for rosbagger-core
```

The fix: **name every package you need in ONE `pip` / `uv pip install`
invocation.** When multiple distributions are named (or pointed at) in a single
transaction, the resolver treats each as an available candidate for the whole
run, so a bare sibling spec is satisfied by a co-named distribution — no index
lookup needed. Do **not** lead with a single-package install; it does not work.

---

## 1. The one-transaction meta recipe (install everything)

Installs all seven packages from git in a single transaction. Use either form.

> **Awaits push.** The git recipes below target the public remote
> `https://github.com/AllenDevaraj/rosbagger` at tag **`v0.2.0`**. That remote is
> currently **empty — nothing has been pushed and no `v0.2.0` tag exists yet**, so
> these literal git commands cannot run end-to-end until the repo is pushed and
> tagged. They are documented here for consumers to use once that happens. The
> locally-verified gate today is the **path-based proof** in
> [section 3](#3-local-path-install) and `scripts/proof_external_install.sh`.

With **uv**:

```bash
uv pip install \
  "rosbagger-core      @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-core" \
  "bagq                @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/bagq" \
  "rosbagger-record    @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-record" \
  "rosbagger-replay    @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-replay" \
  "rosbagger-rerun     @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-rerun" \
  "rosbagger-gui[live] @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-gui" \
  "rosbagger-desktop   @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-desktop"
```

With plain **pip**:

```bash
pip install \
  "rosbagger-core      @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-core" \
  "bagq                @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/bagq" \
  "rosbagger-record    @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-record" \
  "rosbagger-replay    @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-replay" \
  "rosbagger-rerun     @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-rerun" \
  "rosbagger-gui[live] @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-gui" \
  "rosbagger-desktop   @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-desktop"
```

---

## 2. Per-package git+subdirectory snippets (install just what you need)

Each snippet co-names the siblings the target package requires, so the bare
spec resolves in the same transaction. (These git recipes also **await push** —
see the flag in section 1.)

**Just the CLI (`bagq` + its `rosbagger-core` dependency):**

```bash
pip install \
  "rosbagger-core @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-core" \
  "bagq           @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/bagq"
```

**The GUI, offline only (`rosbagger-gui` + `rosbagger-core`):**

```bash
pip install \
  "rosbagger-core @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-core" \
  "rosbagger-gui  @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-gui"
```

**The GUI with live panels (`rosbagger-gui[live]` co-naming record + replay + core):**

```bash
pip install \
  "rosbagger-core    @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-core" \
  "rosbagger-record  @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-record" \
  "rosbagger-replay  @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-replay" \
  "rosbagger-gui[live] @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-gui"
```

The `[live]` extra pulls `rosbagger-record` and `rosbagger-replay`; because those
specs are bare too, you must co-name them (as above) so they resolve.

---

## 3. Local path install

If you have the repo checked out, install from local paths — the same
one-transaction rule applies. This is the recipe the autonomous proof
(`scripts/proof_external_install.sh`) exercises, and it runs **today** with no
network or remote dependency:

```bash
pip install ./packages/rosbagger-core ./packages/bagq \
  ./packages/rosbagger-record ./packages/rosbagger-replay \
  "./packages/rosbagger-gui[live]"
```

Quote any path carrying an extra (e.g. `"./packages/rosbagger-gui[live]"`) so
your shell does not glob-expand the brackets.

**The desktop cockpit** pulls four siblings — co-name them all in one transaction:

```bash
pip install ./packages/rosbagger-core ./packages/rosbagger-record \
  ./packages/rosbagger-replay ./packages/rosbagger-rerun \
  ./packages/rosbagger-desktop
```

Or just run `./install.sh --desktop` from the repo root — it builds the correct
one-transaction command for you. Add `--user` to install globally into
`~/.local/bin` (so `rosbagger`/`bagq` work from any terminal, no venv) instead of
a venv: `./install.sh --desktop --user`. On a distro system `pip`, `--user` mode
seeds the build prereqs and builds with `--no-build-isolation` so the source build
doesn't trip over an old system `packaging` (our PEP 639 license metadata needs
`packaging>=24.2`).

---

## 4. Consumer-side `[tool.uv.sources]` (downstream uv project)

If your own project uses **uv**, declare rosbagger as a normal version-spec
dependency and redirect it to the git source **in your own `pyproject.toml`**.
This source lives in *your* project, not in our wheels — it is the supported way
a downstream uv project consumes us while keeping our packages source-agnostic:

```toml
[project]
dependencies = ["rosbagger-gui>=0.2,<0.3", "rosbagger-core>=0.2,<0.3"]

[tool.uv.sources]
rosbagger-gui  = { git = "https://github.com/AllenDevaraj/rosbagger", tag = "v0.2.0", subdirectory = "packages/rosbagger-gui" }
rosbagger-core = { git = "https://github.com/AllenDevaraj/rosbagger", tag = "v0.2.0", subdirectory = "packages/rosbagger-core" }
```

Then `uv sync` resolves both from the git source. (This recipe also targets the
`v0.2.0` tag and so **awaits push** — see section 1.) Note that this is *not* the
same as baking the URL into our wheels: the source declaration is your project's
dev-only metadata, never written into rosbagger's published metadata.

---

## 5. Live GUI panels — `rosbagger-gui[live]`

Base `rosbagger-gui` is **offline-only**: the inspect, query, and tf panels run
with no ROS installed (no `rclpy`, no `rosbag2_py`). Importing
`rosbagger-gui` never pulls a ROS runtime.

The **record** and **replay** panels need a live ROS environment. They are
gated behind the optional `live` extra:

```toml
# rosbagger-gui's [project.optional-dependencies]
live = ["rosbagger-record>=0.2,<0.3", "rosbagger-replay>=0.2,<0.3"]
```

Install `rosbagger-gui[live]` (co-naming the siblings, as in sections 2 and 3)
to enable them. The live panels lazy-import `rclpy` inside method bodies, so the
base import stays ROS-free even with the extra installed; the panels light up
only when a ROS environment is sourced.

---

## 6. Proof recipe — verify the resolution gap is closed

A committed script proves, with no network or remote dependency, that the
one-transaction install actually resolves the bare sibling spec and runs outside
the monorepo:

```bash
PYTHONPATH="" bash scripts/proof_external_install.sh   # prints: PROOF OK
```

It performs the path-based clean-room check end to end:

1. Creates a **throwaway venv** with `python3 -m venv` (never the workspace
   `.venv`) and removes it on exit.
2. Co-installs all five packages by local path in **one** `pip` invocation, so
   the bare `rosbagger-core>=0.2,<0.3` spec resolves in-transaction.
3. `cd`s to a **neutral cwd outside the monorepo** before any smoke check, so
   nothing can resolve via the workspace source.
4. Asserts `rosbagger-gui --help` exits 0.
5. Asserts `bagq --version` is exactly `bagq 0.2.0`.
6. Asserts `import rosbagger_gui, rosbagger_core, bagq, rosbagger_record,
   rosbagger_replay` succeeds.
7. Asserts the **offline invariant** — base `import rosbagger_gui` leaks no
   `rclpy`/`rosbag2_py` into `sys.modules`.
8. Asserts `import tools` raises `ModuleNotFoundError` — the dev-only `tools/`
   directory never ships in a wheel.

> **Host note.** On a machine with ROS sourced globally, ROS leaks onto
> `PYTHONPATH` and can mask the offline assertion. Every command in the proof
> (and the invocation above) is prefixed `PYTHONPATH=""` to neutralize that
> leak. The proof is the locally-verified gate; the git+`@v0.2.0` recipes above
> run once the repo is pushed and tagged.
