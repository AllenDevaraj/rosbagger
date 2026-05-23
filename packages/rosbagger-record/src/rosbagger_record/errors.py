"""Teaching capability errors for the live record module (D-11).

These mirror the "errors that teach" discipline of ``rosbagger_core.errors`` but
cover a different failure class: ENVIRONMENT / CAPABILITY conditions, not the
core's structured-data ``ValueError`` family (unknown table/column/type). When a
required ROS runtime piece is absent, the user gets a plain-text remedy ("source
your ROS 2 environment" / "install the storage plugin") instead of a bare
``ModuleNotFoundError`` or an opaque ``pluginlib`` RuntimeError.

These subclass ``RuntimeError`` (NOT ``ValueError``): a missing ROS install or an
unregistered storage plugin is a runtime/capability state of the environment, not
a bad-argument condition — distinct from the core teaching-data errors.

OFFLINE INVARIANT (D-11): this module imports ONLY the standard library and NEVER
``rclpy`` / ``rosbag2_py`` / ``rosidl_runtime_py`` (nor the heavy query stack). It
must stay importable in the ROS-free uv venv so ``import rosbagger_record`` (which
re-exports ``RosNotAvailableError``) leaks no ROS. ``test_offline_guard.py``
asserts ``import rosbagger_record`` pulls none of ``rclpy`` / ``rosbag2_py``.
"""

from __future__ import annotations


class RosNotAvailableError(RuntimeError):
    """``rclpy`` / ``rosbag2_py`` could not be imported — ROS 2 is not sourced.

    Raised by :func:`rosbagger_record._require_ros` (from the underlying
    ``ImportError``) when the live entry points (``record`` / ``list_topics``) are
    called in an environment without a sourced ROS 2 distro. The lazy-import
    boundary (D-03/D-11) means the package itself imports fine offline; this error
    only surfaces when ROS-bound work is actually invoked, turning a raw
    ``ModuleNotFoundError: No module named 'rclpy'`` into an actionable remedy.

    Builds the teaching message in ``__init__`` (API-first: a CLI/GUI face only
    presents it).
    """

    def __init__(self) -> None:
        super().__init__(
            "rclpy / rosbag2_py are not importable — source your ROS 2 environment "
            "before recording (e.g. `source /opt/ros/humble/setup.bash`). "
            "The offline bagq / inspect / query tools need no ROS."
        )


class NoTopicsMatchedError(RuntimeError):
    """The topic selection resolved to ZERO live topics — nothing to record.

    Raised by :func:`rosbagger_record.record.record` BEFORE opening the writer when
    the requested selection (positional ``topics`` / ``--all`` / ``--regex`` /
    ``--exclude``) matches none of the currently-discoverable topics — the day-one
    mistake of naming a topic that is mistyped or not (yet) being published. This is
    the recorder's most common usage error, so it gets the same teaching treatment as
    the capability errors: :func:`rosbagger_record.cli._capability_errors` catches it
    and prints a single stderr line + ``Exit(1)`` instead of dumping a traceback
    (mirroring ``bagq``'s ``UnknownTableError``).

    Subclasses ``RuntimeError`` (NOT ``ValueError``) for symmetry with the other
    teaching capability errors in this module and so the CLI's ``@_capability_errors``
    tuple stays a single typed family. Builds the teaching message in ``__init__``
    (API-first: a CLI/GUI face only presents it) from the structured selection inputs
    and what WAS discoverable, so the user can see both what they asked for and what is
    actually live.
    """

    def __init__(
        self,
        *,
        topics: list[str],
        all_topics: bool,
        regex: str | None,
        exclude: str | None,
        discovered: list[str],
    ) -> None:
        self.topics = topics
        self.all_topics = all_topics
        self.regex = regex
        self.exclude = exclude
        self.discovered = discovered
        super().__init__(
            f"No live topics matched (topics={topics!r}, all={all_topics}, "
            f"regex={regex!r}, exclude={exclude!r}). Currently discoverable: "
            f"{discovered or '(none)'}. "
            "Run `rosbagger-record list` to see what is being published, "
            "or pass --all to record everything."
        )


class McapStorageUnavailableError(RuntimeError):
    """The requested rosbag2 storage plugin is not registered (e.g. ``mcap``).

    Raised before opening a ``rosbag2_py`` writer when the requested ``storage_id``
    is absent from ``rosbag2_py.get_registered_writers()`` (12-RESEARCH Pattern 5 /
    Pitfall 1 — the ``mcap`` plugin is a separate apt package not installed on every
    box). Carries the structured data (``.requested`` / ``.available``) and builds a
    teaching message naming the requested id, the registered writers, and the
    remedy (install the plugin or fall back to ``--storage sqlite3``).
    """

    def __init__(self, requested: str, available: list[str]) -> None:
        self.requested = requested
        self.available = available
        avail = ", ".join(available) if available else "(none)"
        super().__init__(
            f"Storage plugin {requested!r} is not registered. "
            f"Registered writers: {avail}. "
            "Install the storage plugin (e.g. "
            "`sudo apt install ros-humble-rosbag2-storage-mcap`) "
            "or pass --storage sqlite3."
        )
