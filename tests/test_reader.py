"""Fixture-backed regression tests for ``RosbagsReader`` (the Phase 2 reader).

These tests prove the Bag Reader Layer's three success criteria with NO ROS
install, reusing the Phase 1 fixture generator (``tools/make_fixtures.py``):

* **READ-01/02/03** — ``RosbagsReader`` opens all three target formats
  (ROS 1 ``.bag``, ROS 2 sqlite3, ROS 2 MCAP) through the one interface and
  iterates them.
* **READ-04** — iterating yields ``Message`` records carrying
  ``(topic, t, t_ns, stamp, msgtype, msg)``, with ``stamp`` derived correctly:
  ``None`` for the headerless ``/cmd_vel`` Twist, and an integer from
  ``header.stamp`` for ``/imu`` and ``/image``. The stamp is a per-message
  series (``/imu`` = ``[1_000_000_000, 2_100_000_000, 3_200_000_000]``), so only
  the FIRST ``/imu`` record (lowest ``t_ns``) equals ``1_000_000_000``.
* **READ-05** — multiple same-format bag paths read as one time-ordered logical
  dataset (covered in the merge tests below).

LOCAL-RUN REQUIREMENT (02-RESEARCH.md Pitfall 5): this dev host sources ROS 2
Humble onto ``PYTHONPATH``, which can pull ROS plugins into the test process and
crash pytest on collection. Run these tests locally with the host leak
neutralized::

    PYTHONPATH="" uv run pytest tests/test_reader.py -q

CI is ROS-free, so it needs NO prefix — and this file bakes in NO ``PYTHONPATH``
override (it is a run-time prefix only, never committed code).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# `tools` is a dev-only package at the repo root (NOT an installed distribution
# like rosbagger_core / bagq), so it is not on sys.path under pytest's default
# import mode. Put the repo root on sys.path here — scoped to this test file, so
# we touch neither tests/conftest.py nor the root pyproject.toml (mirrors the
# established convention in tests/test_fixtures.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import make_all_fixtures  # noqa: E402  (after sys.path setup)

from rosbagger_core.reader import Message, RosbagsReader  # noqa: E402  (3rd-party)

FORMATS = ("ros1", "ros2_sqlite", "ros2_mcap")
EXPECTED_TOPICS = {"/cmd_vel", "/imu", "/image"}

# Verified fixture facts (02-RESEARCH.md §1/§2, re-confirmed against the
# generator this plan): each single bag carries 9 messages — 3 each of /cmd_vel
# (Twist, headerless), /imu (Imu), /image (Image). /imu header.stamp varies per
# message (sec=1+i, nanosec=i*1e8), so the stamp series is the constant below;
# only the first (lowest-t_ns) /imu record equals FIRST_IMU_STAMP.
EXPECTED_MESSAGE_COUNT = 9
FIRST_IMU_STAMP = 1_000_000_000


@pytest.fixture(scope="session")
def fixture_bags(tmp_path_factory) -> dict[str, Path]:
    """Generate all three fixture bags once into a throwaway session tmp dir.

    Kept self-contained here (NOT reusing the ``fixture_bags`` in
    tests/test_fixtures.py) so this module's harness stands alone.
    """
    dest = tmp_path_factory.mktemp("reader_bags")
    return make_all_fixtures(dest)


# ---------------------------------------------------------------------------
# Task 1 — single-format reader tests (READ-01/02/03/04)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_reader_opens_and_yields_nine_messages(
    fixture_bags: dict[str, Path], fmt: str
) -> None:
    """Each format opens via the context manager and yields exactly 9 Messages.

    Exercises READ-01 (ROS 2 sqlite), READ-02 (ROS 2 MCAP), READ-03 (ROS 1)
    through the single ``RosbagsReader`` interface.
    """
    with RosbagsReader(fixture_bags[fmt]) as reader:
        msgs = list(reader.read())
    assert len(msgs) == EXPECTED_MESSAGE_COUNT
    assert all(isinstance(m, Message) for m in msgs)


@pytest.mark.parametrize("fmt", FORMATS)
def test_reader_yields_all_topics_with_record_fields(
    fixture_bags: dict[str, Path], fmt: str
) -> None:
    """Every format yields the three topics with well-shaped record fields (READ-04)."""
    with RosbagsReader(fixture_bags[fmt]) as reader:
        msgs = list(reader.read())
    assert {m.topic for m in msgs} == EXPECTED_TOPICS
    for m in msgs:
        assert isinstance(m.t, int)
        assert isinstance(m.t_ns, int)
        assert m.t == m.t_ns  # reader sets both to the same log-time ns
        assert m.msg is not None
        assert isinstance(m.msgtype, str) and m.msgtype


@pytest.mark.parametrize("fmt", FORMATS)
def test_reader_stamp_derivation(fixture_bags: dict[str, Path], fmt: str) -> None:
    """stamp is derived correctly across all formats (READ-04 stamp derivation).

    - All headerless ``/cmd_vel`` (Twist) records -> ``stamp is None``.
    - All header-bearing ``/imu`` and ``/image`` records -> integer ``stamp``.
    - The FIRST ``/imu`` record (lowest ``t_ns``) -> ``1_000_000_000``. The /imu
      stamps are a per-message series (``[1e9, 2.1e9, 3.2e9]``), so we assert
      only the first equals 1e9 — NOT that they are all equal.
    """
    with RosbagsReader(fixture_bags[fmt]) as reader:
        msgs = list(reader.read())

    for m in msgs:
        if m.topic == "/cmd_vel":
            assert m.stamp is None
        elif m.topic in ("/imu", "/image"):
            assert isinstance(m.stamp, int)

    imu_msgs = sorted((m for m in msgs if m.topic == "/imu"), key=lambda m: m.t_ns)
    assert imu_msgs, "no /imu records found"
    assert imu_msgs[0].stamp == FIRST_IMU_STAMP


@pytest.mark.parametrize("fmt", FORMATS)
def test_reader_topics_metadata_without_iteration(
    fixture_bags: dict[str, Path], fmt: str
) -> None:
    """topics/connections are available on an opened reader WITHOUT calling read()."""
    with RosbagsReader(fixture_bags[fmt]) as reader:
        assert set(reader.topics) == EXPECTED_TOPICS
        assert len(list(reader.connections)) >= 3


def test_read_before_open_raises(fixture_bags: dict[str, Path]) -> None:
    """Advancing ``read()`` without entering the context raises the not-opened guard.

    ``read()`` is a generator, so the guard fires when it is first advanced
    (``next``), not at construction. Matches the ``RuntimeError`` raised in 02-02.
    """
    reader = RosbagsReader(fixture_bags["ros1"])
    with pytest.raises(RuntimeError):
        next(reader.read())
