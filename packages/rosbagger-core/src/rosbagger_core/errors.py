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
        # Order-preserving dedup: a column shared across JOINed tables (e.g.
        # header.stamp.sec) would otherwise yield DUPLICATE "Did you mean" suggestions,
        # crowding out distinct near-misses within the n=3 budget.
        all_cols = list(dict.fromkeys(c for cols in columns_by_table.values() for c in cols))
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


class NonTfMessageError(ValueError):
    """A ``/tf`` / ``/tf_static`` topic carries a non-``TFMessage`` message type (TF-02).

    :func:`rosbagger_core.tf.collect_tf_report` matches the TF topics by NAME (so the
    ``tf2_msgs/TFMessage`` vs ``tf2_msgs/msg/TFMessage`` spelling never matters), then reads
    ``msg.transforms`` off every message. A remap mistake or a republisher can put a
    non-``TFMessage`` type on ``/tf`` — and ``.transforms`` would then raise a raw
    ``AttributeError`` mid-stream (a traceback, not a teaching error). The analyzer guards on
    the O(1) topic METADATA before the stream walk and raises this instead (newA7).

    Like its siblings it subclasses ``ValueError`` (so existing ``except ValueError`` handlers
    keep working) and stays stdlib-only — it names no other class and adds no import, so the
    module's offline invariant holds. Carries ``.topic`` and ``.msgtype``.
    """

    def __init__(self, topic: str, msgtype: str) -> None:
        self.topic = topic
        self.msgtype = msgtype
        super().__init__(
            f"Topic {topic!r} carries message type {msgtype!r}, not tf2_msgs/msg/TFMessage, "
            f"so it cannot be analyzed as a transform topic. Check for a topic remap or a "
            f"republisher publishing the wrong type on {topic!r}."
        )


class MixedTypeTopicError(ValueError):
    """A referenced topic exists but carries MORE THAN ONE message type (newE22).

    ``rosbags`` reports ``TopicInfo.msgtype is None`` for a topic that appears with
    different message types — within one bag, or (more commonly) for the SAME topic name
    recorded with different types across MERGED multi-bag inputs. The query orchestrator
    skips such topics (it cannot build one schema for two types), so a query against the
    topic previously failed with :class:`UnknownTableError` listing only the OTHER tables —
    telling the user the data was missing when it actually exists but is mixed-type. This
    error says so truthfully (the topic exists; it just is not singly-typed).

    Subclasses ``ValueError``; stdlib-only (no new import). Carries ``.topic`` and ``.table``.
    """

    def __init__(self, topic: str, table: str) -> None:
        self.topic = topic
        self.table = table
        super().__init__(
            f"Table {table!r} maps to topic {topic!r}, which carries more than one message "
            f"type and so cannot be queried as a single table. This usually means the topic "
            f"was recorded with different message types (often across the bags you merged). "
            f"Query a single bag, or split the inputs so {topic!r} has one consistent type."
        )


class UnknownTopicError(ValueError):
    """A requested topic name matches no topic in the bag (T3).

    The topic-name sibling of :class:`UnknownTableError`. Every topic-accepting surface
    (``bagq edit --keep/--drop``, ``--downsample /topic:N``, replay ``--topics/--remap``)
    used to exact-string-match user input with NO normalization and NO suggestions — so a
    missing leading slash (``--keep cmd_vel``) silently matched nothing and ``bagq edit``
    wrote an EMPTY bag while reporting success (data loss). The shared
    :func:`rosbagger_core.topics.resolve_topics` chokepoint normalizes the leading ``/`` and,
    when a name still matches nothing, raises this — carrying a ``difflib`` "Did you mean: …?"
    over the available topics, exactly like the SQL errors.

    Subclasses ``ValueError`` (so existing ``except ValueError`` handlers keep working) and
    stays stdlib-only (``difflib``; no new import). Carries ``.name`` / ``.available`` /
    ``.suggestions``.
    """

    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
        # Suggest against the raw name first, then the slash-normalized form (so a bare
        # `cmdvel` still surfaces `/cmd_vel` as a near miss). cutoff 0.6 mirrors the SQL errors.
        self.suggestions = difflib.get_close_matches(name, available, n=3, cutoff=0.6)
        if not self.suggestions:
            normalized = "/" + name.lstrip("/")
            self.suggestions = difflib.get_close_matches(normalized, available, n=3, cutoff=0.6)
        if self.suggestions:
            hint = f" Did you mean: {', '.join(self.suggestions)}?"
        elif available:
            hint = f" Available topics: {', '.join(sorted(available))}."
        else:
            hint = " The bag has no topics."
        super().__init__(f"Unknown topic {name!r}.{hint}")


class MultiBagEventsError(ValueError):
    """The reserved ``events`` table was referenced against a MULTI-bag reader (newE23).

    The per-bag event sidecar (``<bag>.events.parquet``) is loaded for a SINGLE bag
    (``reader.paths[0]``); multi-bag events are deferred. When the SQL references ``events``
    while more than one bag is open, the orchestrator previously loaded ONLY the first bag's
    sidecar and silently joined it against the merged multi-bag stream — dropping every event
    recorded against the 2nd..Nth bags with no warning (quietly wrong analysis). It now raises
    this instead of returning a wrong result.

    Subclasses ``ValueError``; stdlib-only (no new import). Carries ``.n_bags``.
    """

    def __init__(self, n_bags: int) -> None:
        self.n_bags = n_bags
        super().__init__(
            f"The 'events' table is not supported across multiple bags yet (you opened "
            f"{n_bags} bags). Each bag has its own '<bag>.events.parquet' sidecar; joining one "
            f"bag's events against the merged multi-bag stream would silently drop the others' "
            f"events. Query a single bag at a time when referencing 'events'."
        )
