"""``RosbaggerApp`` — the Textual shell: sidebar ListView + ContentSwitcher.

The cockpit shell every panel sits on (D-01/D-02/D-03/D-04):

* **Shell (D-01):** a ``Horizontal`` of a sidebar ``ListView`` (one ``ListItem``
  per panel) and a ``ContentSwitcher`` (the five panel widgets). Selecting a
  sidebar item sets ``switcher.current`` to the matching panel id.
* **Shared reader (D-02):** the App owns exactly ONE open ``RosbagsReader``. It is
  opened in ``on_mount`` when launched with a ``<bag-path>``; an in-TUI picker can
  call :meth:`open_bag` to close it and open another. Panels read from this single
  reader — there is never a second open reader.
* **Capability gate (D-03/D-04):** a cheap tier-1 ``_detect_ros`` probe runs ONCE
  at startup; when ROS is absent the live record/replay sidebar items AND panel
  widgets are ``disabled``, surfacing the teaching hint. Offline panels
  (inspect/query/tf) are always enabled.

OFFLINE-IMPORT INVARIANT (D-03): this module imports NO ROS at top level. The
ROS-2-Humble typestore for the legacy-sqlite3 fixture is imported from ``rosbags``
(which is ROS-free); ``rclpy`` is touched only inside :func:`_detect_ros`. The live
packages are imported only inside the live panels' method bodies (a later wave).
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import ContentSwitcher, Label, ListItem, ListView

from rosbagger_core.reader import RosbagsReader

from . import _detect_ros
from .panels import InspectPanel, QueryPanel, RecordPanel, ReplayPanel, TfPanel

# Panel registry: (panel id, sidebar label, panel class, is_live). The id is the
# ContentSwitcher key; the sidebar ListItem id is "nav-" + id (D-01). Live panels
# (record/replay) are capability-gated (D-03).
_PANELS: tuple[tuple[str, str, type, bool], ...] = (
    ("inspect", "Inspect", InspectPanel, False),
    ("query", "Query", QueryPanel, False),
    ("tf", "TF", TfPanel, False),
    ("record", "Record", RecordPanel, True),
    ("replay", "Replay", ReplayPanel, True),
)

# The default panel shown on launch.
_INITIAL_PANEL = "inspect"


def _ros2_humble_typestore() -> object:
    """Build the ROS-2-Humble typestore for legacy ROS 2 sqlite3 bags (Pitfall 5).

    Modern ROS 2 bags (and MCAP / ROS 1) embed their own message definitions and
    need no default; the legacy ROS 2 sqlite3 fixture does. ``rosbags.typesys`` is
    ROS-FREE — importing it pulls no ``rclpy`` — so passing this default keeps the
    shared reader able to open every fixture while preserving the offline invariant.
    """
    from rosbags.typesys import Stores, get_typestore

    return get_typestore(Stores.ROS2_HUMBLE)


class RosbaggerApp(App):
    """The Textual cockpit App: sidebar + ContentSwitcher over a shared reader."""

    CSS_PATH = "app.tcss"

    def __init__(self, bag_path: str | Path | None = None, **kwargs: object) -> None:
        """Accept the optional D-02 launch-arg ``<bag-path>``; do NOT open yet.

        The reader is opened in :meth:`on_mount` (after the widget tree exists) so a
        bag-open error can surface in the UI rather than crashing construction
        (T-14-02-01). ``ros_available`` is computed once here (cheap, D-04).
        """
        super().__init__(**kwargs)
        self._bag_path: Path | None = Path(bag_path) if bag_path is not None else None
        self.reader: RosbagsReader | None = None
        self.ros_available: bool = _detect_ros()

    def compose(self) -> ComposeResult:
        """Build the shell: sidebar ``ListView`` + ``ContentSwitcher`` (D-01)."""
        with Horizontal():
            yield ListView(
                *(
                    ListItem(Label(label), id=f"nav-{panel_id}")
                    for panel_id, label, _cls, _live in _PANELS
                ),
                id="sidebar",
            )
            with ContentSwitcher(initial=_INITIAL_PANEL, id="content"):
                for panel_id, _label, cls, _live in _PANELS:
                    yield cls(id=panel_id)

    def on_mount(self) -> None:
        """Apply the live-panel gate (D-03) and open the launch bag if given (D-02)."""
        if not self.ros_available:
            # Disable the live sidebar items AND panel widgets so the teaching hint
            # is the only thing the live panels show (D-03).
            for panel_id, _label, _cls, is_live in _PANELS:
                if not is_live:
                    continue
                self.query_one(f"#nav-{panel_id}", ListItem).disabled = True
                self.query_one(f"#{panel_id}").disabled = True
        if self._bag_path is not None:
            self._open_reader(self._bag_path)

    def _open_reader(self, path: Path) -> None:
        """Open ONE shared ``RosbagsReader`` over ``path`` (D-02), replacing any prior.

        Closes any currently-open reader first so there is never a second open
        reader. Passes the ROS-2-Humble typestore so the legacy sqlite3 fixture
        loads (Pitfall 5); modern bags ignore the unused default.
        """
        if self.reader is not None:
            self.reader.close()
            self.reader = None
        reader = RosbagsReader(path, default_typestore=_ros2_humble_typestore())
        try:
            reader.open()
        except Exception as exc:  # noqa: BLE001 - teaching, not a startup crash (WR-05)
            # A bad/corrupt/missing <bag-path> must surface in the UI rather than crash
            # construction — the __init__ contract defers opening to on_mount for exactly
            # this. Both the launch (on_mount) and the picker (open_bag) paths funnel here,
            # so a single teaching notify covers both without a traceback.
            self.notify(f"Could not open {path}: {exc}", severity="error")
            return
        self.reader = reader
        self._bag_path = path

    def open_bag(self, path: str | Path) -> None:
        """In-TUI picker seam (D-02): switch the shared reader to ``path``.

        Closes the existing reader, opens the new one, and refreshes the active
        panel so it re-reads from the new shared reader. This is the single entry
        point the bag-picker will call.
        """
        self._open_reader(Path(path))
        switcher = self.query_one("#content", ContentSwitcher)
        active = switcher.current
        if active is not None:
            panel = self.query_one(f"#{active}")
            # Panels expose refresh_view() to re-READ the new shared reader (a plain
            # .refresh() only re-renders the existing data); call it when present so
            # a bag switch repopulates the active panel from core (D-05/D-07).
            refresh_view = getattr(panel, "refresh_view", None)
            if callable(refresh_view):
                refresh_view()
            else:
                panel.refresh()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Sidebar selection drives the ContentSwitcher (D-01).

        The selected ``ListItem`` id is ``nav-<panel>``; stripping the prefix yields
        the ContentSwitcher key. A disabled live item never fires this (Textual skips
        disabled items), so a gated panel is never switched to.
        """
        item_id = event.item.id
        if item_id is None:
            return
        self.query_one("#content", ContentSwitcher).current = item_id.removeprefix("nav-")

    def on_unmount(self) -> None:
        """Close the shared reader on shutdown (no leaked file handle, D-02)."""
        if self.reader is not None:
            self.reader.close()
            self.reader = None
