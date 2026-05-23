"""Live topic discovery (D-06) + pure-Python subset selection (D-07).

Two responsibilities, deliberately split by their ROS-dependence:

* :func:`discover_topics` is the ONE ROS-bound call — it spins an ``rclpy`` node
  briefly so DDS discovery populates (external publishers are not visible
  immediately; 12-RESEARCH Pattern 3 / Pitfall 4) and returns the live
  ``{topic: type_str}`` map. ``rclpy`` is lazy-imported INSIDE the body so this
  module's top level stays ROS-free (the offline-import boundary, D-03/D-11).
* :func:`select_topics` is a PURE function (no ROS, no lazy import) that filters a
  discovered ``{topic: type}`` map by the user's selection — positional names /
  ``--all`` / ``--regex`` / ``--exclude``. The Phase-14 GUI's checkbox-select is
  the same filter over the same API (API-first / CLI↔GUI parity).

OFFLINE INVARIANT: module top imports ONLY ``__future__`` + stdlib ``re``. No
``rclpy`` at module top — ``import rosbagger_record.discovery`` pulls no ROS.

SECURITY (T-12-02): topic names and the ``regex`` / ``exclude`` patterns are
user-supplied strings, handled purely as DATA — compiled via stdlib ``re.search``
only. They are NEVER interpolated into a shell or ``eval``/``exec``.
"""

from __future__ import annotations

import re


def discover_topics(
    node: object, *, settle_iters: int = 30, settle_dt: float = 0.02
) -> dict[str, str]:
    """Discover currently-published live topics + their types (D-06 / SC1).

    Spins ``node`` ``settle_iters`` times (``settle_dt`` s each) so DDS discovery
    propagates — topics published by OTHER processes are not visible immediately
    after node creation; only the recorder's own publishers appear at once
    (12-RESEARCH Pattern 3 / Pitfall 4, verified on ROS 2 Humble). Then reads
    ``node.get_topic_names_and_types()`` (shape ``List[Tuple[str, List[str]]]``)
    and returns ``{name: types[0]}`` — the FIRST type per topic; multi-type topics
    are rare. Topics advertised with no type (empty list) are dropped.

    ``rclpy`` is imported INSIDE this body (lazy) so the module imports ROS-free.
    ``node`` is typed ``object`` because the only ROS type (the ``rclpy`` node) must
    not be named at module top; a ``MagicMock`` node drives this in unit tests
    (mock injected via ``sys.modules`` — 12-RESEARCH Pitfall 6).
    """
    import rclpy

    for _ in range(settle_iters):
        rclpy.spin_once(node, timeout_sec=settle_dt)  # let DDS discovery populate
    # take the FIRST type per topic (multi-type topics are rare); drop typeless ones
    return {name: types[0] for name, types in node.get_topic_names_and_types() if types}


def select_topics(
    discovered: dict[str, str],
    *,
    topics: list[str] | None = None,
    all_topics: bool = False,
    regex: str | None = None,
    exclude: str | None = None,
) -> dict[str, str]:
    """Filter a discovered ``{topic: type}`` map to the user's subset (D-07).

    Pure function — no ROS, no I/O. Implements the selection in a fixed
    PRECEDENCE so it is deterministic:

    1. **Base set.** If ``all_topics`` is True, start from EVERY discovered topic.
       Otherwise start from the positional ``topics`` that EXIST in ``discovered``;
       a requested name not present is silently dropped (it is simply not being
       published — the CLI in Plan 03 may warn). ``topics=None``/empty with
       ``all_topics=False`` yields an empty selection.
    2. **Regex include.** If ``regex`` is given, keep only base-set names matching
       ``re.search(regex, name)``.
    3. **Exclude.** If ``exclude`` is given, drop names matching
       ``re.search(exclude, name)``.

    Iterates over ``discovered`` in its own insertion order throughout (stable /
    deterministic output) and preserves each kept topic's discovered type string.

    SECURITY (T-12-02): ``regex`` / ``exclude`` are compiled via stdlib ``re`` only;
    topic names are pure data — never shell-interpolated or ``eval``'d. A
    pathological pattern is the local trusted user's own input (accepted ReDoS risk
    for a local CLI).
    """
    if all_topics:
        base = dict(discovered)
    else:
        wanted = set(topics or ())
        # iterate `discovered` (not `topics`) so output order is stable and types
        # are sourced from the discovered map
        base = {name: t for name, t in discovered.items() if name in wanted}

    if regex is not None:
        base = {name: t for name, t in base.items() if re.search(regex, name)}

    if exclude is not None:
        base = {name: t for name, t in base.items() if not re.search(exclude, name)}

    return base
