"""Topic -> table-name sanitization and collision resolution (QURY-01).

One table per topic. The table name is the topic with its single leading ``/``
dropped and remaining ``/`` turned into ``_`` (``/camera/image_raw`` ->
``camera_image_raw``; design spec §4.1, VERIFIED canonical example). Any other
character outside the SQL-identifier-safe set ``[0-9A-Za-z_]`` becomes ``_``; an
empty result (topic ``"/"``) becomes ``"topic"``; a leading-digit result gets a
``t_`` prefix (a SQL identifier may not start with a digit).

``TableNameResolver`` adds deterministic, idempotent, case-insensitive collision
resolution: two distinct topics that sanitize to the same name (``/a/b`` and
``/a.b`` both -> ``a_b``, or ``/Foo`` vs ``/foo`` under SQL case-folding) get a
numeric suffix (``a_b``, then ``a_b_2``, ...), and it records the topic ->
table-name mapping for Phase 4's ``bagq tables`` to print.

This module is intentionally pure stdlib (``re`` only) — no ``pyarrow``,
``rosbags``, or ``duckdb`` — so it stays fast to import and trivially testable.

**Security note (T-03-01 / T-03-02):** topic strings are untrusted external bag
content that become SQL identifiers in Phase 5. This module restricts the output
to the ``[0-9A-Za-z_]`` allow-list so a hostile topic cannot escape into a raw
identifier, and the resolver prevents two distinct topics from silently aliasing
to one table. It produces only quotable safe-charset names; it never quotes or
concatenates into SQL — final SQL-time quoting via ``sqlglot`` is wired in
plan ``03-03`` (research Pattern 6).
"""

from __future__ import annotations

import re

# Any character that is NOT an ASCII letter, digit, or underscore. Matching the
# research's Pattern 2 / Code Examples §1 allow-list (T-03-01 mitigation).
_UNSAFE_CHAR = re.compile(r"[^0-9A-Za-z_]")


def sanitize_table_name(topic: str) -> str:
    """Map a topic to a safe-charset table name (QURY-01).

    Rules (research Pattern 2 / Code Examples §1):

    * Drop exactly ONE leading ``/`` (``/imu`` -> ``imu``; ``imu`` -> ``imu``).
    * Replace remaining ``/`` with ``_`` (``/a/b`` -> ``a_b``).
    * Replace any character outside ``[0-9A-Za-z_]`` with ``_`` (``/a.b`` ->
      ``a_b``) — the SQL-identifier-safety allow-list.
    * An empty result (topic was ``"/"``) becomes ``"topic"``.
    * A leading-digit result gets a ``t_`` prefix (``/2d_scan`` -> ``t_2d_scan``)
      since a SQL identifier may not start with a digit.

    The rule is idempotent on an already-sanitized name
    (``sanitize_table_name("camera_image_raw") == "camera_image_raw"``).

    Note: this returns the raw safe-charset name only; it does NOT quote the
    identifier (that is done via ``sqlglot`` at SQL-build time — Phase 5 /
    plan ``03-03``), and it does NOT resolve collisions (use
    ``TableNameResolver`` for that).
    """
    name = topic[1:] if topic.startswith("/") else topic  # drop ONE leading '/'
    name = name.replace("/", "_")  # remaining '/' -> '_'
    name = _UNSAFE_CHAR.sub("_", name)  # any other odd char -> '_'
    if not name:  # e.g. the topic was exactly "/"
        name = "topic"
    if name[0].isdigit():  # SQL identifier can't start with a digit
        name = f"t_{name}"
    return name


class TableNameResolver:
    """Resolve topics to unique table names, deterministically and idempotently.

    Stateful: feed it topics one at a time via :meth:`resolve`. It sanitizes
    each topic (:func:`sanitize_table_name`) and, on a collision with a name
    already handed out, appends a deterministic numeric suffix (``_2``, ``_3``,
    ...) until the name is unique. Collisions are compared **case-insensitively**
    because SQL commonly folds identifier case, so ``/Foo`` and ``/foo`` are
    treated as colliding.

    The resolver is idempotent: resolving the SAME topic twice returns the SAME
    name and does not burn a collision suffix. It records every resolved topic
    -> table-name pair, exposed (as a copy) via :attr:`mapping` for Phase 4's
    ``bagq tables`` to print.
    """

    def __init__(self) -> None:
        # Insertion-ordered topic -> resolved table name (the recorded mapping).
        self._mapping: dict[str, str] = {}
        # Lower-cased resolved names already handed out (case-insensitive guard).
        self._used_lower: set[str] = set()

    def resolve(self, topic: str) -> str:
        """Return a unique table name for ``topic`` (idempotent per topic)."""
        # Idempotent: a topic seen before keeps its first-assigned name and does
        # not consume a new suffix.
        existing = self._mapping.get(topic)
        if existing is not None:
            return existing

        base = sanitize_table_name(topic)
        candidate = base
        suffix = 2
        # Deterministic case-insensitive de-duplication: a_b, a_b_2, a_b_3, ...
        while candidate.lower() in self._used_lower:
            candidate = f"{base}_{suffix}"
            suffix += 1

        self._mapping[topic] = candidate
        self._used_lower.add(candidate.lower())
        return candidate

    @property
    def mapping(self) -> dict[str, str]:
        """A copy of the recorded topic -> table-name mapping (Phase 4 reads this).

        Returns a copy so callers cannot mutate the resolver's internal state.
        """
        return dict(self._mapping)
