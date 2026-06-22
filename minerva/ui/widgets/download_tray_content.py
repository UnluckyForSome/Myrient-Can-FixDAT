"""DownloadTrayContent — reusable download management widget for the tray.

Extracts the core download table, segmented filter, and action controls
from DownloadsPage into a standalone widget that can be embedded in the
DownloadTray's expanded content area.
"""

from __future__ import annotations

import logging

from PyQt6 import QtCore, QtWidgets

from minerva.app.app_state import AppState
from minerva.app.download_controller import DownloadController
from minerva.domain.downloads import DownloadStatus
from minerva.ui.icons import Icons
from minerva.ui.models.delegates import ActionDelegate, DisplayDelegate, ProgressDelegate
from minerva.ui.models.download_model import (
    DownloadTableModel,
    _DOWNLOAD_COLUMNS,
)
from minerva.ui.widgets.segmented_control import SegmentedControl

log = logging.getLogger(__name__)


class _TrayFilterProxy(QtCore.QSortFilterProxyModel):
    """Lightweight filter for the tray — text + status."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._status = "all"
        self.setDynamicSortFilter(False)

    def set_status(self, status: str) -> None:
        self._status = status
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):  # noqa: N802
        model = self.sourceModel()
        if not isinstance(model, DownloadTableModel):
            return True
        record = model.record_at(source_row)
        if record is None:
            return False

        status_groups = {
            "active": {
                DownloadStatus.STARTING,
                DownloadStatus.DOWNLOADING,
                DownloadStatus.PAUSED,
                DownloadStatus.SEEDING,
            },
            "queued": {DownloadStatus.QUEUED},
            "completed": {DownloadStatus.COMPLETED},
            "failed": {DownloadStatus.FAILED, DownloadStatus.CANCELLED},
        }
        if self._status != "all" and self._status in status_groups:
            if record.status not in status_groups[self._status]:
                return False
        return True


class DownloadTrayContent(QtWidgets.QWidget):
    """Compact download table with segmented filter and action controls.

    Designed for embedding in the DownloadTray expanded area.
    """

    action_triggered = QtCore.pyqtSignal(str, str)  # action_name, queue_id

    def __init__(
        self,
        app_state: AppState,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._controller: DownloadController | None = None
        self._resolve_controller()

        self._model = DownloadTableModel([], _DOWNLOAD_COLUMNS, parent=self)
        self._proxy = _TrayFilterProxy(self)
        self._proxy.setSourceModel(self._model)

        self._build_ui()
        self._wire_signals()
        self._refresh_from_controller()

    # ── Controller resolution ────────────────────────────────────────────

    def _resolve_controller(self) -> None:
        """Try to get the DownloadController from the shell via app_state."""
        # ponytail: the controller lives on AppShell; app_state's parent
        # chain should lead there. If not found, the widget just shows
        # "No connection" — no crash.
        parent = self._app_state.parent()
        while parent is not None:
            if hasattr(parent, "download_controller"):
                self._controller = parent.download_controller
                return
            parent = parent.parent()

    # ── UI ───────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # Segmented filter row
        self._segments = SegmentedControl([
            ("all", "All"),
            ("active", "Active"),
            ("queued", "Queued"),
            ("completed", "Done"),
        ])
        layout.addWidget(self._segments)

        # Download table
        self._view = QtWidgets.QTableView()
        self._view.setObjectName("trayDownloadsTable")
        self._view.setModel(self._proxy)
        self._view.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._view.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._view.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._view.setAlternatingRowColors(True)
        self._view.setSortingEnabled(True)
        self._view.setShowGrid(False)
        self._view.verticalHeader().hide()
        self._view.verticalHeader().setDefaultSectionSize(36)
        self._view.setItemDelegateForColumn(0, DisplayDelegate(self._view))
        self._progress_delegate = ProgressDelegate(self._view)
        self._view.setItemDelegateForColumn(2, self._progress_delegate)
        self._action_delegate = ActionDelegate(self._view)
        self._view.setItemDelegateForColumn(7, self._action_delegate)
        header = self._view.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._view, 1)

        # Action row
        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(8)
        self._pause_btn = QtWidgets.QPushButton("Pause all")
        self._pause_btn.setIcon(Icons.pause())
        self._pause_btn.setFixedHeight(28)
        self._pause_btn.clicked.connect(lambda: self._bulk_action("pause_all"))
        action_row.addWidget(self._pause_btn)

        self._resume_btn = QtWidgets.QPushButton("Resume")
        self._resume_btn.setIcon(Icons.play())
        self._resume_btn.setFixedHeight(28)
        self._resume_btn.clicked.connect(lambda: self._bulk_action("resume_all"))
        action_row.addWidget(self._resume_btn)

        action_row.addStretch(1)
        layout.addLayout(action_row)

    def _wire_signals(self) -> None:
        self._segments.current_changed.connect(self._on_segment)
        self._action_delegate.action_triggered.connect(self._on_action)
        if self._controller is not None:
            self._controller.queue_changed.connect(self._refresh_from_controller)
        self._app_state.queue_changed.connect(self._refresh_from_controller)

    # ── Actions ──────────────────────────────────────────────────────────

    def _on_segment(self, segment_id: str) -> None:
        self._proxy.set_status(segment_id)

    def _on_action(self, action_name: str, queue_id: str) -> None:
        self.action_triggered.emit(action_name, queue_id)

    def _bulk_action(self, action: str) -> None:
        if self._controller is None:
            return
        if action == "pause_all":
            self._controller.pause_all()
        elif action == "resume_all":
            self._controller.resume_all()

    # ── Refresh ──────────────────────────────────────────────────────────

    def _refresh_from_controller(self) -> None:
        if self._controller is None:
            return
        try:
            records = self._controller.get_queue_records()
            self._model.replace_records(records)
        except Exception:
            log.debug("Failed to refresh tray content from controller", exc_info=True)
