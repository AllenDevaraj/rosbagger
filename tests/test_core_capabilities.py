"""Tests for ``rosbagger_core.capabilities`` — the shared runtime-capability probes (R6/T7)."""

from __future__ import annotations

from rosbagger_core.capabilities import module_importable


def test_module_importable_true_for_a_real_module() -> None:
    """A real, importable module probes True (R6)."""
    assert module_importable("json") is True


def test_module_importable_false_for_an_absent_module() -> None:
    """A module that does not exist probes False (ImportError → False, never a raise) — R6."""
    assert module_importable("rosbagger_definitely_not_a_real_module_xyz") is False
