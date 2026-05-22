"""Typed, framework-free domain errors shared across ``rosbagger_core`` (CLI-02/03/04).

These are the "errors that teach": a SQL table that maps to no topic, a column not
in any referenced table, or a bag whose custom message types cannot be resolved
offline. Each is a plain ``ValueError`` subclass (so existing ``except ValueError``
handlers keep working) that CARRIES the structured data the user needs to recover —
the available names, the columns grouped by table, the registration guidance — and
builds a plain-text teaching message. The ``bagq`` CLI's ``teaching_errors`` wrapper
catches them and presents the message; the API-first split (design decision 1) keeps
ALL presentation in the CLI and all domain data here.

OFFLINE INVARIANT (07-RESEARCH Pitfall 6): this module imports ONLY the standard
library — ``difflib`` for the did-you-mean ranking — and NEVER ``duckdb`` / ``pyarrow``
/ ``sqlglot`` / ``rosbags``. The library exceptions these wrap (``duckdb.BinderException``,
``rosbags`` ``AnyReaderError``) are caught where those libraries are ALREADY imported
(``backend/query.py`` function body, ``reader/rosbags_reader.py``), so referencing them
here is unnecessary and would break the invariant. ``test_offline_guard.py`` asserts
``import rosbagger_core.errors`` pulls none of the heavy stack.
"""

from __future__ import annotations

import difflib


class UnknownTableError(ValueError):
    """A SQL table name maps to no topic in the bag (CLI-02).

    Subclasses ``ValueError`` so existing ``except ValueError`` handlers still catch
    it, while giving callers a typed handle. Canonical home for this class (it was
    born in ``backend/query.py``); that module re-exports it for back-compat, so
    ``from rosbagger_core.backend.query import UnknownTableError`` still resolves the
    SAME object.

    Carries the structured data (``.name`` / ``.available`` / ``.suggestions``) AND
    builds the teaching message: a ``difflib`` "Did you mean: ...?" line when a close
    match exists (cutoff 0.6 — VERIFIED to suggest the right ROS name without noise,
    07-RESEARCH §1), else the available-tables list, else a no-tables note.
    """

    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
        # difflib is stdlib (offline-safe). cutoff=0.6 was VERIFIED to suggest the
        # right ROS name ('cmdvel'->['cmd_vel'], 'tfstatic'->['tf_static']) with no
        # false positive ('wxyz123'->[], falling back to the available list).
        self.suggestions = difflib.get_close_matches(name, available, n=3, cutoff=0.6)
        if self.suggestions:
            hint = f" Did you mean: {', '.join(self.suggestions)}?"
        elif available:
            hint = f" Available tables: {', '.join(sorted(available))}."
        else:
            hint = " The bag exposes no queryable tables."
        super().__init__(f"Unknown table {name!r}.{hint}")


class UnknownColumnError(ValueError):
    """A SQL column is not in any referenced table (CLI-03).

    Raised by ``backend/query.py`` after catching ``duckdb.BinderException`` (caught
    by TYPE; the message is parsed only to extract the offending column NAME). Carries
    the offending column plus the referenced tables' columns grouped by table — for a
    single-``FROM`` query that is one table; for a multi-table JOIN it is all of them
    (07-RESEARCH §2 / Open Q2). Builds a teaching message: the offending column, a
    ``difflib`` "Did you mean: ...?" over every available column when a close match
    exists, then one ``Columns in <table>: ...`` line per table.
    """

    def __init__(self, column: str, columns_by_table: dict[str, list[str]]) -> None:
        self.column = column
        self.columns_by_table = columns_by_table
        all_cols = [c for cols in columns_by_table.values() for c in cols]
        self.suggestions = difflib.get_close_matches(column, all_cols, n=3, cutoff=0.6)
        lines = [f"Unknown column {column!r}."]
        if self.suggestions:
            lines.append(f"Did you mean: {', '.join(self.suggestions)}?")
        for table, cols in columns_by_table.items():
            lines.append(f"Columns in {table}: {', '.join(cols)}")
        super().__init__(" ".join(lines))


class UnresolvedTypeError(ValueError):
    """A bag's custom message types cannot be resolved offline (CLI-04).

    Raised at the reader boundary (``reader/rosbags_reader.py`` ``open()``) when
    ``rosbags`` reports a bag with no embedded message definitions (the SPECIFIC
    "no type definitions" ``AnyReaderError`` — other reader errors propagate, see
    07-RESEARCH Pitfall 3). Surfaces identically for ``bagq info`` / ``tables`` /
    ``query``, since all three open the reader. Carries the original library detail
    on ``.detail`` and builds registration guidance naming ``rosbags``' own
    ``get_types_from_msg`` / ``get_types_from_idl`` / ``register`` / ``default_typestore``
    (v1 teaches HOW to register; it does not load defs itself — Open Q1).
    """

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        guidance = (
            "This bag has no embedded message definitions, so its custom message types "
            "cannot be resolved offline. Register the type(s) with rosbags before reading "
            "— e.g.:\n"
            "    from rosbags.typesys import get_typestore, Stores, get_types_from_msg\n"
            "    ts = get_typestore(Stores.ROS2_HUMBLE)\n"
            "    ts.register(get_types_from_msg(open('my_pkg/msg/Widget.msg').read(), "
            "'my_pkg/msg/Widget'))\n"
            "(use get_types_from_idl for .idl). Then pass it as the reader's default_typestore."
        )
        super().__init__(guidance if not detail else f"{guidance}\n({detail})")


class NoTransformsError(ValueError):
    """A bag carries neither ``/tf`` nor ``/tf_static`` — nothing to analyze (TF-01).

    Raised by :func:`rosbagger_core.tf.collect_tf_report` when the open reader's
    ``topics`` contain neither standard TF topic, so there is no transform graph to
    build (the empty-input teaching case). Like its siblings here it subclasses
    ``ValueError`` (so existing ``except ValueError`` handlers keep working), CARRIES
    the structured data the user needs to recover — the bag's available topics on
    ``.available`` — and builds the plain-text teaching message in core. The CLI
    mechanism (Plan 03) widens ``bagq``'s ``teaching_errors`` wrapper by one import +
    one ``except`` entry to present this message with no traceback.

    Stays stdlib-only: it names no other class and adds no import (the module's lone
    ``difflib`` import is untouched), so ``import rosbagger_core.errors`` keeps pulling
    none of the heavy stack / no ``rosbags`` (the offline invariant in the module
    docstring).
    """

    def __init__(self, available_topics: list[str]) -> None:
        self.available = available_topics
        hint = (
            f" Available topics: {', '.join(sorted(available_topics))}."
            if available_topics
            else " The bag has no topics."
        )
        super().__init__(f"Bag has no /tf or /tf_static topics.{hint}")
