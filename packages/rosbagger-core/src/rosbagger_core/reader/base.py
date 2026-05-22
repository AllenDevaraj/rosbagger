"""The backend-agnostic bag-reader seam: ``BagReader`` ABC + ``Message`` record.

This module is the typed contract every concrete reader satisfies. It is the
swappable seam (design spec §4.1, §3.3 principle 6): impl #1 is ``RosbagsReader``
(plan 02-02, wrapping ``rosbags.highlevel.AnyReader``); a future ``rosbag2_py``
backend is a deferred impl #2 behind the same interface.

It deliberately imports ONLY the standard library — no ``rosbags``, no ``numpy``,
and no ROS module (``rclpy`` / ``rosbag2_py`` / ``rosidl_runtime_py`` /
``ament_index_python``). Keeping the abstract seam ROS-free is load-bearing: it
preserves the offline invariant (design spec §3.2, enforced by
``tests/test_offline_guard.py``) and lets the contract be imported without the
heavy backend.
"""

from __future__ import annotations

import abc
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Message:
    """One bag message in the project's uniform record shape.

    Every ``BagReader.read()`` yields these. Frozen + slotted: the record is an
    immutable value object.

    Fields:
        topic: The topic name (e.g. ``/imu``); from ``connection.topic``.
        t: Log/receive time in nanoseconds. Phase 3 maps this column to
            ``TIMESTAMP_NS``.
        t_ns: The same nanosecond value, kept explicit. Phase 3 maps this column
            to ``BIGINT``.
        stamp: ``header.stamp`` in nanoseconds, or ``None`` for headerless
            messages (e.g. ``geometry_msgs/msg/Twist`` has no header).
        msgtype: The message type string (e.g. ``sensor_msgs/msg/Imu``); from
            ``connection.msgtype``.
        msg: The deserialized message object (the "fields"). Typed as ``object``
            because base.py must stay backend-agnostic.
    """

    topic: str
    t: int
    t_ns: int
    stamp: int | None
    msgtype: str
    msg: object


class BagReader(abc.ABC):
    """Swappable bag-reader seam.

    The abstract contract a concrete reader must satisfy. Impl #1 is
    ``RosbagsReader`` (plan 02-02); a ``rosbag2_py`` backend is a deferred
    impl #2 behind this same interface (design spec §4.1).

    Concrete readers implement ``open``/``close``/``read`` plus the ``topics``
    and ``connections`` metadata properties; they inherit the
    context-manager lifecycle (``__enter__``/``__exit__``) for free.
    """

    @abc.abstractmethod
    def open(self) -> None:
        """Open the underlying bag(s) and prepare for reading."""
        ...

    @abc.abstractmethod
    def close(self) -> None:
        """Release the underlying bag handle(s)."""
        ...

    @abc.abstractmethod
    def read(self) -> Iterator[Message]:
        """Lazily yield ``Message`` records, time-ordered across all opened bags.

        Implementations MUST be generators (deserialize one message at a time);
        real bags are too large to materialize eagerly.
        """
        ...

    @property
    @abc.abstractmethod
    def topics(self) -> Mapping[str, object]:
        """Topic name -> TopicInfo metadata, available without full deserialization.

        Feeds Phase 4 (Inspect). The value type is left loose as ``object``
        because the concrete ``TopicInfo`` shape is a ``rosbags`` NamedTuple
        introduced by impl #1 (02-02); base.py must not depend on ``rosbags``.
        """
        ...

    @property
    @abc.abstractmethod
    def connections(self) -> Sequence[object]:
        """Per-connection metadata, available without full deserialization.

        Like ``topics``, the element type is left loose as ``object`` so the
        seam stays backend-agnostic (the concrete ``Connection`` NamedTuple is
        a ``rosbags`` type introduced in 02-02).
        """
        ...

    # --- O(1) bag metadata (Phase 4 Inspect) --------------------------------
    # These feed plan 04-01's inspect API. Returns stay loosely typed (``int`` /
    # ``object`` / ``list``) so a future ``rosbag2_py`` backend (impl #2) can
    # satisfy the contract without base.py naming any ``rosbags`` type.

    @property
    @abc.abstractmethod
    def message_count(self) -> int:
        """Total message count across all opened bags (Phase 4 Inspect)."""
        ...

    @property
    @abc.abstractmethod
    def duration(self) -> int:
        """Whole-bag duration in nanoseconds (Phase 4 Inspect; guard empty bag)."""
        ...

    @property
    @abc.abstractmethod
    def start_time(self) -> int:
        """Earliest log time in nanoseconds across all opened bags (Inspect)."""
        ...

    @property
    @abc.abstractmethod
    def end_time(self) -> int:
        """Latest log time in nanoseconds across all opened bags (Inspect)."""
        ...

    @property
    @abc.abstractmethod
    def typestore(self) -> object:
        """The message typestore; loosely typed for the future rosbag2_py backend."""
        ...

    @property
    @abc.abstractmethod
    def paths(self) -> list:
        """The opened bag paths (for size measurement; multi-bag READ-05)."""
        ...

    # Shared lifecycle — concrete readers inherit this for free.
    def __enter__(self) -> BagReader:
        self.open()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self.close()
        return False
