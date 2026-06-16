"""Fixture-backed proof of Phase 9's three TF Success Criteria (TF-01), no ROS install.

These tests exercise the whole TF stack — ``rosbagger_core.tf.collect_tf_report`` (the
graph build + dropout detection) and the thin ``bagq tf`` rich renderer — against the
09-01 ``write_tf_bag`` fixture, which seeds a deterministic ~800ms ``odom→base_link``
publish gap (omitted ticks 8..14 of 24), a clean ``base_link→laser`` edge, and a latched
static ``map→odom``:

* **SC1 (graph)** — ``/tf`` + ``/tf_static`` load and build the parent→child graph:
  frames ``{map, odom, base_link, laser}``; ``map→odom`` static, ``odom→base_link`` /
  ``base_link→laser`` dynamic — proven on ALL THREE formats (ROS 1, ROS 2 sqlite3,
  ROS 2 MCAP).
* **SC2 (gaps)** — per-edge dropouts with bag-relative timestamps: exactly one ~800ms
  gap on ``odom→base_link``, zero on the clean edge, NONE on the static edge — across
  all three formats; plus the ``--gap-ms`` / ``--gap-multiplier`` knobs and the
  ``at_rel_ns == at_ns - start_ns`` relation.
* **SC3 (offline)** — the suite runs on rosbags fixtures with no ROS install (CI is
  ROS-free; ``tests/test_offline_guard.py`` separately proves ``import rosbagger_core.tf``
  pulls no ROS), and ``bagq tf`` prints the edge/gap tables.

LOCAL-RUN REQUIREMENT (MEMORY.md / 09-RESEARCH): this dev host sources ROS 2 Humble onto
``PYTHONPATH``, which crashes a bare ``uv run pytest`` on collection. Run locally with
the host leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_tf.py -q

CI is ROS-free, so it needs NO prefix — and this file bakes in NO ``PYTHONPATH`` override
(it is a run-time prefix only, never committed code).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# `tools` is a dev-only repo-root package (NOT an installed distribution), so it is not
# on sys.path under pytest's default import mode. Put the repo root on sys.path here,
# scoped to this file (mirrors tests/test_reader.py), touching neither tests/conftest.py
# nor the root pyproject.toml.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import make_all_fixtures, write_tf_bag  # noqa: E402  (after sys.path)

from bagq.cli import app  # noqa: E402  (3rd-party, after sys.path)
from rosbagger_core.errors import NoTransformsError  # noqa: E402
from rosbagger_core.reader import RosbagsReader  # noqa: E402
from rosbagger_core.tf import collect_tf_report  # noqa: E402

# The three target formats: ROS 1 `.bag`, ROS 2 sqlite3, ROS 2 MCAP. `storage` is ignored
# when ros1=True. The SC1/SC2 tests parametrize over this so SC3 exercises all three.
FORMATS = [(True, "sqlite3"), (False, "sqlite3"), (False, "mcap")]
_LABELS = {
    (True, "sqlite3"): "ros1",
    (False, "sqlite3"): "ros2_sqlite",
    (False, "mcap"): "ros2_mcap",
}

EXPECTED_FRAMES = {"map", "odom", "base_link", "laser"}
SEEDED_GAP_NS = 800_000_000  # the omitted-ticks dropout on odom->base_link
DT_NS = 100_000_000  # the regular publish interval (the median expected_ns)

runner = CliRunner()


@pytest.fixture(scope="session")
def tf_bags(tmp_path_factory) -> dict[str, Path]:
    """Write one TF fixture bag per format into its OWN session tmp subdir.

    Each bag gets a distinct directory (mirroring the test_reader convention) keyed by a
    label — "ros1" / "ros2_sqlite" / "ros2_mcap" — so the three formats never collide.
    """
    root = tmp_path_factory.mktemp("tf_bags")
    bags: dict[str, Path] = {}
    for ros1, storage in FORMATS:
        label = _LABELS[(ros1, storage)]
        bags[label] = write_tf_bag(root / label, ros1=ros1, storage=storage)
    return bags


@pytest.fixture(scope="session")
def non_tf_bag(tmp_path_factory) -> Path:
    """A bag with NO TF topics (the /cmd_vel,/imu,/image fixture) for the empty case."""
    return make_all_fixtures(tmp_path_factory.mktemp("non_tf_bag"))["ros1"]


# ---------------------------------------------------------------------------
# SC1 — the transform graph (parametrized over all three formats)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label", ["ros1", "ros2_sqlite", "ros2_mcap"])
def test_sc1_graph_frames_and_static_dynamic_edges(tf_bags: dict[str, Path], label: str) -> None:
    """SC1: frames + parent→child edges, static vs dynamic, on every format."""
    with RosbagsReader(tf_bags[label]) as reader:
        report = collect_tf_report(reader)

    assert report.frames == EXPECTED_FRAMES

    by_key = {(e.parent, e.child): e for e in report.edges}
    # The static map->odom edge is present and tagged static.
    assert ("map", "odom") in by_key
    assert by_key[("map", "odom")].static is True
    # The two dynamic edges are present and tagged NOT static.
    assert ("odom", "base_link") in by_key
    assert by_key[("odom", "base_link")].static is False
    assert ("base_link", "laser") in by_key
    assert by_key[("base_link", "laser")].static is False


# ---------------------------------------------------------------------------
# SC2 — per-edge dropouts (parametrized over all three formats)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label", ["ros1", "ros2_sqlite", "ros2_mcap"])
def test_sc2_gaps_one_800ms_dropout_clean_and_static_edges(
    tf_bags: dict[str, Path], label: str
) -> None:
    """SC2: exactly one ~800ms odom->base_link gap; clean + static edges have none."""
    with RosbagsReader(tf_bags[label]) as reader:
        report = collect_tf_report(reader)

    odom_gaps = [g for g in report.gaps if (g.parent, g.child) == ("odom", "base_link")]
    assert len(odom_gaps) == 1
    gap = odom_gaps[0]
    assert abs(gap.gap_ns - SEEDED_GAP_NS) <= 1
    assert gap.expected_ns == DT_NS

    # The clean edge has zero gaps.
    assert [g for g in report.gaps if (g.parent, g.child) == ("base_link", "laser")] == []
    # The static edge produces NO gap (Decision 5 / Pitfall 4 — never gap-checked).
    assert [g for g in report.gaps if (g.parent, g.child) == ("map", "odom")] == []
    by_key = {(e.parent, e.child): e for e in report.edges}
    assert by_key[("base_link", "laser")].gap_count == 0
    assert by_key[("map", "odom")].gap_count == 0


def test_sc2_boundary_no_synthetic_gap_and_bag_relative_clock(tf_bags: dict[str, Path]) -> None:
    """SC2 boundaries (ros2_sqlite): no synthetic start/end gap; at_rel == at - start (A4 / D3)."""
    with RosbagsReader(tf_bags["ros2_sqlite"]) as reader:
        report = collect_tf_report(reader)

    by_key = {(e.parent, e.child): e for e in report.edges}
    # The clean edge spans well inside the bag yet reports 0 gaps — no synthetic gap is
    # emitted before its first sample or after its last (A4).
    assert by_key[("base_link", "laser")].gap_count == 0

    # Every gap's bag-relative clock is exactly at_ns - start_ns (Decision 3).
    assert report.start_ns is not None
    assert report.gaps  # the seeded dropout exists
    for g in report.gaps:
        assert g.at_rel_ns == g.at_ns - report.start_ns


# ---------------------------------------------------------------------------
# Algorithm knobs (ros2_sqlite) — both Decision 6 thresholds wired through
# ---------------------------------------------------------------------------


def test_gap_ms_override_flags_dropout(tf_bags: dict[str, Path]) -> None:
    """A tiny --gap-ms (~3x DT in ms) still flags the seeded dropout (absolute override)."""
    gap_ms = 3 * DT_NS / 1e6  # 300.0 ms — below the 800ms dropout, above the 100ms cadence
    with RosbagsReader(tf_bags["ros2_sqlite"]) as reader:
        report = collect_tf_report(reader, gap_ms=gap_ms)
    assert any((g.parent, g.child) == ("odom", "base_link") for g in report.gaps)


def test_gap_ms_overrides_multiplier_suppresses_subthreshold_dropout(
    tf_bags: dict[str, Path],
) -> None:
    """--gap-ms OVERRIDES the multiplier: a gap_ms ABOVE the seeded dropout suppresses it.

    Regression for the audit bug: the threshold ORed gap_ms with the median multiplier
    instead of overriding it, so raising --gap-ms above the 800ms dropout still reported it
    (the 8x-median delta tripped the multiplier branch) — contradicting the CLI help that
    --gap-ms "overrides the multiplier". With true override, gap_ms=1000ms (> the 800ms
    dropout) reports NO odom->base_link gap. This is the regime where OR and override
    DIVERGE; the shipped override test uses gap_ms BELOW the multiplier, where they coincide.
    """
    gap_ms = 1000.0  # 1s — above the 800ms dropout AND above the 500ms (5x100ms) multiplier
    with RosbagsReader(tf_bags["ros2_sqlite"]) as reader:
        report = collect_tf_report(reader, gap_ms=gap_ms)
    odom_gaps = [g for g in report.gaps if (g.parent, g.child) == ("odom", "base_link")]
    assert odom_gaps == [], f"gap_ms=1000ms must override the multiplier; got {odom_gaps}"
    by_key = {(e.parent, e.child): e for e in report.edges}
    assert by_key[("odom", "base_link")].gap_count == 0


def test_large_gap_multiplier_suppresses_dropout(tf_bags: dict[str, Path]) -> None:
    """A very large --gap-multiplier (100x) does NOT flag the seeded dropout."""
    with RosbagsReader(tf_bags["ros2_sqlite"]) as reader:
        report = collect_tf_report(reader, gap_multiplier=100.0)
    # 8x-median dropout < 100x-median threshold -> not a gap.
    assert report.gaps == []
    by_key = {(e.parent, e.child): e for e in report.edges}
    assert by_key[("odom", "base_link")].gap_count == 0


# ---------------------------------------------------------------------------
# Empty case — NoTransformsError on a bag with no TF topics
# ---------------------------------------------------------------------------


def test_no_transforms_error_on_non_tf_bag(non_tf_bag: Path) -> None:
    """collect_tf_report raises NoTransformsError naming /tf + listing available topics."""
    with RosbagsReader(non_tf_bag) as reader, pytest.raises(NoTransformsError) as excinfo:
        collect_tf_report(reader)
    msg = str(excinfo.value)
    assert "/tf" in msg
    # The error carries the bag's available topics and names at least one in the message.
    assert excinfo.value.available  # non-empty
    assert "/cmd_vel" in msg


# ---------------------------------------------------------------------------
# Single-sample edge coverage — a duck-typed reader (no real bag needed)
# ---------------------------------------------------------------------------


def test_single_sample_edge_is_informational_not_a_gap() -> None:
    """A one-publish dynamic edge: samples==1, no inferable rate, zero gaps (covers the skip).

    Uses a minimal duck-typed reader stub (mirroring the inspect-test stubs) so the
    single-sample branch is exercised without a bespoke fixture bag.
    """

    class _TF:
        def __init__(self, parent: str, child: str) -> None:
            self.header = type("H", (), {"frame_id": parent})()
            self.child_frame_id = child

    class _Msg:
        def __init__(self, topic: str, t_ns: int, transforms: list) -> None:
            self.topic = topic
            self.t_ns = t_ns
            self.msg = type("M", (), {"transforms": transforms})()

    class _StubReader:
        topics = {"/tf": object()}
        start_time = 1_000_000_000
        end_time = 1_000_000_000

        def read(self, *, topics=None):  # noqa: ARG002 - duck-typed signature
            yield _Msg("/tf", 1_000_000_000, [_TF("odom", "base_link")])

    report = collect_tf_report(_StubReader())
    by_key = {(e.parent, e.child): e for e in report.edges}
    edge = by_key[("odom", "base_link")]
    assert edge.samples == 1
    assert edge.expected_ns is None
    assert edge.max_gap_ns is None
    assert edge.gap_count == 0
    assert report.gaps == []


def test_all_duplicate_timestamps_no_false_gap_no_zerodivision() -> None:
    """An edge whose every publish shares ONE log time drops all deltas: no gap, no crash (T-09-03).

    With several publishes at the IDENTICAL log time, every inter-arrival delta is 0 and
    is dropped before the median (which is therefore never taken over an empty list) — the
    edge is informational (``expected_ns is None``, 0 gaps), never a ZeroDivision or a
    false dropout. Exercises the all-duplicate defensive branch.
    """

    class _TF:
        def __init__(self, parent: str, child: str) -> None:
            self.header = type("H", (), {"frame_id": parent})()
            self.child_frame_id = child

    class _Msg:
        def __init__(self, topic: str, t_ns: int, transforms: list) -> None:
            self.topic = topic
            self.t_ns = t_ns
            self.msg = type("M", (), {"transforms": transforms})()

    class _StubReader:
        topics = {"/tf": object()}
        start_time = 1_000_000_000
        end_time = 1_000_000_000

        def read(self, *, topics=None):  # noqa: ARG002 - duck-typed signature
            # Four publishes at the IDENTICAL log time -> every delta is 0 -> diffs empty.
            for _ in range(4):
                yield _Msg("/tf", 1_000_000_000, [_TF("odom", "base_link")])

    report = collect_tf_report(_StubReader())
    by_key = {(e.parent, e.child): e for e in report.edges}
    edge = by_key[("odom", "base_link")]
    assert edge.samples == 4
    assert edge.expected_ns is None  # no positive delta -> no inferable rate
    assert edge.max_gap_ns is None
    assert edge.gap_count == 0
    assert report.gaps == []


# ---------------------------------------------------------------------------
# CLI tests (selectable via `-k cli`) — the bagq tf renderer + json + no-TF error
# ---------------------------------------------------------------------------


def test_cli_tf_table_shows_gap_row_and_sections(tf_bags: dict[str, Path]) -> None:
    """bagq tf prints the edge/gap tables incl. the 'odom → base_link' 800ms dropout row."""
    bag = tf_bags["ros2_sqlite"]
    result = runner.invoke(app, ["tf", str(bag)])
    assert result.exit_code == 0, result.output
    assert "TF edges" in result.stdout
    assert "TF gaps" in result.stdout
    assert "odom → base_link" in result.stdout
    assert "800ms" in result.stdout


def test_cli_tf_format_json_emits_frames_and_gap(tf_bags: dict[str, Path]) -> None:
    """bagq tf --format json exits 0 and emits the frames + the gap (machine-readable)."""
    bag = tf_bags["ros2_sqlite"]
    result = runner.invoke(app, ["tf", str(bag), "--format", "json"])
    assert result.exit_code == 0, result.output
    assert "odom" in result.stdout
    # The JSON parses and carries the frames + at least one gap.
    payload = json.loads(result.stdout)
    assert set(payload["frames"]) == EXPECTED_FRAMES
    assert any(g["parent"] == "odom" and g["child"] == "base_link" for g in payload["gaps"])


def test_cli_tf_no_transforms_exits_one_cleanly(non_tf_bag: Path) -> None:
    """bagq tf on a non-TF bag exits 1 as a clean SystemExit (no traceback)."""
    result = runner.invoke(app, ["tf", str(non_tf_bag)])
    assert result.exit_code == 1
    # A clean typer.Exit(1) surfaces to CliRunner as SystemExit (07-RESEARCH §6), NOT the
    # raw NoTransformsError — i.e. no domain-error traceback leaked (T-09-08).
    assert isinstance(result.exception, SystemExit)
    assert not isinstance(result.exception, NoTransformsError)
    assert "no /tf" in (result.output or "")


def test_cli_tf_clean_bag_reports_no_gaps(tf_bags: dict[str, Path]) -> None:
    """bagq tf with a large multiplier prints 'no gaps detected' (the empty-timeline branch)."""
    bag = tf_bags["ros2_sqlite"]
    result = runner.invoke(app, ["tf", str(bag), "--gap-multiplier", "100"])
    assert result.exit_code == 0, result.output
    assert "TF edges" in result.stdout
    assert "no gaps detected" in result.stdout


def test_cli_tf_bad_format_is_rejected(tf_bags: dict[str, Path]) -> None:
    """bagq tf --format bogus errors (typer.BadParameter), mirroring query's guard."""
    bag = tf_bags["ros2_sqlite"]
    result = runner.invoke(app, ["tf", str(bag), "--format", "bogus"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# newA7 — a /tf topic carrying a non-TFMessage type teaches, not tracebacks.
# ---------------------------------------------------------------------------


def test_collect_tf_report_rejects_non_tfmessage_topic(tmp_path: Path) -> None:
    """A `/tf` carrying std_msgs/msg/String raises NonTfMessageError, not AttributeError.

    The analyzer matches `/tf` by name then reads `msg.transforms`; a non-TFMessage
    payload has no such attribute, so without the metadata guard it raised a raw
    AttributeError mid-stream. The guard rejects it from O(1) topic metadata.
    """
    from tools.make_fixtures import write_wrong_type_tf_bag

    from rosbagger_core.errors import NonTfMessageError

    bag = write_wrong_type_tf_bag(tmp_path)
    with RosbagsReader(bag) as reader, pytest.raises(NonTfMessageError) as excinfo:
        collect_tf_report(reader)
    assert excinfo.value.topic == "/tf"
    assert "std_msgs/msg/String" in str(excinfo.value)


def test_bagq_tf_wrong_type_is_clean_error(tmp_path: Path) -> None:
    """`bagq tf` on a wrong-typed /tf prints a clean teaching line, no traceback (newA7)."""
    from tools.make_fixtures import write_wrong_type_tf_bag

    bag = write_wrong_type_tf_bag(tmp_path)
    result = CliRunner().invoke(app, ["tf", str(bag)])
    assert result.exit_code == 1
    assert not isinstance(result.exception, AttributeError)
    assert "not tf2_msgs/msg/TFMessage" in result.output


# ---------------------------------------------------------------------------
# newA8 — an empty (registered-but-zero-message) /tf bag yields None bounds.
# ---------------------------------------------------------------------------


def test_collect_tf_report_empty_bag_has_no_garbage_bounds(tmp_path: Path) -> None:
    """A registered-but-empty /tf bag yields None start/end, not AnyReader sentinels (newA8).

    When message_count == 0 the underlying AnyReader returns 2**63-1 / 0 time sentinels;
    those are ints, so the isinstance(int) guard could not catch them and JSON emitted
    start_ns=9223372036854775807. The analyzer now mirrors inspect.collect_bag_info's
    count==0 guard and reports None bounds.
    """
    from tools.make_fixtures import write_empty_tf_bag

    bag = write_empty_tf_bag(tmp_path)
    with RosbagsReader(bag) as reader:
        report = collect_tf_report(reader)
    assert report.start_ns is None
    assert report.end_ns is None
    assert report.edges == []
    assert report.gaps == []


def test_bagq_tf_json_empty_bag_emits_null_bounds(tmp_path: Path) -> None:
    """`bagq tf --format json` on an empty /tf bag emits null bounds, no 2**63-1 (newA8)."""
    from tools.make_fixtures import write_empty_tf_bag

    bag = write_empty_tf_bag(tmp_path)
    result = CliRunner().invoke(app, ["tf", str(bag), "--format", "json"])
    assert result.exit_code == 0
    assert "9223372036854775807" not in result.output
    payload = json.loads(result.output)
    assert payload["start_ns"] is None
    assert payload["end_ns"] is None
