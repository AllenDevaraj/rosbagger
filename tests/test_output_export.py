"""Behavior tests for CSV / Parquet export via DuckDB COPY (OUT-02 / OUT-03).

These build a REAL result table (open a fixture bag, run Phase 5's ``query()``), write
it with ``rosbagger_core.output.write_table``, then READ THE FILE BACK and assert the
header/rows. The ``/imu`` fixture contributes the LIST column
``orientation_covariance`` (the regression for 06-RESEARCH Pitfall 2: pyarrow's CSV
writer raises ``ArrowInvalid`` on LIST — DuckDB ``COPY`` renders it as a bracketed
string); ``/cmd_vel`` the scalar / empty cases.

LOCAL-RUN REQUIREMENT (06-RESEARCH.md): this dev host sources ROS 2 onto ``PYTHONPATH``;
run locally with the leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_output_export.py -q

CI is ROS-free and needs no prefix; this file bakes in NO ``PYTHONPATH`` override.
"""

from __future__ import annotations

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
from rosbagger_core.output import write_table  # noqa: E402
from rosbagger_core.reader import RosbagsReader  # noqa: E402


@pytest.fixture(scope="session")
def ros1_bag(tmp_path_factory) -> Path:
    """A single ROS 1 fixture bag (cmd_vel/imu/image) for building result tables."""
    return write_ros1_bag(tmp_path_factory.mktemp("output_export_bag"))


def _query(bag: Path, sql: str):
    """Run ``sql`` over ``bag`` and return the result ``pyarrow.Table``."""
    with RosbagsReader([bag]) as reader:
        return query(sql, reader)


def test_write_csv_header_and_bracketed_list_cell(ros1_bag: Path, tmp_path: Path) -> None:
    """``write_table(..., out.csv)`` writes a header + a bracketed LIST cell (no ArrowInvalid).

    Pitfall 2: ``orientation_covariance`` is a LIST column. pyarrow's CSV writer would
    raise ``ArrowInvalid``; DuckDB ``COPY`` renders it as ``"[...]"``.
    """
    table = _query(ros1_bag, 'SELECT t_ns, topic, "orientation_covariance" FROM imu')
    out = tmp_path / "imu.csv"
    write_table(table, str(out))
    assert out.exists()
    text = out.read_text()
    lines = text.splitlines()
    # Header line is the comma-joined column names.
    assert lines[0] == "t_ns,topic,orientation_covariance"
    assert len(lines) == 1 + table.num_rows  # header + one line per row
    # The LIST column rendered as a bracketed string somewhere in the body (not a crash).
    # Do NOT assert exact float formatting — only the bracket structure.
    assert "[" in text and "]" in text


def test_write_parquet_roundtrips_schema_and_rows(ros1_bag: Path, tmp_path: Path) -> None:
    """``write_table(..., out.parquet)`` round-trips column names + num_rows via read_table."""
    import pyarrow.parquet as pq

    table = _query(ros1_bag, 'SELECT t, t_ns, topic, "orientation_covariance" FROM imu')
    out = tmp_path / "imu.parquet"
    write_table(table, str(out))
    assert out.exists()
    back = pq.read_table(str(out))
    assert back.column_names == table.column_names
    assert back.num_rows == table.num_rows == 3


def test_write_csv_zero_rows_is_header_only(ros1_bag: Path, tmp_path: Path) -> None:
    """A 0-row result writes a header-only CSV (Pitfall 3)."""
    table = _query(ros1_bag, "SELECT t, t_ns, topic FROM cmd_vel WHERE 1=0")
    out = tmp_path / "empty.csv"
    write_table(table, str(out))
    lines = out.read_text().splitlines()
    assert lines == ["t,t_ns,topic"]  # header only, no data rows


def test_write_parquet_zero_rows_preserves_schema(ros1_bag: Path, tmp_path: Path) -> None:
    """A 0-row result writes a 0-row Parquet whose schema is preserved (Pitfall 3)."""
    import pyarrow.parquet as pq

    table = _query(ros1_bag, "SELECT t, t_ns, topic FROM cmd_vel WHERE 1=0")
    out = tmp_path / "empty.parquet"
    write_table(table, str(out))
    back = pq.read_table(str(out))
    assert back.num_rows == 0
    assert back.column_names == ["t", "t_ns", "topic"]


def test_write_unknown_extension_raises_valueerror(ros1_bag: Path, tmp_path: Path) -> None:
    """An unknown extension raises ValueError naming the supported extensions."""
    table = _query(ros1_bag, "SELECT t_ns, topic FROM cmd_vel")
    with pytest.raises(ValueError, match=r"\.csv or \.parquet"):
        write_table(table, str(tmp_path / "out.txt"))


def test_write_csv_escapes_single_quote_in_path(ros1_bag: Path, tmp_path: Path) -> None:
    """A path containing a single quote is escaped, not a COPY injection (T-06-01).

    The file is written to the literal quoted name; a naive interpolation would break
    the ``COPY ... TO '<path>'`` statement.
    """
    table = _query(ros1_bag, "SELECT t_ns, topic FROM cmd_vel")
    out = tmp_path / "o'ut.csv"
    write_table(table, str(out))
    assert out.exists()
    assert out.read_text().splitlines()[0] == "t_ns,topic"
