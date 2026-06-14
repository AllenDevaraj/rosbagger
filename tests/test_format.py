"""Unit tests for rosbagger_core.format (R2/R3 — the shared human-readable formatters).

These pin the canonical behavior the three faces (bagq, Textual GUI, PySide6 desktop) now
share, including the fix for the bagq `_human_size` drift that capped at GB.

LOCAL-RUN: stdlib-only; run with `PYTHONPATH=""` on a ROS-equipped host (02-RESEARCH Pitfall 5).
"""

from __future__ import annotations

import pytest

from rosbagger_core.format import human_dur, human_size


@pytest.mark.parametrize(
    ("num_bytes", "expected"),
    [
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1024**2 + 1024**2 // 2, "1.5 MB"),
        (2 * 1024**3, "2.0 GB"),
        (2 * 1024**4, "2.0 TB"),  # the drift fix: bagq used to print "2048.0 GB" here
        (3 * 1024**5, "3.0 PB"),
    ],
)
def test_human_size(num_bytes: int, expected: str) -> None:
    assert human_size(num_bytes) == expected


def test_human_size_no_longer_caps_at_gb() -> None:
    """A 2 TiB bag prints in TB, not thousands of GB (the bagq drift this dedup fixed)."""
    assert human_size(2 * 1024**4) == "2.0 TB"
    assert "GB" not in human_size(2 * 1024**4)


@pytest.mark.parametrize(
    ("ns", "expected"),
    [
        (0, "0ms"),
        (800_000_000, "800ms"),  # the seeded TF dropout
        (1_500_000, "1.5ms"),
        (1_000_000_000, "1.00s"),
        (12_400_000_000, "12.40s"),
    ],
)
def test_human_dur(ns: int, expected: str) -> None:
    assert human_dur(ns) == expected
