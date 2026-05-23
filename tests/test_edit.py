"""Fixture-backed round-trip tests for the same-format edit pipeline (Plan 11-01).

These prove EDIT-01's raw-copy half — trim (D-06), drop/keep (D-07), downsample
(D-08), and implicit multi-bag merge (D-09) — and the SC1 contract that every
edit output *re-opens AND deserializes* via ``rosbags.highlevel.AnyReader``,
parametrized across all three target formats (ROS 1 ``.bag``, ROS 2 sqlite3,
ROS 2 MCAP). Re-opening is NOT enough: a structurally-valid-but-semantically-
broken bag passes ``AnyReader([out]).topics`` but fails ``deserialize`` on its
headered messages (11-RESEARCH Pitfall 1/2), so the round-trip helper here
deserializes EVERY kept message of EVERY kept topic.

The fixture corpus (``tools/make_fixtures.py``) carries ``/cmd_vel`` (Twist,
headerless), ``/imu`` (Imu, header + float64[9] covariance), and ``/image``
(Image, uint8[] blob) — 3 messages each at t = 1.0 / 1.1 / 1.2 s
(``start_time`` = 1_000_000_000 ns). These exact counts/timestamps are asserted
to prove trim/downsample slice precisely.

LOCAL-RUN REQUIREMENT (02-RESEARCH.md Pitfall 5): this dev host sources ROS 2
Humble onto ``PYTHONPATH``, which can pull ROS plugins into the test process and
crash pytest on collection. Run these tests locally with the host leak
neutralized::

    PYTHONPATH="" uv run pytest tests/test_edit.py -q

CI is ROS-free, so it needs NO prefix — and this file bakes in NO ``PYTHONPATH``
override (it is a run-time prefix only, never committed code).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# `tools` is a dev-only package at the repo root (NOT an installed distribution
# like rosbagger_core / bagq), so it is not on sys.path under pytest's default
# import mode. Put the repo root on sys.path here — scoped to this test file
# (mirrors tests/test_reader.py / tests/test_backend_query.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import (  # noqa: E402  (after sys.path setup)
    make_all_fixtures,
    write_ros1_bag,
    write_ros2_mcap_bag,
    write_ros2_sqlite_bag,
)

from rosbagger_core.edit import EditOps, edit_bag  # noqa: E402

FORMATS = ("ros1", "ros2_sqlite", "ros2_mcap")
EXPECTED_TOPICS = {"/cmd_vel", "/imu", "/image"}

# Verified fixture facts (mirrors tests/test_reader.py): 3 messages per topic at
# t = 1.0 / 1.1 / 1.2 s, start_time = 1_000_000_000 ns.
_N_PER_TOPIC = 3
_START_NS = 1_000_000_000


# The destination NAME per output format. ROS 1 is a single-file ``.bag``; the two
# ROS 2 formats are directories (sqlite3) / an ``.mcap`` file selected by suffix.
def _dst_for(fmt: str, dest_dir: Path) -> Path:
    if fmt == "ros1":
        return dest_dir / "out.bag"
    if fmt == "ros2_mcap":
        return dest_dir / "out.mcap"
    return dest_dir / "out_ros2"  # ROS 2 sqlite3 directory


@pytest.fixture(scope="session")
def fixture_bags(tmp_path_factory) -> dict[str, Path]:
    """Generate all three fixture bags once into a throwaway session tmp dir."""
    dest = tmp_path_factory.mktemp("edit_bags")
    return make_all_fixtures(dest)


def _roundtrip(out: Path) -> dict[str, list]:
    """Re-open ``out`` via AnyReader and DESERIALIZE every message (SC1 / Pitfall 2).

    Returns a dict ``{topic: [t_ns, ...]}`` built ONLY after a successful
    ``deserialize`` of each message, so a bag that re-opens but cannot deserialize
    its headered messages fails here rather than masquerading as a pass.
    """
    from rosbags.highlevel import AnyReader

    per_topic: dict[str, list] = {}
    with AnyReader([out]) as reader:
        for connection, t_ns, rawdata in reader.messages():
            msg = reader.deserialize(rawdata, connection.msgtype)
            assert msg is not None  # deserialized object, not merely re-opened bytes
            per_topic.setdefault(connection.topic, []).append(t_ns)
    return per_topic


# ---------------------------------------------------------------------------
# round-trip (no-op): SC1 — re-open AND deserialize, all 3 formats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_roundtrip_noop_preserves_all(fmt, fixture_bags, tmp_path):
    """A no-op edit re-opens AND deserializes every message of every topic (SC1)."""
    src = fixture_bags[fmt]
    out = _dst_for(fmt, tmp_path)
    edit_bag([src], out, EditOps())
    per_topic = _roundtrip(out)
    assert set(per_topic) == EXPECTED_TOPICS
    for topic in EXPECTED_TOPICS:
        assert len(per_topic[topic]) == _N_PER_TOPIC


# ---------------------------------------------------------------------------
# trim (D-06): bag-relative seconds window [START, END]
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_trim_keeps_only_in_window(fmt, fixture_bags, tmp_path):
    """trim=(0.0, 0.1) keeps t=1.0s + t=1.1s (2 of 3) per topic; all deserialize."""
    src = fixture_bags[fmt]
    out = _dst_for(fmt, tmp_path)
    edit_bag([src], out, EditOps(trim=(0.0, 0.1)))
    per_topic = _roundtrip(out)
    assert set(per_topic) == EXPECTED_TOPICS
    for topic in EXPECTED_TOPICS:
        assert sorted(per_topic[topic]) == [_START_NS, _START_NS + 100_000_000]


# ---------------------------------------------------------------------------
# drop (D-07): exclude named topics, no orphan connections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_drop_excludes_topic_no_orphan(fmt, fixture_bags, tmp_path):
    """drop={'/image'} yields topic set exactly {'/cmd_vel','/imu'}; counts unchanged."""
    src = fixture_bags[fmt]
    out = _dst_for(fmt, tmp_path)
    edit_bag([src], out, EditOps(drop=frozenset({"/image"})))
    per_topic = _roundtrip(out)
    assert set(per_topic) == {"/cmd_vel", "/imu"}  # no /image, no orphan connection
    assert len(per_topic["/cmd_vel"]) == _N_PER_TOPIC
    assert len(per_topic["/imu"]) == _N_PER_TOPIC


# ---------------------------------------------------------------------------
# keep (D-07): include only named topics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_keep_includes_only_named(fmt, fixture_bags, tmp_path):
    """keep={'/cmd_vel'} yields a single topic /cmd_vel (3 msgs, all deserialize)."""
    src = fixture_bags[fmt]
    out = _dst_for(fmt, tmp_path)
    edit_bag([src], out, EditOps(keep=frozenset({"/cmd_vel"})))
    per_topic = _roundtrip(out)
    assert set(per_topic) == {"/cmd_vel"}
    assert len(per_topic["/cmd_vel"]) == _N_PER_TOPIC


# ---------------------------------------------------------------------------
# downsample (D-08): keep every Nth message per topic (deterministic)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_downsample_keeps_every_nth(fmt, fixture_bags, tmp_path):
    """downsample={'/imu':2} keeps the 0th + 2nd /imu (2 of 3); others untouched."""
    src = fixture_bags[fmt]
    out = _dst_for(fmt, tmp_path)
    edit_bag([src], out, EditOps(downsample={"/imu": 2}))
    per_topic = _roundtrip(out)
    assert set(per_topic) == EXPECTED_TOPICS
    # every-Nth with the keep-the-0th rule: indices 0,2 survive of {0,1,2}
    assert sorted(per_topic["/imu"]) == [_START_NS, _START_NS + 200_000_000]
    assert len(per_topic["/cmd_vel"]) == _N_PER_TOPIC  # untouched
    assert len(per_topic["/image"]) == _N_PER_TOPIC  # untouched


@pytest.mark.parametrize("fmt", FORMATS)
def test_downsample_all_applies_globally(fmt, fixture_bags, tmp_path):
    """A global downsample_all=2 keeps the 0th + 2nd of EVERY topic (2 of 3 each)."""
    src = fixture_bags[fmt]
    out = _dst_for(fmt, tmp_path)
    edit_bag([src], out, EditOps(downsample_all=2))
    per_topic = _roundtrip(out)
    assert set(per_topic) == EXPECTED_TOPICS
    for topic in EXPECTED_TOPICS:
        assert sorted(per_topic[topic]) == [_START_NS, _START_NS + 200_000_000]


# ---------------------------------------------------------------------------
# merge (D-09): two same-format bags -> one time-ordered output (2x count)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def two_bags(tmp_path_factory) -> dict[str, list[Path]]:
    """One same-format fixture written into TWO dirs per format (a split recording).

    Each bag dir/name collides if written into the same parent, so each lands in
    its own ``tmp_path_factory`` dir (mirrors tests/test_reader.py's merge fixture).
    """
    return {
        "ros1": [
            write_ros1_bag(tmp_path_factory.mktemp("m_ros1_a")),
            write_ros1_bag(tmp_path_factory.mktemp("m_ros1_b")),
        ],
        "ros2_sqlite": [
            write_ros2_sqlite_bag(tmp_path_factory.mktemp("m_sqlite_a")),
            write_ros2_sqlite_bag(tmp_path_factory.mktemp("m_sqlite_b")),
        ],
        "ros2_mcap": [
            write_ros2_mcap_bag(tmp_path_factory.mktemp("m_mcap_a")),
            write_ros2_mcap_bag(tmp_path_factory.mktemp("m_mcap_b")),
        ],
    }


@pytest.mark.parametrize("fmt", FORMATS)
def test_merge_two_bags_doubles_and_orders(fmt, two_bags, tmp_path):
    """Editing [bag_a, bag_b] yields 2x messages in time order; re-opens+deserializes."""
    srcs = two_bags[fmt]
    out = _dst_for(fmt, tmp_path)
    edit_bag(srcs, out, EditOps())
    per_topic = _roundtrip(out)
    assert set(per_topic) == EXPECTED_TOPICS
    total = 0
    for topic in EXPECTED_TOPICS:
        assert len(per_topic[topic]) == _N_PER_TOPIC * 2  # doubled
        # each topic's own stream is time-ordered (AnyReader merges globally)
        assert per_topic[topic] == sorted(per_topic[topic])
        total += len(per_topic[topic])
    assert total == _N_PER_TOPIC * len(EXPECTED_TOPICS) * 2  # 18


# ---------------------------------------------------------------------------
# mutual exclusion (D-07): drop + keep together -> ValueError, no bag written
# ---------------------------------------------------------------------------


def test_drop_and_keep_together_raises(tmp_path):
    """Both drop and keep non-empty raises a clear ValueError at construction.

    Because ``edit_bag`` takes an already-constructed ``EditOps``, the mutual
    exclusion (D-07) is enforced BEFORE any bag could be written — constructing
    the spec raises, so no output path is ever opened.
    """
    out = tmp_path / "should_not_exist"
    with pytest.raises(ValueError):
        EditOps(drop=frozenset({"/image"}), keep=frozenset({"/cmd_vel"}))
    assert not out.exists()  # the failed construction wrote nothing


def test_downsample_non_positive_raises():
    """A downsample N <= 0 is rejected at construction (V5 input validation)."""
    with pytest.raises(ValueError):
        EditOps(downsample={"/imu": 0})
    with pytest.raises(ValueError):
        EditOps(downsample_all=-1)


# ---------------------------------------------------------------------------
# D-05: refuse to overwrite an input path (never mutate the input)
# ---------------------------------------------------------------------------


def test_refuses_to_overwrite_input(fixture_bags):
    """edit_bag raises if the output path resolves to an input path (D-05)."""
    src = fixture_bags["ros2_sqlite"]
    with pytest.raises(ValueError):
        edit_bag([src], src, EditOps())


# ---------------------------------------------------------------------------
# format selection (D-10): explicit fmt override beats the suffix
# ---------------------------------------------------------------------------


def test_format_override_to_mcap(fixture_bags, tmp_path):
    """An explicit fmt='mcap' writes a ROS 2 MCAP bag regardless of the dest name."""
    src = fixture_bags["ros2_sqlite"]
    out = tmp_path / "override_out"  # no .mcap suffix; fmt should win
    edit_bag([src], out, EditOps(), fmt="mcap")
    per_topic = _roundtrip(out)
    assert set(per_topic) == EXPECTED_TOPICS
    # The output is a ROS 2 bag dir containing an .mcap file (MCAP storage chosen).
    assert any(p.suffix == ".mcap" for p in out.iterdir())


# ---------------------------------------------------------------------------
# empty result (Open Q2 LOCKED): write an empty bag + report 0 (no silent no-op)
# ---------------------------------------------------------------------------


def test_trim_window_outside_writes_empty_bag(fixture_bags, tmp_path):
    """A trim window past the bag end writes a valid EMPTY bag and reports 0 (Open Q2)."""
    src = fixture_bags["ros2_sqlite"]
    out = tmp_path / "empty_out"
    written = edit_bag([src], out, EditOps(trim=(100.0, 200.0)))
    assert written == 0  # reported count, not a silent no-op
    per_topic = _roundtrip(out)  # still a re-openable bag
    assert per_topic == {}


# ---------------------------------------------------------------------------
# convert (D-04 cross-format half): ROS1 <-> ROS2 via the rosbags converter
# factory. The load-bearing assertion is that the headered /imu + /image
# messages DESERIALIZE after convert (Pitfall 1/2) — a naive byte path opens but
# crashes deserializing them (the ROS1 Header.seq field ROS2 dropped). Both
# directions are tested across the ROS2 sqlite + MCAP destination formats.
# ---------------------------------------------------------------------------


def test_convert_ros1_to_ros2_sqlite_deserializes_headered(fixture_bags, tmp_path):
    """convert ROS1 -> ROS2 sqlite: every topic re-opens AND deserializes (SC1)."""
    src = fixture_bags["ros1"]
    out = tmp_path / "ros1_to_ros2_sqlite"  # directory dst -> ROS2 sqlite3
    written = edit_bag([src], out, EditOps())
    assert written == _N_PER_TOPIC * len(EXPECTED_TOPICS)  # 9 = 3 topics x 3 msgs
    per_topic = _roundtrip(out)  # _roundtrip DESERIALIZES every message (Pitfall 2)
    assert set(per_topic) == EXPECTED_TOPICS
    for topic in EXPECTED_TOPICS:
        assert len(per_topic[topic]) == _N_PER_TOPIC


def test_convert_ros1_to_ros2_mcap_deserializes_headered(fixture_bags, tmp_path):
    """convert ROS1 -> ROS2 MCAP: headered /imu + /image deserialize after convert."""
    src = fixture_bags["ros1"]
    out = tmp_path / "out.mcap"  # .mcap dst -> ROS2 MCAP
    edit_bag([src], out, EditOps())
    per_topic = _roundtrip(out)
    assert set(per_topic) == EXPECTED_TOPICS
    for topic in EXPECTED_TOPICS:
        assert len(per_topic[topic]) == _N_PER_TOPIC


def test_convert_ros2_sqlite_to_ros1_deserializes_headered(fixture_bags, tmp_path):
    """convert ROS2 sqlite -> ROS1 .bag: the seq-field direction the naive path crashes on.

    This is Pitfall 1's hard case — a ROS2 message has no ``Header.seq``, so a
    byte-level convert writes a .bag that re-opens but raises deserializing /imu +
    /image. The factory's ``migrate_bytes`` fills the missing ``seq`` from a default
    message, so ``_roundtrip`` (which deserializes every message) succeeds.
    """
    src = fixture_bags["ros2_sqlite"]
    out = tmp_path / "out.bag"  # .bag dst -> ROS1
    edit_bag([src], out, EditOps())
    per_topic = _roundtrip(out)
    assert set(per_topic) == EXPECTED_TOPICS
    for topic in EXPECTED_TOPICS:
        assert len(per_topic[topic]) == _N_PER_TOPIC


def test_convert_ros2_mcap_to_ros1_deserializes_headered(fixture_bags, tmp_path):
    """convert ROS2 MCAP -> ROS1 .bag: the other ROS2 source format, same seq case."""
    src = fixture_bags["ros2_mcap"]
    out = tmp_path / "out.bag"
    edit_bag([src], out, EditOps())
    per_topic = _roundtrip(out)
    assert set(per_topic) == EXPECTED_TOPICS
    for topic in EXPECTED_TOPICS:
        assert len(per_topic[topic]) == _N_PER_TOPIC


def test_convert_composes_with_drop_filter(fixture_bags, tmp_path):
    """convert + drop in ONE pass (D-10): ROS1 -> ROS2 dropping /image.

    Proves the filter and the cross-format conversion compose in a single
    read->write loop — the output is ROS2, carries only /cmd_vel + /imu, and both
    deserialize (the headered /imu survives the convert).
    """
    src = fixture_bags["ros1"]
    out = tmp_path / "convert_drop_ros2"  # ROS2 sqlite3 dir
    edit_bag([src], out, EditOps(drop=frozenset({"/image"})))
    per_topic = _roundtrip(out)
    assert set(per_topic) == {"/cmd_vel", "/imu"}  # /image dropped, no orphan
    assert len(per_topic["/cmd_vel"]) == _N_PER_TOPIC
    assert len(per_topic["/imu"]) == _N_PER_TOPIC


# ---------------------------------------------------------------------------
# raw-copy (D-04 split): same-wireformat targets do NOT engage migration.
# ROS2-sqlite3 -> MCAP and ROS1 -> ROS1 are both byte-identical copies. We
# assert the bytes are UNCHANGED for at least one message (the convert factory
# returns the memoryview identity when is_same_wireformat AND src_is2==dst_is2).
# ---------------------------------------------------------------------------


def _first_raw(path: Path, topic: str) -> bytes:
    """Read the first raw payload of ``topic`` from ``path`` (no deserialize)."""
    from rosbags.highlevel import AnyReader

    with AnyReader([path]) as reader:
        for connection, _t_ns, rawdata in reader.messages():
            if connection.topic == topic:
                return bytes(rawdata)
    raise AssertionError(f"topic {topic} not found in {path}")


def test_raw_copy_ros2_sqlite_to_mcap_is_byte_identical(fixture_bags, tmp_path):
    """ROS2 sqlite3 -> MCAP stays raw-copy (both CDR): the /imu bytes are unchanged."""
    src = fixture_bags["ros2_sqlite"]
    out = tmp_path / "raw_out.mcap"
    edit_bag([src], out, EditOps())
    per_topic = _roundtrip(out)
    assert set(per_topic) == EXPECTED_TOPICS
    # Same wireformat (CDR both sides) -> the converter is the identity, so the
    # raw bytes survive untouched (pins the D-04 raw-copy branch).
    assert _first_raw(out, "/imu") == _first_raw(src, "/imu")


def test_raw_copy_ros1_to_ros1_is_byte_identical(fixture_bags, tmp_path):
    """ROS1 -> ROS1 stays raw-copy (no migration): the /imu bytes are unchanged."""
    src = fixture_bags["ros1"]
    out = tmp_path / "raw_out.bag"
    edit_bag([src], out, EditOps())
    per_topic = _roundtrip(out)
    assert set(per_topic) == EXPECTED_TOPICS
    assert _first_raw(out, "/imu") == _first_raw(src, "/imu")
