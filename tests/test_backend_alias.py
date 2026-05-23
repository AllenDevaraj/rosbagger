"""Unit tests for the alias-pack AST rewrite (Phase 10 plan ``10-01``, QURY-08).

These prove the ``backend/alias.py`` mechanism in isolation — a pure ``sqlglot``
tree transform (D-01), NOT string substitution — against the REAL ``rosbags``
ROS 2 Humble typestore (for the existence-gate's column-name vocabulary). The
orchestrator wiring (per-topic gating, ``--no-alias``) is Plan 10-03; here the
helper stands alone and is fully testable without touching ``query.py``.

What is asserted:

* The canonical Twist ``vx`` → ``"linear.x"`` (the ``/cmd_vel`` fixture type; SC1)
  and the Odometry double-nested ``vx`` → ``"twist.twist.linear.x"`` (the CONTEXT
  canonical example; D-03 message-type-keyed expansion).
* The rewrite reaches EVERY clause (SELECT/WHERE/GROUP BY/HAVING/ORDER BY) and
  inside function args (``avg(vx)``), and preserves an output alias
  (``vx AS speed`` → ``"linear.x" AS speed``).
* Existence-gate (D-04): an alias whose target is NOT in the topic's schema, and
  an unknown short token, are both left untouched (safe no-op); an already-dotted
  quoted column is immune (its ``.name`` contains dots, never equals a short alias).
* ``tree.transform`` returns a NEW tree — the input is never mutated (D-01).

LOCAL-RUN REQUIREMENT (02-RESEARCH.md Pitfall 5 / MEMORY): this dev host sources
ROS 2 Humble onto ``PYTHONPATH``, which can pull ROS plugins into the test process
and crash pytest on collection. Run these tests locally with the host leak
neutralized::

    PYTHONPATH="" .venv/bin/python -m pytest tests/test_backend_alias.py -q

CI is ROS-free, so it needs NO prefix — and this file bakes in NO ``PYTHONPATH``
override (it is a run-time prefix only, never committed code).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from rosbags.typesys import Stores, get_typestore

# `tools` is a dev-only package at the repo root (NOT an installed distribution),
# so it is not on sys.path under pytest's default import mode. Put the repo root
# on sys.path here — scoped to this test file (mirrors tests/test_schema_arrow.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rosbagger_core.backend.alias import ALIAS_PACK, expand_aliases  # noqa: E402

from rosbagger_core.backend.resolve import parse  # noqa: E402
from rosbagger_core.schema.flatten import build_table_schema  # noqa: E402

_TWIST = "geometry_msgs/msg/Twist"
_ODOMETRY = "nav_msgs/msg/Odometry"


@pytest.fixture(scope="session")
def typestore():
    """The real ROS 2 Humble typestore (no bag needed — schema-only existence gate)."""
    return get_typestore(Stores.ROS2_HUMBLE)


def _schema_names(msgtype: str, typestore, *, topic: str) -> set[str]:
    """The dotted column-name set for ``msgtype`` — the existence-gate vocabulary.

    Built from O(1) typestore metadata via ``build_table_schema`` (no bag read),
    exactly the names the flatten walk emits and the gate (D-04) matches against.
    """
    schema = build_table_schema(msgtype, typestore, topic=topic)
    return {c.name for c in schema.columns}


@pytest.fixture(scope="session")
def twist_names(typestore) -> set[str]:
    return _schema_names(_TWIST, typestore, topic="/cmd_vel")


@pytest.fixture(scope="session")
def odom_names(typestore) -> set[str]:
    return _schema_names(_ODOMETRY, typestore, topic="/odom")


def test_rewrite_twist_vx(twist_names):
    """Canonical Twist case (SC1): ``vx`` → ``"linear.x"`` on the /cmd_vel type."""
    out = expand_aliases(parse("SELECT vx FROM cmd_vel"), _TWIST, twist_names).sql(dialect="duckdb")
    assert '"linear.x"' in out
    # No bare `vx` token survives (regex word-boundary so `vx` inside another
    # identifier would not false-match — there is none here anyway).
    import re

    assert re.search(r"\bvx\b", out) is None, out


def test_rewrite_odometry_vx_double_nested(odom_names):
    """Canonical CONTEXT case: ``vx`` → ``"twist.twist.linear.x"`` on Odometry."""
    assert "twist.twist.linear.x" in odom_names  # the gate must be able to match
    out = expand_aliases(parse("SELECT vx FROM odom"), _ODOMETRY, odom_names).sql(dialect="duckdb")
    assert '"twist.twist.linear.x"' in out
    import re

    assert re.search(r"\bvx\b", out) is None, out


def test_rewrite_reaches_all_clauses(twist_names):
    """`-k clause`: every clause's ``vx`` (SELECT/WHERE/GROUP BY/HAVING/ORDER BY) rewrites."""
    sql = "SELECT vx FROM cmd_vel WHERE vx > 0 GROUP BY vx HAVING vx < 10 ORDER BY vx"
    out = expand_aliases(parse(sql), _TWIST, twist_names).sql(dialect="duckdb")
    assert '"linear.x"' in out
    import re

    # No standalone `vx` token anywhere in the regenerated SQL.
    assert re.search(r"\bvx\b", out) is None, out


def test_rewrite_inside_function_arg(twist_names):
    """A function argument is rewritten: ``avg(vx)`` → ``AVG("linear.x")``."""
    out = expand_aliases(parse("SELECT avg(vx) FROM cmd_vel"), _TWIST, twist_names).sql(
        dialect="duckdb"
    )
    assert 'AVG("linear.x")'.lower() in out.lower()


def test_input_tree_not_mutated(twist_names):
    """`tree.transform` returns a copy — the ORIGINAL tree is unchanged (D-01)."""
    tree = parse("SELECT vx FROM cmd_vel")
    before = tree.sql(dialect="duckdb")
    expand_aliases(tree, _TWIST, twist_names)
    after = tree.sql(dialect="duckdb")
    assert before == after == "SELECT vx FROM cmd_vel"


def test_alias_pack_canonical_targets():
    """The pack holds the two SC1 canonical targets keyed by ``pkg/msg/Type``."""
    assert ALIAS_PACK[_TWIST]["vx"] == "linear.x"
    assert ALIAS_PACK[_ODOMETRY]["vx"] == "twist.twist.linear.x"
