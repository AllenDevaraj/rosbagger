"""ROS type-system -> Apache Arrow type-system translator (QURY-03 type side, QURY-07).

The pure-translation half of Phase 3: it maps the ``rosbags`` field-type AST
(``typestore.get_msgdef(msgtype).fields`` -> ``Nodetype`` ``FieldDesc`` tuples)
onto ``pyarrow`` ``DataType`` objects, and decides which fields are *heavy byte
blobs* (lazily excluded by default — QURY-07). The recursive name-flattening walk
that turns a whole message into a ``TableSchema`` lives in ``flatten.py`` and
calls into here for each leaf's type.

This module is the project's core contribution: a lookup table from the verified
ROS ``Basename`` vocabulary to ``pa.DataType`` plus a small AST translator. Both
type systems are mature — resist re-implementing definition parsing.

The ``Nodetype`` ``FieldDesc`` shapes (VERIFIED against ``rosbags`` 0.11.2 this
session — research Pattern 1 / §2, re-confirmed against the project fixtures):

* ``(Nodetype.BASE,     (basename, bound))``        — a scalar; ``basename`` is a
  ``ROS_BASE_TO_ARROW`` key (e.g. ``'float64'``).
* ``(Nodetype.NAME,     "pkg/msg/Type")``           — a sub-message; the payload
  is the **type-name string itself** (NOT a 1-tuple), used in a ``LIST`` context
  to build a ``pa.struct``. Verified: ``('linear', (Nodetype.NAME,
  'geometry_msgs/msg/Vector3'))``.
* ``(Nodetype.ARRAY,    (inner_FieldDesc, length))``   — a fixed-length array.
* ``(Nodetype.SEQUENCE, (inner_FieldDesc, bound))``    — a variable-length array
  (``bound=0`` = unbounded).

Offline note: importing ``pyarrow`` here is SAFE — it is not a ROS module and the
offline guard only blocks ``rclpy``/``rosbag2_py``/``rosidl_runtime_py``/
``ament_index_python``. ``rosbagger_core/__init__`` does NOT import this
subpackage at top level, so ``import rosbagger_core`` stays light. Do NOT
``import duckdb`` here — that is Phase 5.
"""

from __future__ import annotations

import pyarrow as pa
from rosbags.interfaces import Nodetype

# ROS Basename -> pyarrow scalar DataType (the verified vocabulary; RESEARCH §3).
# Transcribed verbatim from the VERIFIED Arrow->DuckDB round-trip:
#   uint32 -> UINTEGER, uint64 -> UBIGINT (no overflow at max), float64 -> DOUBLE,
#   string -> VARCHAR, timestamp('ns') -> TIMESTAMP_NS.
# ROS 'byte'/'char' are single octets -> uint8 (matches rosbags deserialization,
# which returns uint8[] for Image.data). 'wstring'/'float128' are vanishingly
# rare in real bags (no fixture exercises them; Assumptions A1/A2) — 'wstring' is
# treated as a UTF-8 string and 'float128' is omitted (Arrow has no float128;
# add a lossy down-map only if a real bag ever surfaces one).
ROS_BASE_TO_ARROW: dict[str, pa.DataType] = {
    "bool": pa.bool_(),
    "byte": pa.uint8(),  # ROS 'byte' == octet
    "char": pa.uint8(),  # ROS 'char' == uint8 (single octet)
    "int8": pa.int8(),
    "int16": pa.int16(),
    "int32": pa.int32(),
    "int64": pa.int64(),
    "uint8": pa.uint8(),
    "uint16": pa.uint16(),
    "uint32": pa.uint32(),  # -> DuckDB UINTEGER
    "uint64": pa.uint64(),  # -> DuckDB UBIGINT (VERIFIED no overflow at max)
    "float32": pa.float32(),
    "float64": pa.float64(),  # -> DuckDB DOUBLE
    "string": pa.string(),  # -> DuckDB VARCHAR
    "wstring": pa.string(),  # rare; treat as UTF-8 string (Assumption A1)
}

# The byte-blob element basenames: a SEQUENCE of one of these is a heavy blob.
_BLOB_BASENAMES = ("uint8", "byte", "char")


def _name_payload(payload: object) -> str:
    """Extract the sub-message type name from a ``Nodetype.NAME`` payload.

    VERIFIED: ``rosbags`` 0.11.2 stores the payload as the bare type-name string
    (``'geometry_msgs/msg/Vector3'``). We accept a 1-tuple shape defensively (the
    research §3 snippet wrote ``payload[0]``) so a future packaging change can't
    silently break the walk, but the bare-string form is the observed reality.
    """
    if isinstance(payload, str):
        return payload
    return payload[0]  # tolerate a (name, ...) tuple wrapper, just in case


def arrow_type_of(ftype, typestore) -> tuple[pa.DataType, bool]:
    """Translate one ``FieldDesc`` to ``(pyarrow.DataType, is_heavy_blob)``.

    Transcribed from the VERIFIED research §3 translator:

    * ``BASE``     -> ``(ROS_BASE_TO_ARROW[basename], False)``.
    * ``NAME``     -> ``(pa.struct([(field, type), ...]), False)`` built by
      recursing over the sub-message's declared fields, keeping the inner field
      names SHORT (Pitfall 4 — only the top-level path is dotted; a struct's own
      members stay ``x``/``child_frame_id``, never ``linear.x``). Used only inside
      a ``LIST`` context (an unwrapped sub-message is flattened by the
      ``flatten.py`` walk, never resolved here).
    * ``ARRAY``/``SEQUENCE`` -> ``(pa.list_(elem), heavy)`` where ``elem`` is the
      inner element's Arrow type and ``heavy`` is ``True`` ONLY when the node is a
      ``SEQUENCE`` whose inner element is a ``BASE`` in ``{uint8, byte, char}``
      (the structural heavy-byte-blob signal — QURY-07).

    Args:
        ftype: a ``Nodetype`` ``FieldDesc`` tuple ``(nodetype, payload)``.
        typestore: the ``rosbags`` ``Typestore`` (for ``get_msgdef`` recursion on
            ``NAME`` sub-messages).

    Returns:
        ``(arrow_type, is_heavy_blob)``. ``is_heavy_blob`` is ``True`` only for a
        ``SEQUENCE`` of bytes; everything else (including a fixed ``float64[9]``
        covariance ``ARRAY``) is ``False``.

    Raises:
        ValueError: on an unknown ``Nodetype`` (defensive — the enum has exactly
            four members).
    """
    nt, payload = ftype
    if nt == Nodetype.BASE:
        return ROS_BASE_TO_ARROW[payload[0]], False
    if nt == Nodetype.NAME:  # sub-message in a LIST context -> struct (short names)
        submsgtype = _name_payload(payload)
        fields = [
            (fname, arrow_type_of(ft, typestore)[0])
            for fname, ft in typestore.get_msgdef(submsgtype).fields
        ]
        return pa.struct(fields), False
    if nt in (Nodetype.ARRAY, Nodetype.SEQUENCE):  # fixed or variable -> LIST
        inner, _bound = payload
        elem, _ = arrow_type_of(inner, typestore)
        heavy = (
            nt == Nodetype.SEQUENCE and inner[0] == Nodetype.BASE and inner[1][0] in _BLOB_BASENAMES
        )
        return pa.list_(elem), heavy
    raise ValueError(f"unknown Nodetype {nt!r}")


def is_heavy_blob(ftype) -> bool:
    """Return ``True`` iff ``ftype`` is a heavy byte blob (QURY-07).

    A *structural* predicate (RESEARCH §6, Pattern 5), NOT a name blocklist: a
    field is heavy iff it is a variable-length ``SEQUENCE`` whose element is a
    ``BASE`` in ``{uint8, byte, char}``. VERIFIED to flag ``Image.data`` /
    ``PointCloud2.data`` / ``CompressedImage.data`` while NOT flagging
    ``Imu.orientation_covariance`` (a fixed ``float64[9]`` ``ARRAY`` — Pitfall 3)
    or ``std_msgs/msg/String.data`` (a scalar ``BASE`` string). A name blocklist
    would be brittle (``String.data`` is a scalar; a custom blob might be named
    ``payload``); the ``SEQUENCE``-of-byte structure is the real signal.
    """
    nt, payload = ftype
    if nt == Nodetype.SEQUENCE:
        inner, _bound = payload
        return inner[0] == Nodetype.BASE and inner[1][0] in _BLOB_BASENAMES
    return False
