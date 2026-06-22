"""
Central application state — signal-bearing shared QObject.

AppState is owned by AppShell.  Pages receive a reference in their
constructor and read from it.  No QSettings I/O and no DB access
originate from this class.
"""

from __future__ import annotations

from collections.abc import Iterable

from PyQt6 import QtCore

from minerva.app.stores.report_store import ReportStore


class AppState(QtCore.QObject):
    """Shared application state — signal bus + observable domain stores.

    Signals
    -------
    selected_count_changed(int) — emitted when *selected_game_ids* size
        changes.  The int argument is the new count.
    index_state_changed(object) — emitted when DB index status changes.
    qbit_state_changed(object)  — emitted when qBittorrent connection
        state changes.
    queue_changed()             — emitted when the download queue mutates.

    Stores
    ------
    ``self.reports`` — :class:`ReportStore` with granular signals for
    report and entry mutations.  Subscribe to
    ``app_state.reports.entries_updated`` etc. instead of polling.
    """

    selected_count_changed = QtCore.pyqtSignal(int)
    index_state_changed = QtCore.pyqtSignal(object)
    qbit_state_changed = QtCore.pyqtSignal(object)
    queue_changed = QtCore.pyqtSignal()
    log_message = QtCore.pyqtSignal(str)
    runtime_changed = QtCore.pyqtSignal(list)
    activity_event = QtCore.pyqtSignal(str, str)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.reports = ReportStore(self)
        self._selected_game_ids: set[str] = set()
        self._current_report_id: str | None = None
        self._index_state: object = None
        self._qbit_state: object = False

    # ── Read-only views ────────────────────────────────────────────────

    @property
    def selected_game_ids(self) -> frozenset[str]:
        """Immutable view of the selected-game-IDs set."""
        return frozenset(self._selected_game_ids)

    @property
    def current_report_id(self) -> str | None:
        return self._current_report_id

    @current_report_id.setter
    def current_report_id(self, value: str | None) -> None:
        self._current_report_id = value

    @property
    def index_state(self) -> object:
        return self._index_state

    @index_state.setter
    def index_state(self, value: object) -> None:
        self._index_state = value
        self.index_state_changed.emit(value)

    @property
    def qbit_state(self) -> object:
        return self._qbit_state

    @qbit_state.setter
    def qbit_state(self, value: object) -> None:
        self._qbit_state = value
        self.qbit_state_changed.emit(value)

    # ── Mutators (the ONLY way to change selection from outside) ───────

    def set_selected(self, ids: Iterable[str]) -> None:
        """Replace the selection set and emit ``selected_count_changed``."""
        self._selected_game_ids = set(ids)
        self.selected_count_changed.emit(len(self._selected_game_ids))

    def clear_selected(self) -> None:
        """Empty the selection set and emit ``selected_count_changed(0)``."""
        self._selected_game_ids.clear()
        self.selected_count_changed.emit(0)
