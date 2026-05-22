"""The API-first inspect layer — backend-neutral bag overview from O(1) metadata.

Design decision 1 (API-first): the ``bagq info`` capability lives here, in
``rosbagger-core``, NOT in the CLI. ``collect_bag_info`` reads a bag overview
(per-topic msgtype/count/Hz + whole-bag duration/size) off an OPEN reader using
ONLY O(1) ``AnyReader`` metadata — ``message_count``, ``topics`` (per-topic
``msgcount``/``msgtype``), ``start_time``/``end_time``/``duration``. It NEVER
calls ``reader.read()`` and never deserializes a message body, so a multi-GB or
decompression-bomb bag is inspected in constant time and memory (threat T-04-01).
The CLI (``bagq/cli.py``) is a thin renderer over the dataclasses returned here.

OFFLINE INVARIANT (Pitfall 5): this module transitively reaches the heavy stack
through the reader it is handed, so it MUST NOT be imported by
``rosbagger_core/__init__`` at top level. Import it explicitly at call sites
(``from rosbagger_core.inspect import collect_bag_info``) — the same pattern the
``reader`` / ``schema`` subpackages already follow. ``import rosbagger_core``
stays light (no ``rosbags`` / ``pyarrow``); ``tests/test_offline_guard.py``
enforces this.

This module itself imports only the standard library (``dataclasses``,
``pathlib``) — it does NOT import ``rosbags``, ``pyarrow``, or the schema layer,
and never deserializes a message.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TopicInfo:
    """Per-topic overview row for ``bagq info`` (mirrors ``Message``'s house style).

    Fields:
        topic: The topic name (e.g. ``/imu``).
        msgtype: The message type string (e.g. ``sensor_msgs/msg/Imu``), or
            ``None`` when the topic carries more than one message type
            (``rosbags`` collapses a heterogeneous topic to ``None``; the CLI
            renders it as ``<mixed>``).
        count: The topic's message count (``TopicInfo.msgcount``, O(1)).
        hz: Approximate publish rate — ``count / whole_bag_duration_seconds`` —
            or ``None`` when the bag has unknown/zero/negative duration. This is
            a documented approximation: it uses the WHOLE-bag span, not a
            per-topic span (``rosbags`` exposes no per-topic time bounds).
    """

    topic: str
    msgtype: str | None
    count: int
    hz: float | None


@dataclass(frozen=True, slots=True)
class BagInfo:
    """Whole-bag overview returned by :func:`collect_bag_info`.

    Fields:
        topics: One :class:`TopicInfo` per topic, sorted by topic name.
        message_count: Total messages across all opened bags.
        start_time_ns: Earliest log time in ns, or ``None`` on an empty bag.
        end_time_ns: Latest log time in ns, or ``None`` on an empty bag.
        duration_ns: ``end - start`` in ns, or ``None`` on an empty bag (the
            empty-bag guard prevents surfacing ``AnyReader``'s large-negative
            sentinel duration — Pitfall 1).
        size_bytes: On-disk size in bytes — the raw integer; human-readable
            formatting (KB/MB/GB) is the CLI's job, not the API's.
    """

    topics: list[TopicInfo]
    message_count: int
    start_time_ns: int | None
    end_time_ns: int | None
    duration_ns: int | None
    size_bytes: int


def _path_size_bytes(p: Path) -> int:
    """Size of a single bag path: summed file contents for a dir, else file size.

    A ROS 2 bag is a DIRECTORY (``metadata.yaml`` + a ``.db3``/``.mcap`` data
    file); its size is the sum of the contained file sizes — NOT the directory
    inode size, which is a meaningless ~4 KB (Pitfall 3). A ROS 1 bag is a single
    ``.bag`` FILE, so ``stat().st_size`` is the answer.
    """
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return p.stat().st_size


def _bag_size_bytes(reader) -> int:
    """Total on-disk size across every opened bag path (multi-bag READ-05)."""
    return sum(_path_size_bytes(Path(p)) for p in reader.paths)


def collect_bag_info(reader) -> BagInfo:
    """Read a whole-bag overview off an OPEN reader using O(1) metadata only.

    Reads ``message_count``, ``topics`` (per-topic ``msgcount``/``msgtype``), and
    ``start_time``/``end_time``/``duration`` — never iterates messages
    (``reader.read()``). On an empty bag (``message_count == 0``) the time bounds
    are reported as ``None`` rather than ``AnyReader``'s ``sys.maxsize`` / large
    -negative sentinels (Pitfall 1), and every per-topic ``hz`` is ``None``.

    Per-topic Hz is ``count / (duration_ns / 1e9)`` using the WHOLE-bag duration;
    it is guarded to ``None`` whenever the duration is missing, zero, or negative
    (e.g. all messages share one timestamp), so there is no division by zero and
    no negative rate.
    """
    count = reader.message_count
    if count == 0:  # empty-bag guard (Pitfall 1) — no garbage time bounds
        start_ns: int | None = None
        end_ns: int | None = None
        duration_ns: int | None = None
    else:
        start_ns = reader.start_time
        end_ns = reader.end_time
        duration_ns = reader.duration

    dur_s = (duration_ns / 1e9) if (duration_ns and duration_ns > 0) else None

    topics = [
        TopicInfo(
            topic=name,
            msgtype=info.msgtype,  # may be None for a multi-msgtype topic (Pitfall 4)
            count=info.msgcount,
            hz=(info.msgcount / dur_s) if dur_s else None,
        )
        for name, info in sorted(reader.topics.items())
    ]

    return BagInfo(
        topics=topics,
        message_count=count,
        start_time_ns=start_ns,
        end_time_ns=end_ns,
        duration_ns=duration_ns,
        size_bytes=_bag_size_bytes(reader),
    )
