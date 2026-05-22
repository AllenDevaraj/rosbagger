# Phase 7: CLI & Teaching Errors - Research

**Researched:** 2026-05-22
**Domain:** CLI finalization (typer/click) + teaching error UX over the existing `bagq`/`rosbagger-core` stack
**Confidence:** HIGH

## Summary

Phase 7 is the **last v1 feature phase**: it finalizes the `bagq` CLI surface and adds errors that TEACH (CLI-01..04). Almost no new "engine" code is needed — Phases 2-6 already built the reader, schema, query backend, and output writers, and `bagq query`/`info`/`tables` are already wired and runnable as a console script (`bagq --version` exits 0; `bagq query "<SQL>" BAG` returns rows). The actual work is two-fold: (1) **convert raw exceptions into clean teaching messages with non-zero exit codes** instead of Python tracebacks, and (2) **enrich the data those errors carry** (did-you-mean suggestions, the offending table's column list, custom-msg registration guidance). Two carry-forward Phase-6 review WARNINGs (WR-01 extension parsing, WR-02 `/dev/stdout` portability) are also fixed here because this phase touches `cli.py` + `output/export.py`.

The single most important empirical finding (all verified this session against the installed stack — duckdb 1.5.3, rosbags 0.11.2, sqlglot 30.8.0, pyarrow 24.0.0): **each of the three teaching-error cases has a precise, reproducible trigger and exception type.** CLI-02 (unknown table) already raises a typed `UnknownTableError` from `backend/query.py` carrying the available tables — it just needs did-you-mean enrichment + CLI presentation. CLI-03 (unknown column) surfaces as `duckdb.BinderException` from `con.execute()` inside the backend, with a message that already includes (truncated) "Candidate bindings" but never names the table. CLI-04 (unresolvable custom msg) surfaces as `rosbags.highlevel.AnyReaderError` with the **exact** message `Bag contains no type definitions. Instantiate AnyReader with a default_typestore argument.`, raised at **`open()`** time — so `bagq info`/`tables`/`query` all hit it identically.

**Primary recommendation:** Keep the API-first split. Core (`rosbagger_core`) raises **typed, data-carrying** exceptions (a small stdlib-only `errors` module); the CLI (`bagq`) owns **all presentation** via a shared error-handling pattern (`typer.secho(..., err=True)` + `raise typer.Exit(1)`). Enrich `UnknownTableError` with `difflib.get_close_matches` suggestions in core; add an `UnknownColumnError` that core raises by catching `BinderException` in `query()` and attaching the referenced tables' column lists; add an `UnresolvedTypeError` (or detect the specific `AnyReaderError` message at the reader boundary) carrying registration guidance. The CLI catches these typed errors in each command (a shared `@teaching_errors` decorator) and prints the message cleanly. **Recommended plan split: 07-01 = CLI wiring/finalization + WR-01/WR-02 fixes; 07-02 = teaching errors (the three typed exceptions + CLI presentation + CLI-04 fixture).**

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Parse CLI args, dispatch subcommands, `--help`/`--version` | `bagq/cli.py` (typer) | — | typer owns argv→callable; already wired |
| Catch typed core errors → clean message + non-zero exit | `bagq/cli.py` (presentation) | — | Design decision 1 (API-first): CLI owns ALL user-facing rendering, incl. errors |
| Raise typed, data-carrying exceptions | `rosbagger_core` (`errors.py`, `backend/query.py`, reader) | — | Core owns domain logic; carries the *data* (available tables, columns, guidance) but NOT the *formatting* |
| Did-you-mean suggestion computation (`difflib`) | `rosbagger_core` (where the candidate list lives) | `bagq/cli.py` (could format) | `difflib` is stdlib (offline-safe); compute next to the available-names list in core, present in CLI |
| Detect unknown column (`BinderException`) → typed error | `rosbagger_core/backend/query.py` | — | The column candidates (`TableSchema.columns`) are known in `query()`; map there |
| Detect unresolvable custom msg (`AnyReaderError`) → typed error | `rosbagger_core/reader/rosbags_reader.py` (`open()`) | `bagq/cli.py` | The error fires at `reader.open()`; wrap at the reader boundary so info/tables/query all benefit |
| CSV-to-stdout buffering (WR-02 portability) | `rosbagger_core/output/export.py` | `bagq/cli.py` (echo) | Keep `COPY` + duckdb in core (offline invariant); CLI does the Python-level echo |
| Output extension parsing (WR-01 robustness) | `rosbagger_core/output/export.py` | — | Pure fix in `write_table`; `os.path.splitext(os.path.basename(path))` |

## User Constraints

> **No `CONTEXT.md` exists for this phase** (no `/gsd:discuss-phase` was run). Constraints below are drawn from `CLAUDE.md`, the design spec, REQUIREMENTS.md, and the carried-forward Phase-6 review. Treat them with the same authority as locked decisions.

### Locked Decisions (from CLAUDE.md / design spec / prior phases)
- **Offline / NO-ROS invariant (load-bearing).** Any new errors module in `rosbagger_core` must be **stdlib-only at import** (`difflib` is stdlib — fine). `import rosbagger_core` / `import rosbagger_core.backend` / `import rosbagger_core.output` must NOT pull `duckdb`/`sqlglot`/`pyarrow`/`rclpy` (enforced by `tests/test_offline_guard.py`).
- **API-first thin CLI (design decision 1).** All computation lives in `rosbagger_core`; `bagq/cli.py` only renders. **This extends to errors:** core raises typed, data-carrying exceptions; the CLI owns presentation.
- **`bagq/cli.py` imports only typer/rich/click at top level.** Core API (incl. any `errors` module that transitively pulls heavy deps) is imported LAZILY inside command bodies. `difflib`/`os` are stdlib and safe anywhere.
- **Python ≥ 3.10.**
- **Portability: offline tools run anywhere, CI included** (CLAUDE.md). This is the WR-02 driver: no `/dev/stdout` dependence (absent on Windows).
- **Interop: emit standard formats; never rebuild existing viewers.** Unchanged this phase.
- **Keep core exceptions in `rosbagger_core`** (typed, data-carrying); CLI owns presentation. (Stated explicitly in the phase brief; consistent with `UnknownTableError` already living in `backend/query.py`.)

### Claude's Discretion
- Whether the typed errors live in a new `rosbagger_core/errors.py` or stay co-located with the code that raises them (`UnknownTableError` is currently in `backend/query.py`). **Recommendation:** a small `rosbagger_core/errors.py` for shared, stdlib-only exception classes that both reader and backend import (keeps the offline invariant trivially, gives the CLI one import site). `UnknownTableError` can re-export from there for back-compat.
- Whether the CLI catch logic is a shared decorator (`@teaching_errors`) or an inline `try/except` per command. **Recommendation:** a shared decorator/helper — three commands need the same catch set.
- Whether did-you-mean is computed in core (enriching the exception) or in the CLI. **Recommendation:** compute in core next to the available-names list; present in CLI.
- Exact `difflib` cutoff/n (recommend `n=3, cutoff=0.6` — verified to produce good ROS-name suggestions; see Code Examples).
- Whether to add `--version` (it already exists) any additional top-level UX (e.g. epilog examples). Minimal additions only.

### Deferred Ideas (OUT OF SCOPE for this phase)
- Alias packs (`vx` → `"twist.twist.linear.x"`) — QURY-08, v2.
- Column projection pushdown — QURY-09, v2.
- `rosbag2_py` reader backend (for live-workspace custom msgs `rosbags` can't resolve) — explicitly deferred (REQUIREMENTS.md Out of Scope). CLI-04 only needs to *explain how to register* defs with `rosbags`, not to add a second reader.
- Rich timeseries plotting / 3D viz — owned by external tools.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CLI-01 | `bagq query "<SQL>" BAG...` runs end-to-end | **Largely MET.** VERIFIED: `bagq --version` exits 0 as a console script; `query`/`info`/`tables` are wired (`bagq.cli:app`); `bagq query "SELECT t,t_ns,topic FROM cmd_vel" ros1.bag` returns 3 rows (existing `test_cli_query.py`). 07-01 ADDS: cohesive top-level UX, and (critically) clean error-exit handling so failures aren't raw tracebacks. See "What 07-01 should ADD". |
| CLI-02 | Unknown table → lists available topics (did-you-mean) | **BASE EXISTS.** `backend/query.py` raises `UnknownTableError` already listing available tables. ENHANCE: add `difflib.get_close_matches` suggestion (verified to work on ROS table names) + CLI presentation. See Pattern 1, Code Examples §1. |
| CLI-03 | Unknown column → shows that table's columns | VERIFIED: an unknown column raises `duckdb.BinderException` at `con.execute()` (message: `Binder Error: Referenced column "X" not found in FROM clause! Candidate bindings: ...`). Catch in `query()`, attach the referenced tables' `TableSchema.columns`, raise typed `UnknownColumnError`; CLI presents. See Pattern 2, Code Examples §2. |
| CLI-04 | Unresolvable custom msg type → explains registering `.msg`/`.idl` with `rosbags` | VERIFIED: triggers `rosbags.highlevel.AnyReaderError` at **`reader.open()`** with the exact message `Bag contains no type definitions. Instantiate AnyReader with a default_typestore argument.`. Detect this specific case (string match or wrap at reader boundary), raise typed `UnresolvedTypeError` with registration guidance; CLI presents. Surfaces in info/tables/query alike (all call `open()`). See Pattern 3, Code Examples §3, Pitfall 5. |
</phase_requirements>

## What 07-01 Should ADD (CLI-01 is largely met)

Confirmed by running the console script and CliRunner this session. The `bagq` entry point, `--version`, `--help`, and all three subcommands work. 07-01's real additions:

1. **Clean error-exit handling (the load-bearing add).** TODAY, `bagq query "SELECT * FROM nonexistent" bag` exits 1 but with **empty stdout and an uncaught `UnknownTableError`** — i.e. a Python traceback in a real shell (VERIFIED: CliRunner reports `r.exception = UnknownTableError`, `r.output = ''`). Same for `BinderException` (unknown column) and `AnyReaderError`/`FileNotFoundError`. 07-01 must catch the known error set in each command and print a clean message + non-zero exit (no traceback). This is the foundation 07-02's teaching messages plug into.
2. **WR-02 portability fix** in `output/export.py` (`--format csv` without `-o`) — see Pitfall 1 + Code Examples §4.
3. **WR-01 robustness fix** in `output/export.py` (`write_table` extension parsing) — see Pitfall 2 + Code Examples §5.
4. **Top-level UX polish (minimal).** `--version` already exists. Optionally add a short epilog with one example invocation. Do NOT over-build; the design spec wants a thin CLI.
5. **Confirm end-to-end from a real shell**, not just CliRunner — e.g. a subprocess smoke test (`subprocess.run(["bagq","query",...])`) asserting a row in real stdout. This also guards the WR-02 fix (CliRunner can't capture the old `/dev/stdout` write; a real-shell test or the buffered-echo fix makes it observable).

**Recommended 07-01 vs 07-02 split:**

| Plan | Scope | REQ | Rationale |
|------|-------|-----|-----------|
| **07-01 — CLI wiring & portability fixes** | Top-level UX confirmation; the shared error-exit *mechanism* (catch typed errors → clean message → `Exit(1)`); WR-01 + WR-02 fixes; real-shell end-to-end smoke test | CLI-01 (+ WR-01/WR-02) | These are about the CLI *surface* and the carry-forward review items. The error *mechanism* (catch + Exit) is generic; the teaching *content* is 07-02. Touching `output/export.py` for WR-01/02 is naturally co-located with CLI wiring. |
| **07-02 — Teaching errors** | The three typed exceptions (enrich `UnknownTableError` with did-you-mean; add `UnknownColumnError`; add `UnresolvedTypeError`); CLI presentation of each; the CLI-04 fixture (a def-less bag) | CLI-02, CLI-03, CLI-04 | Pure teaching-UX content, built on 07-01's catch mechanism. Each error is independently testable. |

> Alternative: fold WR-01/WR-02 into 07-01 (recommended) rather than a third plan — they're small, mechanical, and in the same file the CLI work touches.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `typer` | 0.15–<1 (locked) | CLI framework; `typer.secho`/`typer.Exit` for clean error presentation | Already the locked CLI lib (`bagq/pyproject.toml`); `Exit(code=1)` is the idiomatic non-traceback exit `[VERIFIED: installed + CliRunner test this session]` |
| `click` | (transitive via typer) | `_PlotCommand` already subclasses `TyperCommand`; click exceptions/exit underlie typer | Already used in `cli.py` for the `--plot` optional-value flag |
| `rich` | >=13 (locked) | Optional colored/structured error output (`rich.console`) | Already used for tables; `typer.secho` is sufficient for error lines |
| stdlib `difflib` | — (Python ≥3.10) | `get_close_matches` for did-you-mean (CLI-02, CLI-03) | **Stdlib — offline-safe at import.** VERIFIED to produce good suggestions on ROS table/column names. NO new dependency. |
| stdlib `os` | — | `os.path.splitext`/`os.path.basename` for WR-01 extension fix | Stdlib |
| stdlib `tempfile` | — | `NamedTemporaryFile` for WR-02 CSV buffering | Stdlib |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `duckdb` | 1.5.3 (locked in core) | Source of `BinderException` (CLI-03); `COPY` for CSV buffering | Already locked; `duckdb.BinderException` is the unknown-column signal. Import stays inside `backend`/`output` bodies (offline invariant). |
| `rosbags` | 0.11.2 (locked in core) | Source of `AnyReaderError` (CLI-04); `get_types_from_msg`/`register` for the CLI-04 *fixture* | Already locked. `AnyReaderError` import path: `from rosbags.highlevel import AnyReaderError`. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `difflib.get_close_matches` (stdlib) | `thefuzz`/`rapidfuzz` (Levenshtein) | New dependency for marginal gain. `difflib` (SequenceMatcher ratio) is stdlib, offline-safe, and VERIFIED to suggest the right ROS names. **Use difflib.** |
| `typer.secho` + `typer.Exit(1)` | Raise `click.ClickException` (auto-formats + exits non-zero) | `ClickException` is also clean (its `.show()` prints `Error: <msg>` to stderr, exit 1) and could let core raise CLI-agnostic messages — BUT it couples core to click. Keep core exceptions framework-free (`ValueError` subclasses); catch + `secho` in the CLI. **Use secho/Exit.** |
| String-matching the DuckDB message to detect unknown column | Catch `duckdb.BinderException` by TYPE | Type-catch is robust across locales/versions; the message string is then parsed only to extract the column NAME (for did-you-mean). **Catch by type, parse message for the name.** |
| Wrapping `AnyReaderError` at the reader boundary | Catching `AnyReaderError` in the CLI and string-matching | Wrapping at the reader (where the semantics are clear) gives the CLI ONE typed `UnresolvedTypeError` to catch and keeps the "is this the no-defs case?" decision in core. Either works; **recommend reader-boundary wrap** (the Phase-2 research explicitly deferred this wrap to Phase 7). |

**Installation:** **None.** No new third-party dependency. `difflib`/`os`/`tempfile` are stdlib; `typer`/`rich`/`duckdb`/`rosbags` are already locked.

**Version verification (performed this session):**
```
duckdb  1.5.3     # .venv — duckdb.BinderException / .CatalogException confirmed
rosbags 0.11.2    # .venv — AnyReaderError import + message confirmed
sqlglot 30.8.0    # .venv — referenced_columns / referenced_tables confirmed
pyarrow 24.0.0    # .venv
typer   0.15–<1   # bagq/pyproject.toml lock; secho/Exit idiom confirmed via CliRunner
```

## Package Legitimacy Audit

> This phase installs **NO new packages.** All functionality uses already-locked deps (`typer`/`rich`/`duckdb`/`rosbags`) plus the Python standard library (`difflib`/`os`/`tempfile`). No registry verification or slopcheck run is required because nothing new is added to `pyproject.toml`.

| Package | Registry | Disposition |
|---------|----------|-------------|
| (none added) | — | N/A — phase uses locked deps + stdlib only |

**Packages removed due to slopcheck [SLOP] verdict:** none (none added)
**Packages flagged as suspicious [SUS]:** none (none added)

## Architecture Patterns

### System Architecture Diagram

```
                     user types: bagq query "<SQL>" BAG... [-o] [--format] [--plot]
                                              │
                                              ▼
                  ┌─────────────────────────────────────────────────────────┐
                  │  bagq/cli.py  (typer app — PRESENTATION ONLY)             │
                  │   @app.command query/info/tables                          │
                  │   @teaching_errors  ── shared catch wrapper ──┐           │
                  └───────────────────────┬───────────────────────┼──────────┘
                          lazy import core │            catches:   │
                                           ▼                       │
        ┌──────────────────────────────────────────────┐          │
        │ rosbagger_core  (DATA-CARRYING, framework-free)│          │
        │                                                │          │
        │  reader.open() ──► AnyReaderError "no type     │   UnresolvedTypeError
        │     │                defs"  ──wrap──► UnresolvedTypeError ─┤  (CLI-04)
        │     ▼                                          │          │
        │  backend.query.query(sql, reader)              │          │
        │     ├─ resolve tables (sqlglot)                │          │
        │     ├─ table∉bag ──► UnknownTableError ────────┼── + difflib did-you-mean
        │     │                 (lists available tables) │          │  (CLI-02)
        │     ├─ load topics, register Arrow             │          │
        │     └─ backend.execute(sql)                    │          │
        │            └─ duckdb BinderException (bad col)  │   UnknownColumnError
        │                 ──catch+map──► UnknownColumnError┼── + that table's columns
        │                  (attach TableSchema.columns)   │          │  (CLI-03)
        │                                                │          │
        │  output.export.write_table  ── WR-01 fix       │          │
        │  output.export.write_csv_buffer ── WR-02 fix   │          ▼
        └────────────────────────────────────────────────┘   typer.secho(msg, err=True)
                                                              raise typer.Exit(1)
                                                              ── clean message, exit 1,
                                                                 NO traceback
```

Each typed error is a `ValueError` subclass (framework-free) raised by core and caught by the CLI's `@teaching_errors` wrapper. The CLI is the only tier that imports typer; core stays presentation-agnostic.

### Recommended Project Structure
```
packages/rosbagger-core/src/rosbagger_core/
├── errors.py              # NEW (recommended): stdlib-only typed exceptions
│                          #   UnknownTableError (re-exported / moved from backend/query),
│                          #   UnknownColumnError, UnresolvedTypeError
├── backend/query.py       # EDIT: enrich UnknownTableError w/ difflib; catch BinderException
│                          #   -> UnknownColumnError carrying referenced tables' columns
├── reader/rosbags_reader.py  # EDIT: wrap the "no type definitions" AnyReaderError ->
│                          #   UnresolvedTypeError in open() (CLI-04)
└── output/export.py       # EDIT: WR-01 (splitext) + WR-02 (buffer CSV, no /dev/stdout)

packages/bagq/src/bagq/
└── cli.py                 # EDIT: @teaching_errors wrapper; catch the typed errors;
                           #   route --format csv through the buffered writer + click.echo
```

> **Offline-guard note:** `rosbagger_core/errors.py` must import ONLY stdlib (it may import `difflib` if did-you-mean lives there, or keep difflib in `backend/query.py` — both stdlib). It must NOT import `duckdb`/`pyarrow`/`rosbags` at module top level, so `import rosbagger_core.errors` stays light. The CLI imports the errors LAZILY inside command bodies (or via the wrapper) — but since they're stdlib-only, importing them at `cli.py` top level would also be safe. **Add a regression test** asserting `import rosbagger_core.errors` does not pull the heavy stack (mirror the existing `test_offline_guard.py` subprocess checks).

### Pattern 1: Enrich a typed, data-carrying error with did-you-mean (CLI-02)
**What:** Core raises a typed exception that carries the *structured data* (the offending name + the available names + computed suggestions). The message string is built in core (it's plain text, not formatting), but the CLI could also re-format from the attributes.
**When to use:** CLI-02 (unknown table). Same shape reused for CLI-03 (unknown column).
**Example:** see Code Examples §1.

### Pattern 2: Catch a backend exception, map to a domain error with context (CLI-03)
**What:** `query()` already knows the referenced tables and can build each `TableSchema` (it does, to load topics). Wrap `backend.execute(sql)` in a `try/except duckdb.BinderException`, extract the column name from the message, look it up against the referenced tables' columns, and raise `UnknownColumnError(column, table_columns, suggestions)`. **Catch by exception TYPE; parse the message only to get the column name.**
**When to use:** CLI-03. The duckdb import is already lazy in `query()` via `_default_backend`; catching `duckdb.BinderException` requires importing `duckdb` in `query()` — keep it inside the function body (offline invariant), OR catch on the message/type at the `DuckDBBackend.execute` boundary and re-raise a core error. **Recommendation:** catch in `query()` (it has the column→table context); `import duckdb` lazily there.
**Example:** see Code Examples §2.

### Pattern 3: Wrap a library error at the boundary where its meaning is clear (CLI-04)
**What:** `RosbagsReader.open()` is the single choke point for "bag has no resolvable type defs." Catch the specific `AnyReaderError` whose message is `Bag contains no type definitions...` and re-raise `UnresolvedTypeError` with registration guidance, preserving the original as `__cause__`. Because `info`/`tables`/`query` all go through `RosbagsReader.open()` (via `with RosbagsReader(...)`), all three get the teaching error for free.
**When to use:** CLI-04. Keep OTHER `AnyReaderError`s (mixed format) and `FileNotFoundError` propagating as their own (CLI catches them with a generic clean message).
**Example:** see Code Examples §3.

### Pattern 4: Shared CLI error-handling wrapper (the catch mechanism)
**What:** A decorator (or a small `run_command(fn)` helper) that wraps each command body, catches the known typed-error set, prints a clean message via `typer.secho(..., fg=RED, err=True)`, and raises `typer.Exit(1)`. Unknown exceptions are NOT swallowed (let real bugs surface — Pitfall 4).
**When to use:** all three commands. Centralizes the catch set so a new error type is handled in one place.
**Example:** see Code Examples §6.

### Anti-Patterns to Avoid
- **Catching bare `Exception` in the CLI and printing a generic message.** Swallows real bugs (Pitfall 4). Catch only the known typed set + `FileNotFoundError`/`AnyReaderError`; let everything else traceback.
- **Building the teaching message in the CLI from a string-parsed core message.** Brittle. Core should carry the *data* (available names, columns) as exception attributes; the CLI formats from attributes (or core builds the plain-text message). Don't regex core messages in the CLI.
- **Coupling core exceptions to typer/click.** Keep them `ValueError` subclasses (framework-free) in `rosbagger_core`. Only the CLI imports typer.
- **`COPY ... TO '/dev/stdout'` for `--format csv`.** Bypasses `sys.stdout`, breaks on Windows, uncapturable by CliRunner (WR-02 — VERIFIED). Buffer to a temp file, read, echo via Python.
- **`path.rsplit('.', 1)` over the whole path for extension detection.** Grabs garbage when a parent dir contains a dot (WR-01 — VERIFIED: `/home/user/v1.2/results/output` → ext `'2/results/output'`). Use `os.path.splitext(os.path.basename(path))`.
- **Importing `duckdb` at the top of `backend/query.py` to catch `BinderException`.** Breaks the offline invariant. Import inside the function body (it's already lazy there).
- **Detecting CLI-04 by catching ALL `AnyReaderError`.** Mixed-format and reader errors are also `AnyReaderError` — match the specific "no type definitions" message (or check `isinstance` + message substring) so only the def-less case gets the registration guidance.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Fuzzy "did you mean" matching | A custom Levenshtein/edit-distance | stdlib `difflib.get_close_matches(name, available, n=3, cutoff=0.6)` | Stdlib, offline-safe, VERIFIED good on ROS names. No new dep. |
| Detecting an unknown SQL column | Pre-validating every column against the schema before execute | Let DuckDB raise `BinderException`; catch + map | DuckDB's binder is authoritative (handles aliases, expressions, JOINs, functions a pre-check would miss). Catch its typed exception. |
| Detecting an unresolvable msg type | Parsing the bag's embedded defs yourself | Let `AnyReader.open()` raise `AnyReaderError`; match the message | `rosbags` already decides resolvability at open(); re-deriving it is strictly worse and risks the offline invariant. |
| Clean non-traceback CLI exit | `sys.exit(1)` + manual `print(file=sys.stderr)` | `typer.secho(msg, err=True)` + `raise typer.Exit(1)` | typer's idiom; integrates with the click runtime, testable via CliRunner. VERIFIED. |
| In-memory CSV with LIST columns | `pyarrow.csv.write_csv` to a buffer | DuckDB `COPY` to a `NamedTemporaryFile`, read back, echo | `pyarrow.csv.write_csv` raises `ArrowInvalid` on LIST columns (VERIFIED `Unsupported Type: list<item: double>`); DuckDB COPY renders them as `"[...]"`. |
| Extension parsing | `path.rsplit('.', 1)` | `os.path.splitext(os.path.basename(path))` | Handles dotted parent dirs and extensionless files correctly (WR-01). |

**Key insight:** This phase is ~95% glue + UX. Every "detect a bad X" need is already answered by an existing library raising a precise, typed exception — the job is to **catch, enrich with the data the user needs, and present cleanly**, not to re-derive the detection. The one genuinely new computation is the did-you-mean ranking, and that's a single stdlib call.

## Runtime State Inventory

> **Not applicable — this is a feature/UX phase, not a rename/refactor/migration.** No stored data, live-service config, OS-registered state, secrets, or build artifacts carry a renamed string. The phase adds typed exceptions + CLI presentation and fixes two `output/export.py` bugs.
>
> - **Stored data:** None — no datastore keys/IDs change.
> - **Live service config:** None — no external service config.
> - **OS-registered state:** None — the `bagq` console script entry point (`bagq.cli:app`) is UNCHANGED (already registered; verified `bagq --version` works). No re-registration needed.
> - **Secrets/env vars:** None.
> - **Build artifacts:** None new. (If `errors.py` is added, a standard editable reinstall already picks it up; no egg-info rename.) Verified: `bagq/pyproject.toml` `[project.scripts]` already maps `bagq = "bagq.cli:app"` and `__version__ = "0.0.0"`.

## Common Pitfalls

### Pitfall 1: `--format csv` (no `-o`) bypasses `sys.stdout` and breaks on Windows (WR-02)
**What goes wrong:** `write_csv_stream(table)` defaults to `COPY result TO '/dev/stdout' (FORMAT CSV, HEADER)`. DuckDB writes at OS fd 1, **not** through Python's `sys.stdout` — so (a) CliRunner's capture sees nothing (VERIFIED: `r.output == ''` while the CSV printed to the real terminal out-of-order), and (b) `/dev/stdout` **does not exist on Windows** (violates CLAUDE.md "runs anywhere").
**Why it happens:** `COPY TO '<path>'` is a filesystem write at the libduckdb layer; `/dev/stdout` is a POSIX-only special file.
**How to avoid:** Buffer the CSV in `output/export.py` — `COPY result TO '<NamedTemporaryFile.csv>' (FORMAT CSV, HEADER)`, read the file text, return it (or `click.echo` it). The CLI then emits via Python (`typer.echo`/`click.echo`/`sys.stdout.write`), which IS captured by CliRunner and works on every OS. The temp-file approach (NOT `pyarrow.csv.write_csv`, which can't serialize LIST columns — VERIFIED) preserves the bracketed-LIST rendering. See Code Examples §4.
**Warning signs:** A CliRunner test of `--format csv` asserts nothing on `r.output`; CI failing on Windows with "No such file or directory: /dev/stdout".

### Pitfall 2: `write_table` extension parsing over the whole path (WR-01)
**What goes wrong:** `path_str.lower().rsplit(".", 1)[-1]` splits on the LAST dot anywhere in the path. For `/home/user/v1.2/results/output` (dot in a parent dir, no file extension) it returns `'2/results/output'` (VERIFIED), so the format lookup misfires.
**Why it happens:** `rsplit` is path-unaware.
**How to avoid:** `ext = os.path.splitext(os.path.basename(path_str))[1].lstrip(".").lower()`. VERIFIED to return `''` for the extensionless tricky path and `'csv'` for `/data/2024.05.21/run.csv`. See Code Examples §5.
**Warning signs:** A `-o` path with a dotted directory raises "Unknown output extension" for a perfectly valid `.csv`/`.parquet` filename.

### Pitfall 3: Detecting "unresolvable custom msg" by catching ALL `AnyReaderError` (CLI-04 over-match)
**What goes wrong:** `AnyReaderError` is raised for SEVERAL distinct conditions — mixed ROS1/ROS2 paths (`Unrecognized storage format '.bag'`), reader-open failures, AND the no-defs case. Catching all of them and printing "register your .msg/.idl" mislabels a mixed-format error.
**Why it happens:** `rosbags` uses one exception type for multiple failure modes (VERIFIED by reading `AnyReader.open`/`__init__` source: `raise AnyReaderError(*err.args)` for reader errors; `raise AnyReaderError('Bag contains no type definitions...')` for the no-defs case; `FileNotFoundError` for missing paths).
**How to avoid:** Match the SPECIFIC no-defs message (`"no type definitions"` substring) before re-raising `UnresolvedTypeError`; let other `AnyReaderError`s and `FileNotFoundError` propagate to the CLI's generic clean-error handler. See Code Examples §3.
**Warning signs:** A mixed-format or missing-file error tells the user to register message definitions.

### Pitfall 4: Catching too broadly in the CLI (swallowing real bugs)
**What goes wrong:** `except Exception:` in a command body turns a genuine `KeyError`/`AttributeError`/programming bug into a misleading clean message + exit 1, hiding the stack trace that would diagnose it.
**Why it happens:** Over-eager "make all errors pretty."
**How to avoid:** Catch only the KNOWN, expected set: `UnknownTableError`, `UnknownColumnError`, `UnresolvedTypeError`, `FileNotFoundError`, `AnyReaderError` (generic fallback), and the existing `typer.BadParameter`/format errors. Let everything else traceback (a real bug should be loud). The `@teaching_errors` wrapper enumerates the catch set explicitly.
**Warning signs:** Bug reports where "exit 1, Error: <vague>" hides the real exception; tests that pass because every failure looks the same.

### Pitfall 5: CLI-04 surfaces at `open()`, not at `query()`/`deserialize()` — and the realistic trigger needs a def-less bag
**What goes wrong:** (a) Placing the CLI-04 catch only around `run_query(...)` misses it, because the `AnyReaderError` fires inside `RosbagsReader.open()` (the `with RosbagsReader(...)` __enter__), BEFORE `query()` runs (VERIFIED). (b) Modern `rosbags`-written bags (ROS1 AND ROS2 v9) **embed** their defs and auto-register, so a custom type "just works" — you cannot trigger CLI-04 with an ordinary fixture (VERIFIED: a custom `my_pkg/msg/Widget` bag re-opens and deserializes fine).
**Why it happens:** (a) `with RosbagsReader(bags) as reader:` calls `open()` in `__enter__`, which is where `AnyReader.open()` raises. (b) ROS2 v9 stores defs in the `message_definitions` sqlite table / metadata; ROS1 embeds them in the bag header.
**How to avoid:** (a) Wrap the error at the reader boundary (Pattern 3) so it's caught regardless of which command opened the reader; the CLI's `@teaching_errors` wrapper covers the whole command body (including the `with`), so the catch site is uniform. (b) For the CLI-04 **fixture**, write a normal ROS2 v9 sqlite bag with a custom type, then **DELETE the `message_definitions` rows** from the `.db3` (VERIFIED: this reproduces the exact `Bag contains no type definitions...` error at `open()`). Add a `write_def_less_bag(dest)` helper to `tools/make_fixtures.py` (sqlite is the only writable-by-`rosbags` format where defs are separable; ROS1 embeds them in the header). See Code Examples §3 + §7.
**Warning signs:** A CLI-04 test that passes a normal fixture and never raises; a catch placed only around `run_query`.

### Pitfall 6: New `errors` module accidentally pulls the heavy stack at import
**What goes wrong:** If `rosbagger_core/errors.py` (or wherever `UnknownColumnError` lives) imports `duckdb` (e.g. to reference `duckdb.BinderException` in an annotation) or `pyarrow` at module top level, `import rosbagger_core.errors` (and any CLI top-level import of it) pulls the heavy stack — breaking the offline invariant and the new regression test.
**Why it happens:** Reflexively importing the library whose exception you're mapping.
**How to avoid:** The typed errors are plain `ValueError` subclasses with stdlib-only attributes (strings, lists). Catch `duckdb.BinderException` where `duckdb` is ALREADY imported lazily (`backend/query.py` function body) — never import duckdb in `errors.py`. `difflib` is stdlib and safe. Add a `test_import_errors_does_not_pull_heavy_query_stack` mirroring the existing subprocess checks.
**Warning signs:** `test_offline_guard.py` failing after adding `errors.py`; `import rosbagger_core.errors` showing `duckdb`/`pyarrow` in `sys.modules`.

## Code Examples

Verified patterns (run against the installed stack + project fixtures this session). All exception types/messages below were reproduced empirically.

### §1 — CLI-02: enrich `UnknownTableError` with did-you-mean (core), present (CLI)
```python
# Source: VERIFIED — difflib output on ROS table names this session; current UnknownTableError
#         already lives in backend/query.py and lists available tables.
# rosbagger_core/errors.py (stdlib-only)
from __future__ import annotations
import difflib

class UnknownTableError(ValueError):
    """A SQL table name maps to no topic in the bag. Carries the available names + suggestions."""
    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
        # difflib is stdlib (offline-safe). cutoff=0.6 verified to suggest the right ROS name
        # ('cmdvel'->['cmd_vel'], 'tfstatic'->['tf_static']) without noise.
        self.suggestions = difflib.get_close_matches(name, available, n=3, cutoff=0.6)
        if self.suggestions:
            hint = f" Did you mean: {', '.join(self.suggestions)}?"
        elif available:
            hint = f" Available tables: {', '.join(sorted(available))}."
        else:
            hint = " The bag exposes no queryable tables."
        super().__init__(f"Unknown table {name!r}.{hint}")

# backend/query.py — replace the inline raise with:
#   raise UnknownTableError(table, sorted(table_to_topic))
```
VERIFIED did-you-mean output (cutoff 0.6): `cmdvel→[cmd_vel]`, `cmd_vell→[cmd_vel]`, `imag→[image]`, `camera_image→[camera_image_raw]`, `tfstatic→[tf_static]`, `odomm→[odom]`; a true-garbage name (`wxyz123`) → `[]` (falls back to listing all available).

### §2 — CLI-03: catch `BinderException`, map to `UnknownColumnError` with the table's columns
```python
# Source: VERIFIED — duckdb 1.5.3 raises BinderException for an unknown column with message
#   'Binder Error: Referenced column "X" not found in FROM clause!\nCandidate bindings: ...'
import re

# rosbagger_core/errors.py
class UnknownColumnError(ValueError):
    """A SQL column is not in any referenced table. Carries the offending column + columns by table."""
    def __init__(self, column: str, columns_by_table: dict[str, list[str]]) -> None:
        self.column = column
        self.columns_by_table = columns_by_table
        import difflib
        all_cols = [c for cols in columns_by_table.values() for c in cols]
        self.suggestions = difflib.get_close_matches(column, all_cols, n=3, cutoff=0.6)
        lines = [f"Unknown column {column!r}."]
        if self.suggestions:
            lines.append(f"Did you mean: {', '.join(self.suggestions)}?")
        for table, cols in columns_by_table.items():
            lines.append(f"Columns in {table}: {', '.join(cols)}")
        super().__init__(" ".join(lines))

_BINDER_COL = re.compile(r'Referenced column "([^"]+)" not found')

# backend/query.py — wrap the execute (duckdb imported lazily INSIDE this function already):
#   import duckdb  # lazy, offline-safe
#   try:
#       return backend.execute(sql)
#   except duckdb.BinderException as e:           # catch by TYPE (robust)
#       m = _BINDER_COL.search(str(e))            # parse message ONLY for the column name
#       column = m.group(1) if m else "?"
#       # columns_by_table: each referenced table's schema columns (already built to load topics)
#       cols_by_table = {topic_to_table[t]: [c.name for c in schemas_by_topic[t].columns]
#                        for t in referenced_topics}
#       raise UnknownColumnError(column, cols_by_table) from e
```
VERIFIED column extraction from the three message variants this session (`linearx`, `linear.xx`, `topi` all parsed correctly). NOTE: `referenced_columns()` returns **bare, non-table-qualified** names (VERIFIED), and the `BinderException` message does NOT name the table — so for a multi-table JOIN, list ALL referenced tables' columns (DuckDB's own "Candidate bindings" are already cross-table). For the common single-table query, that's just the one table.

### §3 — CLI-04: wrap the no-defs `AnyReaderError` at the reader boundary
```python
# Source: VERIFIED — AnyReader.open() raises AnyReaderError('Bag contains no type definitions.
#   Instantiate AnyReader with a default_typestore argument.') for a def-less bag.
# rosbagger_core/errors.py (stdlib-only — no rosbags/duckdb import here)
class UnresolvedTypeError(ValueError):
    """A bag references message types whose definitions are not embedded and can't be resolved."""
    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        guidance = (
            "This bag has no embedded message definitions, so its custom message types "
            "cannot be resolved offline. Register the type(s) with rosbags before reading — e.g.:\n"
            "    from rosbags.typesys import get_typestore, Stores, get_types_from_msg\n"
            "    ts = get_typestore(Stores.ROS2_HUMBLE)\n"
            "    ts.register(get_types_from_msg(open('my_pkg/msg/Widget.msg').read(), 'my_pkg/msg/Widget'))\n"
            "(use get_types_from_idl for .idl). Then pass it as the reader's default_typestore."
        )
        super().__init__(guidance if not detail else f"{guidance}\n({detail})")

# reader/rosbags_reader.py — in open(), narrow the catch to the no-defs case ONLY:
#   from rosbags.highlevel import AnyReader, AnyReaderError
#   try:
#       reader.open()
#   except AnyReaderError as e:
#       if "no type definitions" in str(e):       # the SPECIFIC case (Pitfall 3)
#           from rosbagger_core.errors import UnresolvedTypeError
#           raise UnresolvedTypeError(str(e)) from e
#       raise                                     # mixed-format / other AnyReaderError propagate
```
VERIFIED: this exact message fires at `open()` (not deserialize) for a def-less ROS2 sqlite bag; `info`/`tables`/`query` all call `open()` via `with RosbagsReader(...)`, so all three get the teaching error. (Reproduced by writing a custom-type bag and `DELETE FROM message_definitions`.)

### §4 — WR-02 fix: buffer CSV via temp file, echo via Python (portable, CliRunner-capturable)
```python
# Source: VERIFIED — COPY to a NamedTemporaryFile preserves LIST columns as "[...]"; pyarrow.csv
#   can't serialize LIST (ArrowInvalid). Works on all OSes; CliRunner captures the Python echo.
import os, tempfile

def write_csv_to_string(table) -> str:
    """Return the table as CSV text (LIST columns rendered as bracketed strings)."""
    import duckdb  # lazy — offline invariant
    con = duckdb.connect()
    fd, tmp = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    try:
        con.register("result", table)
        safe = tmp.replace("'", "''")                       # T-06-01 quote-escape (unchanged)
        con.execute(f"COPY result TO '{safe}' (FORMAT CSV, HEADER)")
        with open(tmp, encoding="utf-8") as fh:
            return fh.read()
    finally:
        con.close()
        os.unlink(tmp)

# cli.py — replace write_csv_stream(result) with:
#   from rosbagger_core.output import write_csv_to_string
#   typer.echo(write_csv_to_string(result), nl=False)   # Python-level write -> captured + portable
```
VERIFIED: the temp-file CSV for an Imu LIST column round-tripped as `"[0.0, 0.0, ...]"`; `pyarrow.csv.write_csv` on the same table raised `ArrowInvalid: Unsupported Type: list<item: double>`. (Replaces `write_csv_stream`'s `/dev/stdout` target — keep or remove `write_csv_stream` per the planner's call; the buffered function is the portable replacement.)

### §5 — WR-01 fix: extension via `os.path.splitext(os.path.basename(...))`
```python
# Source: VERIFIED — handles dotted parent dirs + extensionless files.
# output/export.py write_table — replace:
#   ext = path_str.lower().rsplit(".", 1)[-1] if "." in path_str else ""
# with:
import os
ext = os.path.splitext(os.path.basename(path_str))[1].lstrip(".").lower()
```
VERIFIED: `/home/user/v1.2/results/output` → `''` (was buggy `'2/results/output'`); `/data/2024.05.21/run.csv` → `'csv'`.

### §6 — Pattern 4: the CLI `@teaching_errors` wrapper (catch set + clean exit)
```python
# Source: VERIFIED — typer.secho(..., err=True)+raise typer.Exit(1) yields exit 1, clean message,
#   NO traceback; CliRunner (typer 0.15+/click 8.2+) merges stderr into result.output.
import functools
import typer

def teaching_errors(fn):
    """Wrap a command: turn KNOWN typed errors into clean teaching messages + Exit(1).

    Catches ONLY the expected set (Pitfall 4) — real bugs still traceback.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        # Lazy import so cli.py top level stays light (errors.py is stdlib-only anyway).
        from rosbagger_core.errors import (
            UnknownColumnError, UnknownTableError, UnresolvedTypeError,
        )
        try:
            return fn(*args, **kwargs)
        except (UnknownTableError, UnknownColumnError, UnresolvedTypeError) as e:
            typer.secho(str(e), fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
        except FileNotFoundError as e:
            typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
        # AnyReaderError (non-no-defs, e.g. mixed format) — import lazily to catch it cleanly:
        # except <AnyReaderError> as e: ... (or let it propagate if a traceback is acceptable for v1)
    return wrapper

# Apply to each command:  @app.command()  \n  @teaching_errors  \n  def query(...): ...
```
VERIFIED CliRunner result for the idiom: `exit_code == 1`, `output == "Error: <message>\n"`, no traceback. NOTE: this CliRunner version exposes no `mix_stderr` kwarg (signature: `charset, env, echo_stdin, catch_exceptions, capture`) — `err=True` output lands in `result.output`, so teaching-error tests assert on `result.output`.

### §7 — CLI-04 fixture: a def-less bag (for testing the teaching error)
```python
# Source: VERIFIED — writing a normal ROS2 v9 sqlite bag then deleting the message_definitions
#   rows reproduces the exact 'Bag contains no type definitions...' AnyReaderError at open().
# tools/make_fixtures.py — add:
import sqlite3
from rosbags.rosbag2 import Writer as Ros2Writer, StoragePlugin
from rosbags.typesys import Stores, get_typestore, get_types_from_msg

_CUSTOM_MSG = "float64 widget_value\nstring widget_label\n"

def write_def_less_bag(dest_dir, *, msgtype="my_pkg/msg/Widget"):
    """Write a ROS2 sqlite bag with a custom type, then strip its embedded definitions.

    Reproduces the CLI-04 condition: AnyReader.open() raises 'Bag contains no type
    definitions...' because the message_definitions table is empty and no default_typestore
    is supplied. (ROS1 + normal ROS2 bags embed defs and auto-resolve — Pitfall 5.)
    """
    from pathlib import Path
    dest_dir = Path(dest_dir); dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / "def_less_bag"
    ts = get_typestore(Stores.ROS2_HUMBLE)
    ts.register(get_types_from_msg(_CUSTOM_MSG, msgtype))
    with Ros2Writer(path, version=9, storage_plugin=StoragePlugin.SQLITE3) as w:
        conn = w.add_connection("/widget", msgtype, typestore=ts)
        widget_t = ts.types[msgtype]
        raw = ts.serialize_cdr(widget_t(widget_value=1.0, widget_label="hi"), msgtype)
        w.write(conn, 1_000_000_000, raw)
    db = next(path.glob("*.db3"))
    c = sqlite3.connect(db)
    c.execute("DELETE FROM message_definitions")   # strip embedded defs -> unresolvable
    c.commit(); c.close()
    return path
```
VERIFIED: opening this bag with a fresh `AnyReader` (no `default_typestore`) raises `AnyReaderError('Bag contains no type definitions. Instantiate AnyReader with a default_typestore argument.')` at `open()`.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Raw exception → Python traceback in the shell | Typed core exceptions caught at the CLI → clean message + `Exit(1)` | This phase | The user-visible difference between a "tool" and a script. Tracebacks become teaching messages. |
| `COPY ... TO '/dev/stdout'` for CSV-to-stdout | Buffer via temp file + Python echo | This phase (WR-02) | Cross-platform (Windows has no `/dev/stdout`); CliRunner-capturable |
| `path.rsplit('.',1)` extension parsing | `os.path.splitext(os.path.basename(...))` | This phase (WR-01) | Correct on dotted parent dirs / extensionless paths |
| `fetch_arrow_table()` (duckdb) | `to_arrow_table()` | Already done (Phase 5) | N/A here — backend already uses the current API |

**Deprecated/outdated:**
- DuckDB `BinderException` message wording: DuckDB *also* sometimes emits its own "Did you mean" for catalog (table) errors (VERIFIED: `Catalog Error: ... Did you mean "sqlite_temp_master"?`), but for COLUMN errors it emits "Candidate bindings" (truncated, often 1-3). Don't rely on DuckDB's suggestion as the user-facing one — `bagq` should present its own complete column list (CLI-03 wants "that table's columns", not a truncated candidate set).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The DuckDB binder message prefix `Binder Error: Referenced column "X" not found` is stable across the duckdb 1.x line (used only to extract the column NAME, not to detect — detection is by exception TYPE) | Code Examples §2 | LOW — if the wording shifts, the regex returns no match and the message falls back to "Unknown column '?'" while still listing the table's columns (still useful). Detection (type-catch) is unaffected. Pin is `duckdb` (locked via core). |
| A2 | The `rosbags` no-defs message contains the substring `"no type definitions"` in 0.11.x (used to distinguish CLI-04 from other `AnyReaderError`s) | Code Examples §3 / Pitfall 3 | LOW — VERIFIED in 0.11.2 (pinned `>=0.11,<0.12`, stable for this milestone). If reworded, CLI-04 would fall through to the generic clean-error path (still non-traceback, just less specific). Re-verify only if the pin bumps. |
| A3 | `tools/make_fixtures.py` can produce the CLI-04 fixture by stripping `message_definitions` from a sqlite bag (vs needing a hand-built legacy bag) | Code Examples §7 / Pitfall 5 | LOW — VERIFIED this session end-to-end (write → strip → open raises). The only writable-by-`rosbags` format where defs are separable is ROS2 sqlite (ROS1 embeds in the header); the fixture must be sqlite. |

> Three LOW-risk assumptions, all empirically verified this session against the locked versions. No compliance/security/retention assumptions. Everything else is VERIFIED (exception types/messages reproduced) or CITED (existing project code).

## Open Questions

1. **Should `bagq` ever pass a `default_typestore`, or only teach registration?**
   - What we know: REQUIREMENTS.md defers a second reader backend; CLI-04 only requires *explaining* how to register defs. `bagq query`/`info`/`tables` currently never pass `default_typestore` (so the no-defs bag always errors at open).
   - What's unclear: whether a future flag (`--typestore`/`--msg-dir`) to actually load defs is in v1 scope.
   - Recommendation: **v1 = teach only** (CLI-04 says "explains how to register"). The `UnresolvedTypeError` guidance points at `rosbags`' `get_types_from_msg`/`register` + `default_typestore`. A `--msg`/`--typestore` flag that wires `RosbagsReader(default_typestore=...)` is a clean v2 follow-on (the reader already accepts the passthrough), NOT this phase.

2. **For a multi-table JOIN with a bad column, list which table's columns?**
   - What we know: `referenced_columns()` returns bare names; the `BinderException` message names neither the table nor (reliably) all candidates. For a single-table query the table is unambiguous.
   - What's unclear: the cleanest UX when 2+ tables are joined and the column is ambiguous.
   - Recommendation: list ALL referenced tables' columns grouped by table (Code Examples §2). The common case (single `FROM`) collapses to one table. This matches CLI-03's intent ("show that table's columns") for the dominant case and degrades gracefully for JOINs.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | runtime | ✓ | 3.10 (`.python-version`) | — |
| `typer` | CLI framework + `secho`/`Exit` | ✓ | 0.15–<1 (locked) | — |
| `rich` | table/error rendering | ✓ | >=13 (locked) | — |
| `duckdb` | `BinderException` (CLI-03), CSV `COPY` (WR-02) | ✓ | 1.5.3 (locked in core) | — |
| `rosbags` | `AnyReaderError` (CLI-04), fixture defs | ✓ | 0.11.2 (locked in core) | — |
| `sqlglot` | referenced tables/columns (existing) | ✓ | 30.8.0 (locked) | — |
| `pyarrow` | result table (existing) | ✓ | 24.0.0 (locked) | — |
| stdlib `difflib`/`os`/`tempfile` | did-you-mean / WR-01 / WR-02 | ✓ | stdlib | — |
| `bagq` console script | CLI-01 end-to-end | ✓ | installed (`bagq --version` exits 0) | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

> Everything is already installed and verified working this session. No new dependency, no external service, no network/daemon. **LOCAL-RUN REMINDER:** this dev host sources ROS 2 onto `PYTHONPATH`; run tests locally as `PYTHONPATH="" uv run pytest ...` (CI is ROS-free and needs no prefix) — consistent with every prior phase's test files.

## Validation Architecture

> `workflow.nyquist_validation` is **`false`** in `.planning/config.json`. Per the research template, this section is **omitted**. (Standard pytest tests still apply — the project's `tests/` layout + the `--cov=bagq`/`--cov=rosbagger_core` gate. Teaching-error tests should assert on `result.output` + `result.exit_code != 0` via `CliRunner` — see Code Examples §6 for the stderr-merge note — and the CLI-04 test uses the `write_def_less_bag` fixture from Code Examples §7. A real-shell `subprocess.run(["bagq", ...])` smoke test is recommended for CLI-01 + the WR-02 fix.)

## Security Domain

`security_enforcement` is not set in `.planning/config.json`. This is an offline, local single-user CLI with no auth/network/sessions/secrets. The only SQL-building surface in the touched code is the `COPY ... TO '<path>'` literal in `output/export.py`, whose quote-escape (`'`→`''`, threat T-06-01) is PRESERVED in the WR-02 fix (Code Examples §4). No new injection surface is introduced by this phase.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface (local CLI) |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | No multi-user model |
| V5 Input Validation | partial | User SQL is the intended interface (forwarded as-is — T-05-04, unchanged); the new error paths PARSE library messages (regex on `BinderException`) and bag-derived names — treat both as untrusted strings, never `eval`/exec them. The output-path quote-escape is retained. |
| V6 Cryptography | no | None — never hand-roll |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL-literal injection via the `-o` output path | Tampering | PRESERVE the existing `'`→`''` escape in the buffered CSV writer (Code Examples §4); format chosen from the closed `{csv,parquet}` map (unchanged) |
| Error message leaking internal paths/state | Information Disclosure | Local single-user CLI — the user already owns the FS; teaching messages intentionally include the bag's own type names + column names (that's the feature). No cross-user disclosure. |
| Regex/parse DoS on a crafted DuckDB/rosbags message | DoS | The parsed strings come from the project's own locked libraries (duckdb/rosbags), not arbitrary user input; the regexes are simple and bounded. Accept. |

> No security control in this phase needs a new dependency or a hand-rolled primitive. The dominant posture is unchanged from Phase 6: delegate to vetted libraries, preserve the one SQL-literal escape, present errors cleanly.

## Sources

### Primary (HIGH confidence)
- **Installed stack executed this session** (duckdb 1.5.3, rosbags 0.11.2, sqlglot 30.8.0, pyarrow 24.0.0, typer locked) — VERIFIED: `duckdb.BinderException` type + message for unknown columns; `duckdb.CatalogException` for unknown tables; `BinderException` MRO (`ProgrammingError`→`DatabaseError`); column-name extraction regex on 3 message variants; `AnyReaderError` import path + the exact `Bag contains no type definitions...` message firing at `open()`; ROS1 + ROS2 v9 def auto-registration (custom type "just works"); `message_definitions`-strip reproducing the no-defs error; `difflib.get_close_matches` output on ROS table + column names (cutoff 0.6); `typer.secho`+`Exit(1)` exit code/output/no-traceback via CliRunner; CliRunner stderr-merge behavior + signature; `pyarrow.csv.write_csv` `ArrowInvalid` on LIST columns; DuckDB `COPY` to `NamedTemporaryFile` preserving LIST rendering; WR-01 `rsplit` bug vs `os.path.splitext` fix; current `bagq query` traceback behavior for unknown table/column; `bagq --version` console-script exit 0.
- **Installed `rosbags` source** — `AnyReader.open()` / `__init__` (read this session): the no-defs `AnyReaderError` raise, the `FileNotFoundError` for missing paths, the `raise AnyReaderError(*err.args)` for reader errors, embedded-def parsing from `message_definitions`.
- **Project files** — `packages/bagq/src/bagq/cli.py` (current wiring, `_PlotCommand`, version callback), `packages/rosbagger-core/src/rosbagger_core/backend/query.py` (`UnknownTableError`, the `_topic_table_maps` inversion, the lazy execute), `.../backend/duckdb_backend.py` (`con.execute().to_arrow_table()`), `.../backend/resolve.py` (`referenced_tables_in`/`referenced_columns`/`has_star`), `.../schema/flatten.py` + `schema/__init__.py` (`build_table_schema`, `TableSchema.columns`), `.../reader/rosbags_reader.py` (`open()`/`AnyReaderError` propagation), `.../output/export.py` (WR-01/WR-02 sites, the T-06-01 escape), `.../output/__init__.py`, `tools/make_fixtures.py` (fixture API), `tests/conftest.py` + `tests/test_offline_guard.py` (the offline invariant + `no_ros` blocker), `tests/test_cli_query.py`/`test_cli_info.py` (CliRunner test patterns), `.planning/REQUIREMENTS.md` (CLI-01..04), `docs/superpowers/specs/2026-05-21-rosbagger-design.md` §4.2 ("Errors that teach"), `CLAUDE.md` (offline/portability/API-first), `.planning/phases/02-bag-reader-layer/02-RESEARCH.md` (Pitfall 4 — the `AnyReaderError` no-defs case, deferred to Phase 7).

### Secondary (MEDIUM confidence)
- **Phase 06 research/review** (referenced via the phase brief) — the WR-01/WR-02 WARNINGs and the `/dev/stdout` + `pyarrow.csv` LIST findings, re-verified empirically this session.

### Tertiary (LOW confidence)
- None relied upon. (No WebSearch was needed — every claim was verified against the installed stack and project source.)

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — no new deps; all error types/idioms reproduced against the locked, installed versions.
- Architecture (typed-error-in-core / present-in-CLI split, the three patterns): **HIGH** — each exception type, trigger, and the `secho`/`Exit` idiom verified empirically; consistent with the existing `UnknownTableError` + API-first decision.
- Pitfalls (WR-01, WR-02, CLI-04 over-match, broad-catch, open()-timing, offline-import): **HIGH** — each reproduced this session (the `/dev/stdout` capture gap, the `rsplit` bug, the `message_definitions`-strip, the `open()`-time raise, the offline-guard subprocess pattern).
- CLI-01 "largely met": **HIGH** — `bagq --version` console script and `bagq query` rows verified; the gap (clean error-exit + WR fixes) is precisely characterized.

**Research date:** 2026-05-22
**Valid until:** ~2026-06-21 (30 days). Stable for this milestone: `duckdb`, `rosbags`, `sqlglot`, `pyarrow`, `typer` are all pinned. Re-verify the `BinderException`/`AnyReaderError` message strings (A1/A2) only if a pin is bumped.
