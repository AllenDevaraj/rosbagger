"""The edit-operation spec + per-message predicates (Plan 11-01, D-06/07/08).

:class:`EditOps` is a small frozen dataclass carrying the four same-format edit
operations as DATA — a trim window, a drop set, a keep set, per-topic + global
downsample factors — plus the two validity rules the pipeline relies on:

* **D-07 mutual exclusion** — ``drop`` and ``keep`` cannot both be non-empty
  (``--drop`` excludes named topics; ``--keep`` includes only named topics; mixing
  them is ambiguous). Enforced in ``__post_init__`` so an invalid spec can NEVER
  reach :func:`rosbagger_core.edit.pipeline.edit_bag` — the CLI (Plan 11-02) maps
  the resulting ``ValueError`` to ``typer.BadParameter`` before any bag is opened.
* **V5 input validation** — every downsample factor ``N`` must be a positive int
  (``N <= 0`` is meaningless and would zero-divide or drop everything).

The trim window is bag-relative SECONDS (D-06): a message at log time ``t_ns`` is
kept iff ``start_ns + int(START*1e9) <= t_ns <= start_ns + int(END*1e9)`` where
``start_ns`` is the reader's ``start_time``. The per-message decision helpers
live here (``keeps_topic`` / ``trim_window_ns`` / ``downsample_factor``) so the
streaming loop in ``pipeline.py`` stays readable.

OFFLINE INVARIANT (11-RESEARCH Pitfall 5): this module imports ONLY the standard
library (``dataclasses``) — never ``rosbags`` / ``duckdb`` / ``pyarrow``. The
heavy ``rosbags`` Writer/Reader imports are confined to ``pipeline.py`` function
bodies, so ``import rosbagger_core.edit`` stays light
(``tests/test_offline_guard.py`` enforces this).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EditOps:
    """A frozen, validated spec for the same-format edit operations (D-06/07/08).

    All fields default to "no-op", so ``EditOps()`` is an identity edit (raw-copy
    every message of every topic). Construct with only the operations you want:

    * ``trim`` — ``(start_s, end_s)`` bag-relative seconds, inclusive; ``None`` = no trim.
    * ``drop`` — topics to EXCLUDE (mutually exclusive with ``keep``).
    * ``keep`` — topics to INCLUDE (only these survive; mutually exclusive with ``drop``).
    * ``downsample`` — per-topic ``{topic: N}``, keep every Nth message of that topic.
    * ``downsample_all`` — a global N applied to topics with no per-topic factor.

    Validation runs in ``__post_init__``: ``drop`` + ``keep`` both non-empty raises
    ``ValueError`` (D-07), and any downsample ``N <= 0`` raises ``ValueError`` (V5).
    """

    trim: tuple[float, float] | None = None
    drop: frozenset[str] = field(default_factory=frozenset)
    keep: frozenset[str] = field(default_factory=frozenset)
    downsample: dict[str, int] = field(default_factory=dict)
    downsample_all: int | None = None

    def __post_init__(self) -> None:
        # D-07: --drop and --keep are mutually exclusive. Both non-empty is ambiguous.
        if self.drop and self.keep:
            raise ValueError(
                "Cannot combine drop and keep: --drop excludes named topics while "
                "--keep includes only named topics. Use one or the other, not both."
            )
        # V5 input validation: every downsample factor must be a positive integer.
        for topic, n in self.downsample.items():
            if not isinstance(n, int) or n <= 0:
                raise ValueError(
                    f"downsample factor for {topic!r} must be a positive integer, got {n!r}."
                )
        if self.downsample_all is not None and (
            not isinstance(self.downsample_all, int) or self.downsample_all <= 0
        ):
            raise ValueError(
                f"global downsample factor must be a positive integer, got {self.downsample_all!r}."
            )

    def keeps_topic(self, topic: str) -> bool:
        """Is ``topic`` retained under the drop/keep filter (D-07)?

        With a ``keep`` set, ONLY its members survive; with a ``drop`` set, its
        members are excluded; with neither, every topic is kept. The connection
        layer in ``edit_bag`` calls this once per source connection so dropped
        topics are never re-registered (no orphan connections).
        """
        if self.keep:
            return topic in self.keep
        if self.drop:
            return topic not in self.drop
        return True

    def trim_window_ns(self, start_ns: int) -> tuple[int, int] | None:
        """Resolve the bag-relative trim window to absolute ``[lo_ns, hi_ns]`` (D-06).

        ``start_ns`` is the reader's ``start_time``. Returns ``None`` when no trim
        is configured (the caller then keeps every timestamp). The seconds bounds
        are converted to ns with ``int(x * 1e9)`` to match the fixtures' integer
        nanosecond timestamps exactly.
        """
        if self.trim is None:
            return None
        start_s, end_s = self.trim
        lo = start_ns + int(start_s * 1e9)
        hi = start_ns + int(end_s * 1e9)
        return lo, hi

    def downsample_factor(self, topic: str) -> int | None:
        """The effective every-Nth factor for ``topic`` (per-topic beats global).

        Returns the per-topic factor if set, else ``downsample_all``, else ``None``
        (keep every message). A returned factor is always a positive int (validated
        at construction), so the pipeline's ``counter % N == 0`` test is safe.
        """
        if topic in self.downsample:
            return self.downsample[topic]
        return self.downsample_all
