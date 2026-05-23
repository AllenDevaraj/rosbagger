"""The streaming same-format edit driver (Plan 11-01, D-03/04/05/09/10).

:func:`edit_bag` is the single read->filter->write pass: it opens an ``AnyReader``
over one or more SAME-format input paths (D-09 merge is implicit — ``AnyReader``
yields the combined stream time-ordered), re-registers ONLY the kept topics'
connections on a freshly-chosen output Writer (no orphan connections — 11-RESEARCH
Anti-Pattern), then streams the raw ``(connection, t_ns, rawdata)`` tuples,
applying the trim/drop/downsample filters and writing the UNMODIFIED ``rawdata``
losslessly (D-04 raw-copy half — the bytes are NOT decoded/re-encoded this plan;
cross-format CONVERT lands in Plan 11-02).

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

from pathlib import Path

from .operations import EditOps


def make_writer(dst: Path | str, fmt: str | None = None):
    """Construct the output Writer chosen by output FORMAT (D-10 / Pattern 3).

    The rosbags rule ``is2 = dst.suffix != '.bag'`` decides ROS 1 vs ROS 2; for
    ROS 2 the storage plugin is MCAP for a ``.mcap`` dest else SQLITE3. An explicit
    ``fmt`` (``"ros1"`` / ``"mcap"`` / ``"sqlite3"``) overrides the suffix.

    Returns an unopened Writer (a context manager); the caller drives its lifecycle.
    The ``rosbags`` import is lazy here so importing the edit module stays light.
    Raises ``ValueError`` on an unknown ``fmt``.
    """
    dst = Path(dst)
    suffix = dst.suffix.lower()

    if fmt is not None and fmt not in {"ros1", "mcap", "sqlite3"}:
        raise ValueError(f"unknown output format {fmt!r}; expected ros1, mcap, or sqlite3.")

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

    Raises ``ValueError`` if ``dst`` would overwrite an input (D-05), and re-raises
    a no-defs read error as :class:`~rosbagger_core.errors.UnresolvedTypeError`
    (mixed-format ``AnyReaderError`` propagates unchanged — Pitfall 6).
    """
    # Lazy imports keep `import rosbagger_core.edit` off the rosbags graph (Pitfall 5).
    from rosbags.highlevel import AnyReader, AnyReaderError

    src_list = [Path(srcs)] if isinstance(srcs, (str, Path)) else [Path(s) for s in srcs]
    dst = Path(dst)

    # D-05: never mutate the input; refuse before opening any Writer.
    _assert_not_overwriting_input(src_list, dst)

    reader = AnyReader(src_list)
    try:
        reader.open()
    except AnyReaderError as e:
        # Re-raise the no-defs case as the Phase 7 teaching error (copying the
        # RosbagsReader.open() pattern); mixed-format/other errors propagate.
        if "no type definitions" in str(e):
            from rosbagger_core.errors import UnresolvedTypeError

            raise UnresolvedTypeError(str(e)) from e
        raise  # mixed-format merge (Pitfall 6) and any other AnyReaderError surface as-is

    written = 0
    try:
        trim_window = ops.trim_window_ns(reader.start_time)
        with make_writer(dst, fmt) as writer:
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
            for conn in reader.connections:
                if not ops.keeps_topic(conn.topic):
                    continue
                key = (conn.topic, conn.msgtype)
                wconn = registered.get(key)
                if wconn is None:
                    wconn = writer.add_connection(
                        conn.topic, conn.msgtype, typestore=reader.typestore
                    )
                    registered[key] = wconn
                wconns[id(conn)] = wconn

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
                writer.write(wconn, t_ns, rawdata)  # RAW copy of the bytes (D-04, lossless)
                written += 1
    finally:
        reader.close()

    return written
