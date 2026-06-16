"""Behavior tests for the temporal-safe row coercion (OUT-01 / --format json).

These exercise ``rosbagger_core.output.render`` against REAL result tables built by
opening a fixture bag with ``RosbagsReader`` and running Phase 5's ``query()`` — so the
``timestamp[ns]`` ``t``/``stamp`` columns are genuine (regression for 06-RESEARCH
Pitfall 1: naive ``to_pylist()``/``str()`` on a nanosecond timestamp raises
``ValueError``). The ``/imu`` fixture supplies the temporal + LIST columns; ``/cmd_vel``
the scalar / empty cases.

LOCAL-RUN REQUIREMENT (06-RESEARCH.md): this dev host sources ROS 2 onto ``PYTHONPATH``;
run locally with the leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_output_render.py -q

CI is ROS-free and needs no prefix; this file bakes in NO ``PYTHONPATH`` override.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# `tools` is a dev-only repo-root package; put the repo root on sys.path here,
# scoped to this file (mirrors tests/test_cli_tables.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import write_ros1_bag  # noqa: E402  (after sys.path setup)

from rosbagger_core.backend.query import query  # noqa: E402
from rosbagger_core.output import rows_for_display, to_json  # noqa: E402
from rosbagger_core.reader import RosbagsReader  # noqa: E402


@pytest.fixture(scope="session")
def ros1_bag(tmp_path_factory) -> Path:
    """A single ROS 1 fixture bag (cmd_vel/imu/image) for building result tables."""
    return write_ros1_bag(tmp_path_factory.mktemp("output_render_bag"))


def _query(bag: Path, sql: str):
    """Run ``sql`` over ``bag`` and return the result ``pyarrow.Table``."""
    with RosbagsReader([bag]) as reader:
        return query(sql, reader)


def test_rows_for_display_coerces_timestamp_ns_without_valueerror(ros1_bag: Path) -> None:
    """A result with the timestamp[ns] t/stamp columns renders to strings, no ValueError.

    Pitfall 1: ``t`` is timestamp[ns]; ``str()``/``to_pylist()`` on it raises. The
    renderer must convert temporal columns via ``to_numpy`` first.
    """
    table = _query(ros1_bag, 'SELECT t, t_ns, topic, "orientation_covariance" FROM imu')
    names, rows = rows_for_display(table)
    assert names == ["t", "t_ns", "topic", "orientation_covariance"]
    assert len(rows) == table.num_rows == 3
    # The temporal `t` column rendered to a non-empty datetime string (not "" / NaT).
    assert rows[0][0] and rows[0][0] != "NaT"
    # Every cell is a string (full coercion happened).
    assert all(isinstance(cell, str) for row in rows for cell in row)


def test_rows_for_display_max_rows_caps_rows_keeps_all_columns(ros1_bag: Path) -> None:
    """``max_rows=N`` on an M>N table returns exactly N rows and the full column list."""
    table = _query(ros1_bag, "SELECT t, t_ns, topic FROM imu")
    assert table.num_rows == 3
    names, rows = rows_for_display(table, max_rows=2)
    assert names == ["t", "t_ns", "topic"]
    assert len(rows) == 2  # capped, not 3


def test_rows_for_display_zero_rows_returns_columns_and_empty_rows(ros1_bag: Path) -> None:
    """A 0-row result returns the column names and an empty rows list (no index error)."""
    table = _query(ros1_bag, "SELECT t, t_ns, topic FROM cmd_vel WHERE 1=0")
    assert table.num_rows == 0
    names, rows = rows_for_display(table)
    assert names == ["t", "t_ns", "topic"]
    assert rows == []


def test_to_json_emits_temporal_as_raw_int64_ns(ros1_bag: Path) -> None:
    """``to_json`` casts t/stamp to int64 raw-ns (machine-parseable; no ValueError)."""
    table = _query(ros1_bag, "SELECT t, t_ns, topic FROM imu")
    payload = json.loads(to_json(table))
    assert isinstance(payload, list) and len(payload) == 3
    first = payload[0]
    assert set(first) == {"t", "t_ns", "topic"}
    # t (timestamp[ns]) is emitted as an int (raw ns), equal to t_ns for the same row.
    assert isinstance(first["t"], int)
    assert first["t"] == first["t_ns"]


def test_to_json_zero_rows_is_empty_list(ros1_bag: Path) -> None:
    """A 0-row result serializes to an empty JSON list."""
    table = _query(ros1_bag, "SELECT t, t_ns, topic FROM cmd_vel WHERE 1=0")
    assert json.loads(to_json(table)) == []


def test_to_json_sanitizes_non_finite_floats_to_null() -> None:
    """NaN / +/-inf serialize to JSON null so the output is STRICTLY parseable.

    Regression for the audit bug: json.dumps defaults to allow_nan=True, emitting bare
    NaN / Infinity / -Infinity tokens that strict parsers (JS JSON.parse, Go) reject —
    breaking the machine-parseable contract. LaserScan ranges (inf) and Imu/Odometry
    covariance (NaN) are common. Covers scalar, LIST, and LIST-of-STRUCT leaves.
    (Built directly in pyarrow — no query needed to inject non-finite floats.)
    """
    import pyarrow as pa

    table = pa.table(
        {
            "scalar": pa.array([1.5, float("nan"), float("inf"), float("-inf")], pa.float64()),
            "ranges": pa.array(
                [[1.0, float("inf")], [float("nan"), 2.0], [], None], pa.list_(pa.float64())
            ),
            "poses": pa.array(
                [[{"x": float("nan")}], [{"x": 3.0}], None, []],
                pa.list_(pa.struct([("x", pa.float64())])),
            ),
        }
    )
    raw = to_json(table)
    # json.loads ACCEPTS NaN/Infinity, so it cannot prove validity — assert on the raw
    # text: a strict parser would reject these tokens, so they must be absent.
    assert "NaN" not in raw and "Infinity" not in raw, raw
    payload = json.loads(raw)
    assert payload[0]["scalar"] == 1.5
    assert payload[1]["scalar"] is None  # NaN  -> null
    assert payload[2]["scalar"] is None  # inf  -> null
    assert payload[3]["scalar"] is None  # -inf -> null
    # LIST: inner non-finite floats sanitized; finite kept; empty list / null row preserved.
    assert payload[0]["ranges"] == [1.0, None]
    assert payload[1]["ranges"] == [None, 2.0]
    assert payload[2]["ranges"] == []
    assert payload[3]["ranges"] is None
    # LIST-of-STRUCT: the nested struct float is sanitized too (dict recursion).
    assert payload[0]["poses"] == [{"x": None}]
    assert payload[1]["poses"] == [{"x": 3.0}]
