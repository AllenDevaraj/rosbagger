"""The single topic-name resolution chokepoint (T3).

Every surface that accepts a topic NAME from the user — ``bagq edit --keep/--drop``,
``--downsample /topic:N``, replay ``--topics/--remap`` — used to exact-string-match it with
no normalization and no suggestions. A missing leading slash (``--keep cmd_vel``) then matched
nothing, and ``bagq edit`` silently wrote an EMPTY bag while reporting success (data loss),
where the very same typo in SQL would have produced a "Did you mean: /cmd_vel?".

:func:`resolve_topics` is the one place that (1) normalizes a missing leading ``/`` so
``cmd_vel`` matches ``/cmd_vel`` (the common case just works), and (2) validates each name
against the bag's available topics, raising :class:`~rosbagger_core.errors.UnknownTopicError`
(with a ``difflib`` did-you-mean) for a genuine miss — so a typo fails loudly instead of
silently selecting nothing.

OFFLINE INVARIANT: stdlib-only and NOT imported by ``rosbagger_core/__init__`` (the error it
raises lives in the stdlib-only ``errors`` module), so ``import rosbagger_core`` stays light.
"""

from __future__ import annotations

from collections.abc import Iterable


def normalize_topic(name: str) -> str:
    """Canonicalize a topic name to exactly one leading slash (``cmd_vel`` -> ``/cmd_vel``)."""
    return "/" + name.lstrip("/")


def resolve_topics(requested: Iterable[str], available: Iterable[str]) -> list[str]:
    """Resolve ``requested`` topic names against the bag's ``available`` topics (T3).

    Matches exactly first, then by normalized leading slash; returns the resolved CANONICAL
    names (as they appear in ``available``), in the order requested. Raises
    :class:`~rosbagger_core.errors.UnknownTopicError` (with a did-you-mean) for any requested
    name that matches no available topic.

    Args:
        requested: the user-supplied topic names (e.g. an ``EditOps.keep`` set).
        available: the bag's actual topic names (e.g. ``{c.topic for c in reader.connections}``).

    Returns:
        The canonical available-topic name for each requested name, in order.
    """
    available_list = list(dict.fromkeys(available))  # dedupe, preserve first-seen order
    exact = set(available_list)
    by_normalized: dict[str, str] = {}
    for topic in available_list:
        by_normalized.setdefault(normalize_topic(topic), topic)

    resolved: list[str] = []
    for name in requested:
        if name in exact:
            resolved.append(name)
            continue
        canonical = by_normalized.get(normalize_topic(name))
        if canonical is None:
            from rosbagger_core.errors import UnknownTopicError

            raise UnknownTopicError(name, available_list)
        resolved.append(canonical)
    return resolved
