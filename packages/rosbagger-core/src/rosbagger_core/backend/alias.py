"""Built-in alias pack + the ``sqlglot``-AST rewrite that expands it (QURY-08).

This is the "make the SQL terser" half of the query orchestrator: a built-in
mapping from ROS message type → ``{short alias → full dotted column}`` plus one
``tree.transform`` that rewrites each matching short column into the quoted dotted
target. It lets a user write ``SELECT vx FROM cmd_vel`` instead of
``SELECT "linear.x" FROM cmd_vel`` (Twist) or ``SELECT "twist.twist.linear.x"
FROM odom`` (Odometry) — the SAME alias resolves to the correct dotted path *per
message type* (D-03), because Twist's velocity is the shallow ``linear.x`` while
Odometry's is the double-nested ``twist.twist.linear.x``.

Mechanism (D-01): a pure ``sqlglot`` AST transform, NOT string substitution and
NOT a DuckDB view. Each unqualified short ``exp.Column`` whose name is an alias in
the topic's pack — AND whose dotted target EXISTS in that topic's schema (D-04
existence-gate) — is replaced by ``exp.column(target, quoted=True)``. The
replacement is built ONLY through ``sqlglot`` (which escapes embedded quotes), so
no raw string is ever interpolated into the SQL — preserving the trusted-SQL
boundary (threat T-05-04 / T-10-01) and reusing the identifier-quoting discipline
of ``schema/identifiers.py`` (T-03-06). A regex was rejected in Phase 5 ("Don't
Hand-Roll" — breaks on CTE/JOIN/quoting); the same reasoning forbids
string-rewriting here.

Why the existence-gate matters: an alias whose target is not in the FROM topic's
schema is left untouched (a safe no-op — DuckDB then raises the normal teaching
error). An already-dotted quoted column like ``"linear.x"`` is immune: it parses
to ``.name == "linear.x"``, which CONTAINS dots and so never equals a short alias
key like ``vx`` (10-RESEARCH Code Example 3). An output alias is also immune:
``vx AS speed`` parses ``vx`` as ``exp.Column`` and ``speed`` as ``exp.Alias``, and
this rewrite matches only ``exp.Column`` — so the user's chosen output name is
never mangled (Pitfall 1).

This module is per-msgtype / per-schema. The orchestrator (Plan 10-03) owns the
single-base-topic guard for multi-topic / JOIN / CTE queries (10-RESEARCH Open
Q1) — this helper does NOT implement JOIN scoping; tree-wide expansion is safe
because the existence-gate makes a non-resolving short token a no-op.

Offline note: ``from sqlglot import exp`` at module level here is SAFE — ``sqlglot``
is a pure-Python locked dependency, NOT a ROS module (mirrors ``backend/resolve.py``
and ``schema/identifiers.py``). This module imports NO ``pyarrow``/``duckdb`` and
nothing from ``rosbagger_core`` itself, so ``import rosbagger_core.backend.alias``
pulls in NEITHER the heavy data stack NOR ROS (offline-guard invariant —
``tests/test_offline_guard.py``). ``backend/__init__`` adds no eager import, so the
subpackage import stays light.
"""

from __future__ import annotations

from sqlglot import exp

# The built-in alias pack (D-05 — a curated, NON-user-extensible v1 set).
#
# Keyed by the canonical ``pkg/msg/Type`` string (``rosbags`` normalizes ROS 1
# msgtypes to this one form — A2; ``_normalize`` is defensive insurance). Each
# value maps a short alias to the EXACT dotted column the flatten walk emits, so
# the existence-gate (D-04) matches against ``TableSchema`` column names. Every
# dotted target below was produced by ``build_table_schema(msgtype, ROS2_HUMBLE,
# topic=...)`` (10-RESEARCH § "Alias Pack v1 Contents", VERIFIED).
#
# The alias *spellings* (``vx``/``wz``/``ax``/``px``/``qw`` …) are author's
# discretion (D-05 / A1); the dotted *targets* are verified. Note ``wx``/``wy``/
# ``wz`` mean angular VELOCITY for Imu (``angular_velocity.*``) but angular twist
# for Twist (``angular.*``) — the per-type keying (D-03) is exactly why a single
# flat global pack was rejected.
ALIAS_PACK: dict[str, dict[str, str]] = {
    # Bare Twist (no header, no wrapper) — the shallowest. The /cmd_vel fixture.
    "geometry_msgs/msg/Twist": {
        "vx": "linear.x",
        "vy": "linear.y",
        "vz": "linear.z",
        "wx": "angular.x",
        "wy": "angular.y",
        "wz": "angular.z",
    },
    # One wrapper level (``twist.``) — proves message-type-keyed expansion (D-03).
    "geometry_msgs/msg/TwistStamped": {
        "vx": "twist.linear.x",
        "vy": "twist.linear.y",
        "vz": "twist.linear.z",
        "wx": "twist.angular.x",
        "wy": "twist.angular.y",
        "wz": "twist.angular.z",
    },
    # Double-nested (``twist.twist.`` / ``pose.pose.``) — the canonical SC1 case.
    "nav_msgs/msg/Odometry": {
        "vx": "twist.twist.linear.x",
        "vy": "twist.twist.linear.y",
        "vz": "twist.twist.linear.z",
        "wx": "twist.twist.angular.x",
        "wy": "twist.twist.angular.y",
        "wz": "twist.twist.angular.z",
        "px": "pose.pose.position.x",
        "py": "pose.pose.position.y",
        "pz": "pose.pose.position.z",
        "qx": "pose.pose.orientation.x",
        "qy": "pose.pose.orientation.y",
        "qz": "pose.pose.orientation.z",
        "qw": "pose.pose.orientation.w",
    },
    # Imu: ``wx/wy/wz`` here are angular VELOCITY (vs Twist's angular). /imu fixture.
    "sensor_msgs/msg/Imu": {
        "ax": "linear_acceleration.x",
        "ay": "linear_acceleration.y",
        "az": "linear_acceleration.z",
        "wx": "angular_velocity.x",
        "wy": "angular_velocity.y",
        "wz": "angular_velocity.z",
        "qx": "orientation.x",
        "qy": "orientation.y",
        "qz": "orientation.z",
        "qw": "orientation.w",
    },
    # One wrapper (``pose.``).
    "geometry_msgs/msg/PoseStamped": {
        "px": "pose.position.x",
        "py": "pose.position.y",
        "pz": "pose.position.z",
        "qx": "pose.orientation.x",
        "qy": "pose.orientation.y",
        "qz": "pose.orientation.z",
        "qw": "pose.orientation.w",
    },
    # Bare pose (no header).
    "geometry_msgs/msg/Pose": {
        "px": "position.x",
        "py": "position.y",
        "pz": "position.z",
        "qx": "orientation.x",
        "qy": "orientation.y",
        "qz": "orientation.z",
        "qw": "orientation.w",
    },
}


def _normalize(msgtype: str) -> str:
    """Return ``msgtype`` in the canonical ``pkg/msg/Type`` form the pack keys on.

    ``rosbags`` ``AnyReader`` already normalizes ROS 1 msgtypes to ``pkg/msg/Type``
    (A2, VERIFIED for the fixture types), so the common path is the identity. This
    is cheap defensive insurance for an exotic ``pkg/Type`` form: split on ``/`` and
    insert ``msg`` between package and type. Anything that does not look like a
    two- or three-segment slash path is returned unchanged (a non-match in the pack
    is a harmless no-op via the existence-gate).
    """
    if "/msg/" in msgtype:
        return msgtype
    parts = msgtype.split("/")
    if len(parts) == 2:
        return f"{parts[0]}/msg/{parts[1]}"
    return msgtype


def expand_aliases(tree: exp.Expression, msgtype: str, schema_names: set[str]) -> exp.Expression:
    """Expand pack aliases in ``tree`` for ``msgtype``, gated on ``schema_names``.

    Returns a NEW tree (``tree.transform`` copies — the input is never mutated;
    D-01 / Anti-Pattern). Each unqualified short ``exp.Column`` whose ``.name`` is
    an alias in ``msgtype``'s pack AND whose dotted target is in ``schema_names``
    (D-04 existence-gate) is replaced by ``exp.column(target, quoted=True)`` — a
    quoted dotted identifier built solely through ``sqlglot`` (no f-string / no raw
    substitution; threat T-10-01). Every other node — unknown short tokens,
    aliases whose target is absent from the schema, already-dotted quoted columns,
    qualified columns, and output ``exp.Alias`` nodes — is returned unchanged.

    The rewrite reaches every clause (SELECT/WHERE/GROUP BY/HAVING/ORDER BY) and
    function arguments, because ``transform`` walks the whole tree. When
    ``msgtype`` is not in the pack the pack lookup yields ``{}`` and the transform
    is a whole-tree no-op.
    """
    pack = ALIAS_PACK.get(_normalize(msgtype), {})

    def _rewrite(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Column) and not node.table and node.name in pack:
            target = pack[node.name]
            if target in schema_names:  # D-04 existence-gate
                return exp.column(target, quoted=True)
        return node

    return tree.transform(_rewrite)
