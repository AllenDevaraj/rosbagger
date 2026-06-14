"""Unit tests for the rosbagger_core.topics.resolve_topics chokepoint (T3).

Proves the single topic-name resolver normalizes a missing leading slash, returns canonical
names, and raises UnknownTopicError (with a did-you-mean) on a genuine miss — the mechanism
that kills the `bagq edit --keep cmd_vel` silent-empty-bag data loss.

LOCAL-RUN: stdlib-only; run with `PYTHONPATH=""` on a ROS-equipped host (02-RESEARCH Pitfall 5).
"""

from __future__ import annotations

import pytest

from rosbagger_core.errors import UnknownTopicError
from rosbagger_core.topics import normalize_topic, resolve_topics

AVAILABLE = ["/cmd_vel", "/imu", "/camera/image_raw"]


def test_normalize_topic_adds_single_leading_slash() -> None:
    assert normalize_topic("cmd_vel") == "/cmd_vel"
    assert normalize_topic("/cmd_vel") == "/cmd_vel"
    assert normalize_topic("//cmd_vel") == "/cmd_vel"


def test_resolve_exact_match_passthrough() -> None:
    assert resolve_topics(["/cmd_vel", "/imu"], AVAILABLE) == ["/cmd_vel", "/imu"]


def test_resolve_normalizes_missing_leading_slash() -> None:
    """`cmd_vel` resolves to the canonical `/cmd_vel` (the common-case data-loss fix)."""
    assert resolve_topics(["cmd_vel", "camera/image_raw"], AVAILABLE) == [
        "/cmd_vel",
        "/camera/image_raw",
    ]


def test_resolve_preserves_request_order() -> None:
    assert resolve_topics(["imu", "cmd_vel"], AVAILABLE) == ["/imu", "/cmd_vel"]


def test_resolve_unknown_raises_with_did_you_mean() -> None:
    """A genuine typo raises UnknownTopicError carrying a difflib suggestion."""
    with pytest.raises(UnknownTopicError) as excinfo:
        resolve_topics(["cmdvel"], AVAILABLE)
    assert excinfo.value.name == "cmdvel"
    assert "/cmd_vel" in excinfo.value.suggestions
    assert "Did you mean" in str(excinfo.value)


def test_resolve_unknown_is_value_error() -> None:
    """UnknownTopicError stays a ValueError so existing handlers keep catching it."""
    with pytest.raises(ValueError):
        resolve_topics(["/nope"], AVAILABLE)
