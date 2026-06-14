"""The streaming edit + convert driver (Plan 11-01 + 11-02, D-03/04/05/09/10).

:func:`edit_bag` is the single read->filter->write pass: it opens an ``AnyReader``
over one or more SAME-format input paths (D-09 merge is implicit — ``AnyReader``
yields the combined stream time-ordered), re-registers ONLY the kept topics'
connections on a freshly-chosen output Writer (no orphan connections — 11-RESEARCH
Anti-Pattern), then streams the raw ``(connection, t_ns, rawdata)`` tuples,
applying the trim/drop/downsample filters and writing the payload.

D-04 split (the key architectural decision). When the SOURCE and DESTINATION
wireformats MATCH (ROS 1 -> ROS 1, or ROS 2-sqlite3 <-> MCAP — both CDR), the
``rawdata`` is written UNMODIFIED — a lossless raw byte copy (the Plan 11-01 path).
When they DIFFER (ROS 1 <-> ROS 2 — ros1 vs cdr), each message's byte payload is
CONVERTED per message type by the ``rosbags`` converter factory (see
``edit/convert.py`` — Plan 11-02): the library picks ``cdr_to_ros1`` / ``ros1_to_cdr``
(byte-level) or ``migrate_bytes`` (the deserialize->migrate-fields->reserialize path
that fills the ROS 1 ``Header.seq`` field ROS 2 dropped — 11-RESEARCH Pitfall 1).
Filters + conversion compose in the SAME loop (D-10), and the convert path is NEVER
hand-rolled — the byte migration is entirely the library's (Don't-Hand-Roll).

The output Writer is chosen by output FORMAT via :func:`make_writer` using the
rosbags rule ``is2 = dst.suffix != '.bag'`` (D-10 / 11-RESEARCH Pattern 3): a
``.bag`` dest -> ``rosbag1.Writer``; a ``.mcap`` dest -> ``rosbag2.Writer`` with
MCAP storage; any other (directory) dest -> ``rosbag2.Writer`` with SQLITE3
storage. An explicit ``fmt in {ros1, mcap, sqlite3}`` overrides the suffix.

Safety (D-05 / threat T-11-01/T-11-02):

* The edit NEVER mutates the input and refuses to overwrite an input path — if the
  resolved ``dst`` equals any resolved input path, ``edit_bag`` raises ``ValueError``
  before opening any Writer.
* A bag with no resolvable type definitions surfaces the Phase 7
  :class:`~rosbagger_core.errors.UnresolvedTypeError` teaching error (copying the
  re-raise from ``RosbagsReader.open()``); a mixed-format-merge ``AnyReaderError``
  propagates unchanged (Pitfall 6) so it is not mislabeled as a type problem.

Empty result (Open Q2, LOCKED): an empty-keep / out-of-window trim writes the
(empty) output bag and RETURNS the message count (0) — never a silent no-op and
never a special-cased error here; the CLI in Plan 11-02 prints the count.

OFFLINE INVARIANT (11-RESEARCH Pitfall 5): every ``rosbags`` import is LAZY inside
a function body, so ``import rosbagger_core.edit`` (which re-exports this module's
``edit_bag``) pulls in no ``rosbags`` / heavy stack.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from .operations import EditOps


def _resolve_ops_topics(ops: EditOps, available: list[str]) -> EditOps:
    """Resolve ``ops``' keep/drop/downsample topic names against the bag's topics (T3).

    Normalizes a missing leading ``/`` (so ``--keep cmd_vel`` matches ``/cmd_vel``) and raises
    :class:`~rosbagger_core.errors.UnknownTopicError` (with a did-you-mean) for a genuine typo
    — instead of silently matching nothing and writing an EMPTY bag while reporting success
    (the data-loss this fixes). Returns a NEW ``EditOps`` whose keep/drop/downsample carry the
    CANONICAL topic names, so the existing ``keeps_topic`` / ``downsample_factor`` predicates
    (which compare against ``connection.topic``) match correctly.
    """
    from rosbagger_core.topics import resolve_topics

    changes: dict[str, object] = {}
    if ops.keep:
        changes["keep"] = frozenset(resolve_topics(ops.keep, available))
    if ops.drop:
        changes["drop"] = frozenset(resolve_topics(ops.drop, available))
    if ops.downsample:
        keys = list(ops.downsample)
        resolved_keys = resolve_topics(keys, available)
        changes["downsample"] = {
            canonical: ops.downsample[original]
            for original, canonical in zip(keys, resolved_keys)
        }
    if not changes:
        return ops
    return dataclasses.replace(ops, **changes)


def _validate_fmt(fmt: str | None) -> None:
    """Raise ``ValueError`` on an unknown explicit ``fmt`` (the single check both
    :func:`dst_is_ros2` and :func:`make_writer` rely on)."""
    if fmt is not None and fmt not in {"ros1", "mcap", "sqlite3"}:
        raise ValueError(f"unknown output format {fmt!r}; expected ros1, mcap, or sqlite3.")


def _validate_fmt_suffix(dst: Path, fmt: str | None) -> None:
    """Reject a contradiction between an explicit ``fmt`` and ``dst``'s suffix (WR-03).

    ``make_writer`` lets an explicit ``fmt`` OVERRIDE the suffix, but a contradictory
    pair produces an output whose on-disk SHAPE (file vs directory) does not match what
    its name implies, so :func:`rosbags.highlevel.AnyReader` cannot re-open it. The two
    footguns:

    * ``fmt`` is a ROS 2 format (``mcap`` / ``sqlite3``) but ``dst`` ends in ``.bag`` —
      writes a ROS 2 bag DIRECTORY literally named ``out.bag/``; re-opening sees the
      ``.bag`` suffix, treats the directory as a ROS 1 file, and raises
      ``AnyReaderError: ... Is a directory.``.
    * ``fmt == "ros1"`` but ``dst`` ends in ``.mcap`` — writes a ROS 1 FILE named
      ``out.mcap``; re-opening dispatches on the ``.mcap`` suffix to the MCAP reader,
      which cannot parse the ROS 1 bag bytes.

    Raising ``ValueError`` routes through the CLI's clean ``BadParameter`` mapping, so the
    contradiction is reported (with the fix) rather than silently producing a dead bag.
    The non-contradictory explicit-``fmt`` paths (e.g. ``fmt="mcap"`` with a no-suffix
    directory dest, the existing override test) are untouched — only a suffix that names
    the OPPOSITE ROS major version is rejected.
    """
    if fmt is None:
        return
    suffix = dst.suffix.lower()
    fmt_is2 = fmt != "ros1"
    if fmt_is2 and suffix == ".bag":
        raise ValueError(
            f"output format {fmt!r} is a ROS 2 format but the output path {dst} ends in "
            f"'.bag' (a ROS 1 extension). The result would be a directory named "
            f"'{dst.name}' that cannot be re-opened. Use a directory or '.mcap' output "
            f"name, or pass --format ros1."
        )
    if not fmt_is2 and suffix == ".mcap":
        raise ValueError(
            f"output format 'ros1' contradicts the output path {dst} ('.mcap' is a ROS 2 "
            f"extension). The result would be a ROS 1 bag named '{dst.name}' that cannot "
            f"be re-opened as MCAP. Use a '.bag' output name, or pass --format mcap/sqlite3."
        )


def dst_is_ros2(dst: Path | str, fmt: str | None = None) -> bool:
    """Is the destination a ROS 2 bag (the rosbags ``is2 = dst.suffix != '.bag'`` rule)?

    An explicit ``fmt`` overrides the suffix: ``"ros1"`` -> ROS 1 (``False``),
    ``"mcap"`` / ``"sqlite3"`` -> ROS 2 (``True``). This is the SAME decision
    :func:`make_writer` makes about which Writer to build, factored out so
    :func:`edit_bag` can compute ``dst_is2`` for the converter factory (D-04) without
    reconstructing the Writer's branch — the two can never disagree.
    """
    _validate_fmt(fmt)
    if fmt is not None:
        return fmt != "ros1"
    return Path(dst).suffix.lower() != ".bag"


def make_writer(dst: Path | str, fmt: str | None = None):
    """Construct the output Writer chosen by output FORMAT (D-10 / Pattern 3).

    The rosbags rule ``is2 = dst.suffix != '.bag'`` decides ROS 1 vs ROS 2 (see
    :func:`dst_is_ros2`); for ROS 2 the storage plugin is MCAP for a ``.mcap`` dest
    else SQLITE3. An explicit ``fmt`` (``"ros1"`` / ``"mcap"`` / ``"sqlite3"``)
    overrides the suffix.

    Returns an unopened Writer (a context manager); the caller drives its lifecycle.
    The ``rosbags`` import is lazy here so importing the edit module stays light.
    Raises ``ValueError`` on an unknown ``fmt``.
    """
    dst = Path(dst)
    suffix = dst.suffix.lower()
    _validate_fmt(fmt)

    if fmt == "ros1" or (fmt is None and suffix == ".bag"):
        from rosbags.rosbag1 import Writer as Ros1Writer

        # rosbag1.Writer takes ONLY a path — no version/storage_plugin (Pitfall 3).
        return Ros1Writer(dst)

    from rosbags.rosbag2 import StoragePlugin
    from rosbags.rosbag2 import Writer as Ros2Writer

    use_mcap = fmt == "mcap" or (fmt is None and suffix == ".mcap")
    plugin = StoragePlugin.MCAP if use_mcap else StoragePlugin.SQLITE3
    # version=9 is a REQUIRED keyword-only arg for the ROS 2 Writer (Pitfall 4).
    return Ros2Writer(dst, version=9, storage_plugin=plugin)


def _build_writer(dst: Path, fmt: str | None):
    """Construct the output Writer, mapping an already-exists failure to ``ValueError`` (WR-01).

    Both ``rosbags`` Writers raise their own ``WriterError`` (``rosbags.rosbag1`` and
    ``rosbags.rosbag2`` define DISTINCT classes) from ``__init__`` when the destination
    path already exists — ``"<path> exists already, not overwriting."`` Re-running
    ``bagq edit src.bag -o out.bag`` (a very common mistake) would otherwise surface a raw
    traceback: ``WriterError`` is not a ``ValueError``, so neither the CLI's
    ``except ValueError`` nor the ``@teaching_errors`` tuple catches it. Translate it to a
    clean teaching ``ValueError`` here so the CLI maps it to a clean ``BadParameter`` (no
    traceback), consistent with how every other verb presents errors. Any OTHER
    ``WriterError`` (or other exception) propagates unchanged — only the actionable
    already-exists case is reworded. The two ``WriterError`` classes are imported LAZILY so
    ``import rosbagger_core.edit`` stays off the rosbags graph (Pitfall 5).
    """
    from rosbags.rosbag1 import WriterError as Ros1WriterError
    from rosbags.rosbag2 import WriterError as Ros2WriterError

    try:
        return make_writer(dst, fmt)
    except (Ros1WriterError, Ros2WriterError) as e:
        if "exists already" in str(e):
            raise ValueError(
                f"output path {dst} already exists; bagq never overwrites an output bag. "
                f"Choose a new path or remove the existing one."
            ) from None
        raise  # any other Writer construction failure surfaces unchanged


def _assert_not_overwriting_input(srcs: list[Path], dst: Path) -> None:
    """Refuse to overwrite an input path (D-05 / threat T-11-01).

    Resolves every input and the destination to absolute paths and raises
    ``ValueError`` if the destination equals any input — the edit always writes a
    NEW output bag and must never clobber its own source (data loss).
    """
    dst_resolved = dst.resolve()
    for src in srcs:
        if src.resolve() == dst_resolved:
            raise ValueError(
                f"refusing to overwrite an input bag: output {dst} resolves to input "
                f"{src}. The edit always writes a NEW output bag (never in-place)."
            )


def edit_bag(
    srcs: list[Path | str] | Path | str,
    dst: Path | str,
    ops: EditOps,
    *,
    fmt: str | None = None,
) -> int:
    """Stream the same-format edit (trim/drop/keep/downsample/merge) and write ``dst``.

    ``srcs`` is one path or a list of SAME-format paths (multiple = implicit merge,
    D-09). ``ops`` is a validated :class:`EditOps`. ``fmt`` optionally overrides the
    output format inferred from ``dst``'s suffix (D-10). Returns the number of
    messages written (0 for an empty result — Open Q2 LOCKED: write the empty bag,
    report the count, no silent no-op).

    Raises ``ValueError`` if ``dst`` would overwrite an input (D-05), if an explicit
    ``fmt`` contradicts ``dst``'s suffix (WR-03 — would write an unreadable bag), or if
    ``dst`` already exists (WR-01 — the rosbags ``WriterError`` is reworded to a clean
    ``ValueError`` so the CLI never dumps a traceback). Re-raises a no-defs read error as
    :class:`~rosbagger_core.errors.UnresolvedTypeError` (mixed-format ``AnyReaderError``
    propagates unchanged — Pitfall 6).
    """
    # Lazy import keeps `import rosbagger_core.edit` off the rosbags graph (Pitfall 5).
    # open_bag is the SHARED bag-open chokepoint (T2): it owns the env-resolved typestore
    # fallback (so `bagq edit` opens a real def-less .db3 — previously it copy-pasted the
    # no-defs string match with NO typestore and raised), the coverage verify (a custom-type
    # bag still teaches), the no-defs -> UnresolvedTypeError translation, and the fd-leak-safe
    # close (newE19). A mixed-format-merge AnyReaderError still propagates unchanged (Pitfall 6).
    from rosbagger_core.reader import open_bag

    src_list = [Path(srcs)] if isinstance(srcs, (str, Path)) else [Path(s) for s in srcs]
    dst = Path(dst)

    # D-05: never mutate the input; refuse before opening any Writer.
    _assert_not_overwriting_input(src_list, dst)
    # WR-03: reject an explicit --format that contradicts the dst suffix (would write an
    # unreadable bag) BEFORE opening any reader — the ValueError maps to a clean CLI error.
    _validate_fmt_suffix(dst, fmt)

    reader = open_bag(src_list)

    written = 0
    try:
        # T3: resolve keep/drop/downsample topic names against the bag's ACTUAL topics —
        # normalizing a missing leading '/' and raising UnknownTopicError (did-you-mean) on a
        # typo, BEFORE any output is written. Without this, `--keep cmd_vel` (no slash) matched
        # no connection and edit_bag wrote an empty bag yet returned success (data loss).
        ops = _resolve_ops_topics(ops, sorted({c.topic for c in reader.connections}))

        trim_window = ops.trim_window_ns(reader.start_time)

        # D-04 split: when the SOURCE and DESTINATION wireformats differ (ROS 1 <->
        # ROS 2 — ros1 vs cdr), the byte payload must be CONVERTED per message type;
        # when they match (ROS 1 -> ROS 1, or ROS 2-sqlite3 <-> MCAP, both CDR), the
        # bytes are raw-copied losslessly. src_is2 comes from the reader; dst_is2 from
        # the SAME is2 = suffix != '.bag' rule make_writer uses (factored into
        # dst_is_ros2 so they can never disagree). The per-msgtype raw-copy-vs-migrate
        # decision itself is made INSIDE make_payload_converters via is_same_wireformat
        # (a same-wireformat msgtype gets the memoryview identity = raw copy).
        from . import convert as _convert

        src_is2 = reader.is2
        dst_is2 = dst_is_ros2(dst, fmt)
        converting = src_is2 != dst_is2

        # The destination connections (and thus the output msgdefs/md5/RIHS) must be
        # generated from the DESTINATION typestore when converting — add_connection(
        # ..., typestore=dst_ts) derives the right target message definition for the
        # built-in fixture types (11-RESEARCH Don't-Hand-Roll, verified). When the
        # wireformats match the SOURCE typestore is used (the raw bytes already match
        # it, and the converters are all the identity).
        write_ts = _convert.dst_typestore(dst_is2) if converting else reader.typestore

        # WR-01: _build_writer maps a "destination exists already" WriterError to a clean
        # ValueError (the CLI then presents it without a traceback); all other Writer
        # construction errors propagate unchanged.
        with _build_writer(dst, fmt) as writer:
            # Re-register ONLY kept connections (drop/keep at the connection layer):
            # a dropped topic is simply never added, so the output has no orphan
            # connection for it (11-RESEARCH Anti-Pattern).
            #
            # On a multi-bag MERGE (D-09), AnyReader exposes ONE connection PER
            # source bag — so the same topic appears N times, and the per-bag
            # connection ids COLLIDE (both bags use id 0/1/2). We therefore key by
            # the connection's OBJECT identity (id(conn)) — the ROS 2 Connection
            # NamedTuple is unhashable (its ext carries a list), but messages()
            # yields the SAME objects as reader.connections (identity-stable —
            # VERIFIED) — and register the writer connection ONCE per unique
            # (topic, msgtype): a second source connection for the same topic maps
            # to the SAME writer connection (rosbag1.Writer rejects re-adding an
            # identical connection, and a duplicate ROS 2 connection is pointless).
            # The source connection objects stay alive on the open reader for the
            # whole loop, so their ids are stable and never recycled mid-stream.
            wconns: dict[int, object] = {}  # id(source Connection) -> writer Connection
            registered: dict[tuple[str, str], object] = {}  # (topic, msgtype) -> writer conn
            kept_conns = [c for c in reader.connections if ops.keeps_topic(c.topic)]
            for conn in kept_conns:
                key = (conn.topic, conn.msgtype)
                wconn = registered.get(key)
                if wconn is None:
                    wconn = writer.add_connection(conn.topic, conn.msgtype, typestore=write_ts)
                    registered[key] = wconn
                wconns[id(conn)] = wconn

            # Per-kept-connection payload converter (the D-04 split, implemented once
            # in make_payload_converters): a same-wireformat msgtype gets the
            # memoryview IDENTITY (raw copy — bytes unchanged), a differing one gets
            # the rosbags factory's cdr_to_ros1 / ros1_to_cdr / migrate_bytes callable
            # (the seq-field case goes through migrate_bytes — Pitfall 1). The hard
            # byte migration is the LIBRARY's, never hand-rolled here (Don't-Hand-Roll).
            payload_converters = _convert.make_payload_converters(
                kept_conns, reader.typestore, write_ts, src_is2=src_is2, dst_is2=dst_is2
            )

            # Downsample counts per TOPIC (not per source connection) so merged
            # bags share one every-Nth sequence across the combined time-ordered
            # stream — the count must reflect the OUTPUT, not each input.
            counters: dict[str, int] = {}
            for conn, t_ns, rawdata in reader.messages():
                wconn = wconns.get(id(conn))
                if wconn is None:
                    continue  # dropped/unkept topic
                if trim_window is not None and not (trim_window[0] <= t_ns <= trim_window[1]):
                    continue  # outside the bag-relative trim window (D-06)
                n = ops.downsample_factor(conn.topic)
                if n is not None:
                    seen = counters.get(conn.topic, 0)
                    counters[conn.topic] = seen + 1
                    if seen % n != 0:
                        continue  # not the Nth message of this topic (D-08)
                # Identity for a matching wireformat (raw copy, D-04), or the library
                # converter for a differing one — selected per msgtype above.
                payload = payload_converters[id(conn)](rawdata)
                writer.write(wconn, t_ns, payload)
                written += 1
    finally:
        reader.close()

    return written
