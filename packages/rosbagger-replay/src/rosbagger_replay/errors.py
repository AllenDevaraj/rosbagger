"""Teaching capability errors for the live replay module (D-12).

These mirror the "errors that teach" discipline of ``rosbagger_record.errors``:
they cover ENVIRONMENT / CAPABILITY and USAGE conditions, not the core's
structured-data ``ValueError`` family. When the ROS runtime is absent, or when a
topic selection matches nothing to replay, the user gets a plain-text remedy
("source your ROS 2 environment" / "check the bag path and --topics") instead of a
bare ``ModuleNotFoundError`` or a silent empty run.

These subclass ``RuntimeError`` (NOT ``ValueError``): a missing ROS install is a
runtime/capability state of the environment, and an empty replay selection is a
usage state of the request — both distinct from the core teaching-data errors. A
single typed family keeps the CLI's ``@_capability_errors`` tuple (Plan 03) clean.

OFFLINE INVARIANT (D-12): this module imports ONLY the standard library and NEVER
``rclpy`` / ``rosbag2_py`` / ``rosidl_runtime_py`` (nor the heavy query stack). It
must stay importable in the ROS-free uv venv so ``import rosbagger_replay`` (which
re-exports these) leaks no ROS. ``test_offline_guard.py`` (extended in Plan 03)
asserts ``import rosbagger_replay`` pulls none of ``rclpy`` / ``rosbag2_py``.
"""

from __future__ import annotations


class RosNotAvailableError(RuntimeError):
    """``rclpy`` could not be imported — ROS 2 is not sourced.

    Raised by the lazy ROS-availability guard (Plan 03) from the underlying
    ``ImportError`` when the live ``replay`` entry point is called in an
    environment without a sourced ROS 2 distro. The lazy-import boundary
    (D-03/D-12) means the package itself imports fine offline; this error only
    surfaces when ROS-bound work is actually invoked, turning a raw
    ``ModuleNotFoundError: No module named 'rclpy'`` into an actionable remedy.

    Builds the teaching message in ``__init__`` (API-first: a CLI/GUI face only
    presents it).
    """

    def __init__(self) -> None:
        super().__init__(
            "rclpy is not importable — source your ROS 2 environment "
            "before replaying (e.g. `source /opt/ros/humble/setup.bash`). "
            "The offline bagq / inspect / query tools need no ROS."
        )


class NoMessagesToReplayError(RuntimeError):
    """The replay selection resolved to ZERO messages — nothing to publish.

    Raised by the replay path BEFORE creating publishers when the requested
    selection (positional ``bag_paths`` + an optional ``--topics`` subset) matches
    no messages in the bag — the day-one mistake of naming a topic that is
    mistyped or not present in the bag. This is replay's most common usage error,
    so it gets the same teaching treatment as the capability error:
    ``rosbagger_replay.cli._capability_errors`` (Plan 03) catches it and prints a
    single stderr line + ``Exit(1)`` instead of dumping a traceback.

    Subclasses ``RuntimeError`` (NOT ``ValueError``) for symmetry with the other
    teaching capability error in this module and so the CLI's ``@_capability_errors``
    tuple stays a single typed family. Carries its structured selection inputs
    (``.bag_paths`` / ``.topics``) and builds the teaching message in ``__init__``
    (API-first: a CLI/GUI face only presents it), so the user sees both what they
    asked for and the remedy.
    """

    def __init__(self, *, bag_paths: object, topics: object) -> None:
        self.bag_paths = bag_paths
        self.topics = topics
        super().__init__(
            f"No messages to replay (bag_paths={bag_paths!r}, topics={topics!r}). "
            "Check the bag path and that --topics names a topic that exists in the "
            "bag; run `rosbagger-replay <bag>` with no --topics filter to replay "
            "everything."
        )
