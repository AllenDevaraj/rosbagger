"""The API-first TF analysis layer — transform graph + dropout detection (TF-01).

Design decision 1 (API-first): the ``bagq tf`` capability lives here, in
``rosbagger-core``, NOT in the CLI. :func:`collect_tf_report` streams ``/tf`` +
``/tf_static`` off an OPEN reader, builds the parent->child transform graph and a
per-edge publish-time series, detects per-edge publish *gaps* (dropouts) via a
median-inter-arrival x configurable-multiplier threshold, and returns a frozen
:class:`TfReport`. The CLI (Plan 03) is a thin renderer over these dataclasses.

Why the reader stream and NOT the Phase 5 query layer (Decision 2 / 09-RESEARCH
Pitfall 3): the schema layer flattens ``/tf`` into a SINGLE ``transforms``
LIST-of-STRUCT column (one bag row = one ``TFMessage`` = a *list* of transforms);
per-edge gap analysis over that needs ``UNNEST`` + struct digging in SQL — strictly
worse than walking the connection-filtered, already-deserialized reader stream.

OFFLINE INVARIANT (09-RESEARCH Pitfall 5): this module imports ONLY the standard
library (``dataclasses``, ``statistics``) and is NEVER imported by
``rosbagger_core/__init__`` — import it explicitly at call sites
(``from rosbagger_core.tf import collect_tf_report``), the same discipline the
``reader`` / ``schema`` / ``inspect`` modules follow. Crucially it consumes a
PASSED-IN open reader and so imports no ``rosbags`` itself; the reader already
yields deserialized objects, so there is no ``rosbags`` / ``duckdb`` / ``sqlglot``
/ ``pyarrow`` import here. ``import rosbagger_core`` stays light;
``tests/test_offline_guard.py`` (extended in Plan 03) enforces that
``import rosbagger_core.tf`` pulls none of the heavy stack.

Unlike ``inspect.collect_bag_info`` (O(1) metadata, never reads), the TF analyzer
MUST stream ``reader.read()`` — it needs every TF message to time each edge. It
does not list-materialize the whole stream needlessly; it keeps only the int
timestamps and the ``(parent, child)`` string keys, never the message bodies, so a
hostile bag's NaN/inf transform numerics and huge payloads never reach the gap math
(threats T-09-05 / T-09-06).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

# Standard TF topic names (Decision 4 / 09-RESEARCH A3): match by TOPIC NAME, not by
# msgtype string, so the ``tf2_msgs/TFMessage`` vs ``tf2_msgs/msg/TFMessage`` spelling
# variance never matters and a future ``--tf-topic`` override is a one-line change.
_TOPIC_TF = "/tf"
_TOPIC_TF_STATIC = "/tf_static"

# Accepted ``TFMessage`` msgtype spellings (newA7). Matching is by TOPIC NAME (above), but
# a present TF topic carrying a NON-TFMessage type is rejected before the stream walk so
# ``m.msg.transforms`` never raises a raw ``AttributeError``. ``rosbags`` normalizes both
# the ROS 1 (``tf2_msgs/TFMessage``) and ROS 2 (``tf2_msgs/msg/TFMessage``) names — accept
# both so a legitimate TF topic is never falsely rejected.
_TFMESSAGE_TYPES = frozenset({"tf2_msgs/msg/TFMessage", "tf2_msgs/TFMessage"})

# Default dropout threshold (Decision 6 / 09-RESEARCH A1): a delta is a gap when it
# exceeds 5x the edge's median inter-arrival interval. Median (not mean) resists the
# very gaps being detected; 5x tolerates healthy jitter without false positives.
_DEFAULT_GAP_MULTIPLIER = 5.0

_NS_PER_MS = 1_000_000


@dataclass(frozen=True, slots=True)
class GapReport:
    """One detected publish gap (dropout) on a dynamic edge — the TF-01 deliverable.

    A gap is the interval between two CONSECUTIVE observed samples of an edge that
    exceeds the threshold; gaps are between OBSERVED samples only (Decision 6 / A4),
    never synthesized from the bag start to the first sample or from the last sample
    to the bag end.

    Fields:
        parent: The parent frame (``header.frame_id``).
        child: The child frame (``child_frame_id``).
        gap_ns: The gap duration in nanoseconds (the offending inter-arrival delta).
        at_ns: Absolute log time (ns) of the sample that BEGINS the gap (the earlier
            of the two consecutive samples).
        at_rel_ns: Bag-relative start of the gap (``at_ns - start_ns``) for the CLI's
            "at t=12.4s" display (Decision 3). Falls back to ``at_ns`` if the bag
            start is unknown.
        at_rel_s: ``at_rel_ns`` in seconds (convenience for the renderer).
        expected_ns: The median inter-arrival interval this gap was measured against.
    """

    parent: str
    child: str
    gap_ns: int
    at_ns: int
    at_rel_ns: int
    at_rel_s: float
    expected_ns: int


@dataclass(frozen=True, slots=True)
class EdgeReport:
    """One row of the per-edge summary table (``bagq tf``).

    Fields:
        parent: The parent frame (``header.frame_id``).
        child: The child frame (``child_frame_id``).
        static: ``True`` when the edge was seen on ``/tf_static`` (latched; never
            gap-checked). MIXED tie-break (Decision 5 / 09-RESEARCH edge case): an
            edge seen on BOTH ``/tf`` and ``/tf_static`` is marked ``static`` here
            (it IS a static edge in the graph) yet is still gap-checked — presence on
            ``/tf`` makes it gap-checkable.
        samples: The edge's publish count (length of its time series). ``samples == 1``
            is informational ("edge seen only once"), NOT a dropout.
        first_ns: Log time (ns) of the edge's first observed sample.
        last_ns: Log time (ns) of the edge's last observed sample.
        expected_ns: The median inter-arrival interval, or ``None`` for a static /
            single-sample edge (or an all-duplicate-timestamp edge) where no rate is
            inferable.
        max_gap_ns: The largest detected gap on this edge, or ``None`` when none was
            detected (or the edge was never gap-checked).
        gap_count: How many gaps were detected on this edge (``0`` for static /
            single-sample / clean edges).
    """

    parent: str
    child: str
    static: bool
    samples: int
    first_ns: int
    last_ns: int
    expected_ns: int | None
    max_gap_ns: int | None
    gap_count: int


@dataclass(frozen=True, slots=True)
class TfReport:
    """Whole-bag TF analysis returned by :func:`collect_tf_report`.

    Fields:
        frames: Every frame that appears as a parent OR a child (``parents`` ∪
            ``children``).
        edges: One :class:`EdgeReport` per ``(parent, child)`` edge, sorted by
            ``(parent, child)``.
        gaps: Every detected :class:`GapReport`, sorted by ``at_ns`` (the TF-01
            deliverable — the dropout timeline).
        start_ns: The whole-bag earliest log time (ns), or ``None`` if unknown.
        end_ns: The whole-bag latest log time (ns), or ``None`` if unknown.
    """

    frames: frozenset[str]
    edges: list[EdgeReport]
    gaps: list[GapReport]
    start_ns: int | None
    end_ns: int | None


def collect_tf_report(
    reader,
    *,
    gap_multiplier: float = _DEFAULT_GAP_MULTIPLIER,
    gap_ms: float | None = None,
) -> TfReport:
    """Stream ``/tf`` + ``/tf_static`` off an OPEN reader; build the graph + detect gaps.

    Walks ``reader.read(topics={"/tf", "/tf_static"})`` (a connection-level filter —
    only those topics are deserialized), keying each ``TransformStamped`` by
    ``(header.frame_id, child_frame_id)`` and timing it by ``m.t_ns`` (the log time;
    ``TFMessage`` has no top-level header, so ``Message.stamp`` is ``None`` for
    ``/tf`` — Decision 3 / 09-RESEARCH Pitfall 2). Edges seen on ``/tf_static`` are
    tagged static by SOURCE TOPIC (Decision 4), never by msgtype.

    Per-edge gap detection (Decision 6 / 09-RESEARCH algorithm — every edge case
    guarded):

    * STATIC SKIP — an edge seen ONLY on ``/tf_static`` is latched (one publish is
      correct); it contributes to the graph but is never gap-checked. A MIXED edge
      (seen on both ``/tf`` and ``/tf_static``) is marked static yet still gap-checked
      (presence on ``/tf`` makes it gap-checkable).
    * ZERO/SINGLE-SAMPLE SKIP — ``len(times) < 2`` cannot infer a rate; emit no gaps,
      record informationally (``samples`` carries the count).
    * DELTAS — sort the per-edge times defensively (a multi-bag / clock-skew read may
      not be strictly monotonic per edge), then drop any ``<= 0`` inter-arrival delta
      (duplicate / backwards stamps) BEFORE the median, so they never zero it
      (threat T-09-03).
    * EXPECTED — ``statistics.median(diffs)``; an ``expected <= 0`` (all-duplicate
      timestamps) short-circuits the gap math (no ZeroDivision, no false gap).
    * THRESHOLD — a delta ``d`` is a gap when ``d > gap_multiplier * expected`` OR,
      when ``gap_ms`` is given, ``d > gap_ms * 1e6`` (an absolute-ns override). The
      default uses the multiplier.
    * BOUNDARY — gaps are between OBSERVED samples only (A4); no synthetic gap from
      the bag start to the first sample or from the last sample to the bag end.

    Args:
        reader: An ALREADY-OPEN ``BagReader`` (this function never opens a bag — the
            reader is the seam; mirrors ``query()`` / ``inspect`` taking a reader).
        gap_multiplier: Gaps fire above this multiple of the edge's median interval
            (default ``5.0``).
        gap_ms: Optional absolute gap threshold in MILLISECONDS; when set, a delta
            above ``gap_ms`` ms is a gap regardless of the multiplier (the CLI exposes
            this as ``--gap-ms`` in Plan 03).

    Returns:
        A frozen :class:`TfReport` (frames, per-edge summary, gap timeline, bounds).

    Raises:
        NoTransformsError: When ``reader.topics`` contains neither ``/tf`` nor
            ``/tf_static`` — there is no transform graph to build (Decision 7). The
            guard reads ``reader.topics`` (O(1) metadata), NOT the stream.
    """
    from rosbagger_core.errors import NonTfMessageError, NoTransformsError

    # 1. EMPTY-TOPIC GUARD FIRST (Decision 7). Read the O(1) topic metadata — do NOT
    #    walk the stream to discover this. If neither standard TF topic is present
    #    there is nothing to analyze; teach with the bag's available topics.
    topic_names = set(reader.topics.keys())
    if _TOPIC_TF not in topic_names and _TOPIC_TF_STATIC not in topic_names:
        raise NoTransformsError(sorted(topic_names))

    # 1b. MSGTYPE GUARD (newA7). The name guard above is not enough — a remap mistake or a
    #     republisher can put a non-TFMessage type on /tf, and `m.msg.transforms` would then
    #     raise a raw AttributeError mid-stream (a traceback, not a teaching error). Reject a
    #     PRESENT TF topic whose msgtype is a known non-TFMessage type, from O(1) metadata,
    #     before the walk. A msgtype of None (a mixed-type topic) is left alone here — the
    #     per-message body is what would matter and that is a separate, rarer case.
    for tf_topic in (_TOPIC_TF, _TOPIC_TF_STATIC):
        info = reader.topics.get(tf_topic)
        # `getattr` (not `info.msgtype`): a missing/None msgtype means "type unknown" — do
        # NOT reject it as wrong-type, only reject a KNOWN non-TFMessage type.
        msgtype = getattr(info, "msgtype", None) if info is not None else None
        if msgtype is not None and msgtype not in _TFMESSAGE_TYPES:
            raise NonTfMessageError(tf_topic, msgtype)

    # 2. STREAM WALK. Connection-filtered: only /tf + /tf_static are deserialized.
    #    Tag static by TOPIC NAME (Decision 4). Key edges by (parent, child) so a
    #    parent==child self-edge or a child with two parents stays a DISTINCT series
    #    rather than silently merging into another edge's stats (threat T-09-07).
    edge_times: dict[tuple[str, str], list[int]] = {}
    static_keys: set[tuple[str, str]] = set()
    dynamic_keys: set[tuple[str, str]] = set()
    frames: set[str] = set()
    for m in reader.read(topics={_TOPIC_TF, _TOPIC_TF_STATIC}):
        is_static = m.topic == _TOPIC_TF_STATIC
        # An empty `transforms` list (threat T-09-05) simply contributes no edges —
        # the inner loop does not execute.
        for tfs in m.msg.transforms:
            parent = tfs.header.frame_id  # PARENT
            child = tfs.child_frame_id  # CHILD
            key = (parent, child)
            edge_times.setdefault(key, []).append(m.t_ns)
            frames.add(parent)
            frames.add(child)
            if is_static:
                static_keys.add(key)
            else:
                dynamic_keys.add(key)

    # 3. BAG BOUNDS for the bag-relative gap display (Decision 3). A TF stream was
    #    found (message_count > 0), but guard the start against a None/garbage value
    #    so the at_rel math never raises (zero-duration / clock-skew guard, mirrors
    #    inspect.collect_bag_info's defensive bounds handling).
    start_ns = reader.start_time
    end_ns = reader.end_time
    rel_base = start_ns if isinstance(start_ns, int) else None

    # 4. GAP DETECTION per edge.
    edges: list[EdgeReport] = []
    gaps: list[GapReport] = []
    abs_threshold_ns = gap_ms * _NS_PER_MS if gap_ms is not None else None

    for key, times in edge_times.items():
        parent, child = key
        samples = len(times)
        # Sort defensively: the merged stream is time-ordered overall, but a
        # multi-bag / clock-skew read may not be strictly monotonic per edge.
        ordered = sorted(times)
        first_ns = ordered[0]
        last_ns = ordered[-1]
        is_static = key in static_keys
        # MIXED tie-break (Decision 5): static-only -> never gap-check; seen on /tf
        # (with or without /tf_static) -> gap-checkable.
        gap_checkable = key in dynamic_keys

        # STATIC SKIP and ZERO/SINGLE-SAMPLE SKIP both short-circuit to an
        # informational EdgeReport with no gaps and no inferable rate.
        if not gap_checkable or samples < 2:
            edges.append(
                EdgeReport(
                    parent=parent,
                    child=child,
                    static=is_static,
                    samples=samples,
                    first_ns=first_ns,
                    last_ns=last_ns,
                    expected_ns=None,
                    max_gap_ns=None,
                    gap_count=0,
                )
            )
            continue

        # Inter-arrival deltas; drop any <= 0 (duplicate/backwards stamps) BEFORE the
        # median so they never zero it (threat T-09-03).
        # strict=False: the two iterables intentionally differ in length by one
        # (consecutive-pairs walk), so zip MUST stop at the shorter — not error.
        diffs = [b - a for a, b in zip(ordered, ordered[1:], strict=False) if b - a > 0]
        if not diffs:
            # Every delta was <= 0 (all-duplicate timestamps) — no rate, no gap math.
            edges.append(
                EdgeReport(
                    parent=parent,
                    child=child,
                    static=is_static,
                    samples=samples,
                    first_ns=first_ns,
                    last_ns=last_ns,
                    expected_ns=None,
                    max_gap_ns=None,
                    gap_count=0,
                )
            )
            continue

        expected = statistics.median(diffs)
        if expected <= 0:  # guard (no ZeroDivision / false gap) — defensive
            edges.append(
                EdgeReport(
                    parent=parent,
                    child=child,
                    static=is_static,
                    samples=samples,
                    first_ns=first_ns,
                    last_ns=last_ns,
                    expected_ns=None,
                    max_gap_ns=None,
                    gap_count=0,
                )
            )
            continue

        expected_ns = int(expected)
        edge_gaps: list[GapReport] = []
        multiplier_threshold = gap_multiplier * expected
        # Walk consecutive observed samples; emit a gap per offending delta. Gaps are
        # BETWEEN observed samples only (A4) — no bag-boundary synthesis.
        # strict=False: consecutive-pairs walk over differing-length iterables.
        for a, b in zip(ordered, ordered[1:], strict=False):
            d = b - a
            if d <= 0:  # already excluded from the median; never a gap
                continue
            is_gap = d > multiplier_threshold or (
                abs_threshold_ns is not None and d > abs_threshold_ns
            )
            if not is_gap:
                continue
            at_rel_ns = (a - rel_base) if rel_base is not None else a
            edge_gaps.append(
                GapReport(
                    parent=parent,
                    child=child,
                    gap_ns=d,
                    at_ns=a,
                    at_rel_ns=at_rel_ns,
                    at_rel_s=at_rel_ns / 1e9,
                    expected_ns=expected_ns,
                )
            )

        gaps.extend(edge_gaps)
        edges.append(
            EdgeReport(
                parent=parent,
                child=child,
                static=is_static,
                samples=samples,
                first_ns=first_ns,
                last_ns=last_ns,
                expected_ns=expected_ns,
                max_gap_ns=max((g.gap_ns for g in edge_gaps), default=None),
                gap_count=len(edge_gaps),
            )
        )

    edges.sort(key=lambda e: (e.parent, e.child))
    gaps.sort(key=lambda g: g.at_ns)

    return TfReport(
        frames=frozenset(frames),
        edges=edges,
        gaps=gaps,
        start_ns=start_ns,
        end_ns=end_ns,
    )
