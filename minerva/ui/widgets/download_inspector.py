"""Purpose-built inspector for the selected download queue entry."""

from __future__ import annotations

from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.domain.downloads import DownloadStatus
from minerva.ui.icons import Icons
from minerva.ui.models.download_model import DownloadRecord, format_speed
from minerva.ui.widgets.cover_art import CoverLabel
from minerva.ui.widgets.inspector_scaffold import InspectorScaffold
from minerva.ui.widgets.property_list import PropertyList
from minerva.ui.widgets.status_badge import BadgeKind, StatusBadge


class DownloadInspector(InspectorScaffold):
    """Selected-task inspector with live telemetry and contextual actions."""

    pause_requested = QtCore.pyqtSignal(str)
    resume_requested = QtCore.pyqtSignal(str)
    retry_requested = QtCore.pyqtSignal(str)
    remove_requested = QtCore.pyqtSignal(str)
    open_folder_requested = QtCore.pyqtSignal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__("Current task", parent=parent)
        self.setMinimumWidth(310)
        self._record: DownloadRecord | None = None

        # ── Hero: cover + title/scope/torrent ───────────────────────────
        hero_row = QtWidgets.QHBoxLayout()
        hero_row.setSpacing(14)
        self._cover = CoverLabel(76, 104)
        hero_row.addWidget(self._cover, 0, QtCore.Qt.AlignmentFlag.AlignTop)

        hero_text = QtWidgets.QVBoxLayout()
        hero_text.setSpacing(4)
        self._title = QtWidgets.QLabel("Select a download")
        self._title.setObjectName("inspectorTitle")
        self._title.setWordWrap(True)
        hero_text.addWidget(self._title)
        self._scope = QtWidgets.QLabel("Queue details will appear here")
        self._scope.setObjectName("mutedLabel")
        self._scope.setWordWrap(True)
        hero_text.addWidget(self._scope)
        self._torrent = QtWidgets.QLabel("")
        self._torrent.setObjectName("mutedLabel")
        self._torrent.setWordWrap(True)
        hero_text.addWidget(self._torrent)
        hero_text.addStretch(1)
        hero_row.addLayout(hero_text, 1)
        self.hero_layout.addLayout(hero_row)

        # ── Status ──────────────────────────────────────────────────────
        self._status_badge = StatusBadge("No selection", BadgeKind.NEUTRAL)
        self.status_layout.addWidget(self._status_badge)

        # ── Body: progress + metadata + destination + error ─────────────
        self._progress_label = QtWidgets.QLabel("Overall progress")
        self._progress_label.setObjectName("mutedLabel")
        self.body_layout.addWidget(self._progress_label)
        self._progress = QtWidgets.QProgressBar()
        self._progress.setObjectName("downloadInspectorProgress")
        self._progress.setRange(0, 100)
        self._progress.setTextVisible(True)
        self.body_layout.addWidget(self._progress)

        self._properties = PropertyList(
            [
                ("Download speed", "\u2014"),
                ("Upload speed", "\u2014"),
                ("Peers / Seeds", "\u2014"),
                ("Ratio", "\u2014"),
            ],
        )
        self.body_layout.addWidget(self._properties)

        dest_title = QtWidgets.QLabel("Destination")
        dest_title.setObjectName("mutedLabel")
        self.body_layout.addWidget(dest_title)
        self._destination = QtWidgets.QLabel("\u2014")
        self._destination.setObjectName("propertyListValue")
        self._destination.setWordWrap(True)
        self._destination.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.body_layout.addWidget(self._destination)

        self._error = QtWidgets.QLabel("")
        self._error.setObjectName("downloadInspectorError")
        self._error.setWordWrap(True)
        self._error.hide()
        self.body_layout.addWidget(self._error)

        # ── Actions ─────────────────────────────────────────────────────
        self._open_btn = self._make_button("Open folder", Icons.folder_open(), "actionGroupSecondary")
        self._toggle_btn = self._make_button("Pause", Icons.pause(), "actionGroupSecondary")
        self._retry_btn = self._make_button("Retry", Icons.retry(), "actionGroupDestructive")
        self._remove_btn = self._make_button("Remove from queue", Icons.trash(), "actionGroupDestructive")
        for button in (self._open_btn, self._toggle_btn, self._retry_btn, self._remove_btn):
            self.actions_layout.addWidget(button)

        self._open_btn.clicked.connect(self._emit_open)
        self._toggle_btn.clicked.connect(self._emit_toggle)
        self._retry_btn.clicked.connect(self._emit_retry)
        self._remove_btn.clicked.connect(self._emit_remove)
        self.clear()

    @staticmethod
    def _make_button(text: str, icon: QtGui.QIcon, object_name: str) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        button.setIcon(icon)
        button.setObjectName(object_name)
        button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        return button

    def clear(self) -> None:  # type: ignore[override]
        self._record = None
        self._cover.set_placeholder()
        self._title.setText("Select a download")
        self._scope.setText("Queue details will appear here")
        self._torrent.clear()
        self._status_badge.setText("No selection")
        self._status_badge.set_kind(BadgeKind.NEUTRAL)
        self._progress.setValue(0)
        self._properties.set_rows([
            ("Download speed", "\u2014"),
            ("Upload speed", "\u2014"),
            ("Peers / Seeds", "\u2014"),
            ("Ratio", "\u2014"),
        ])
        self._destination.setText("\u2014")
        self._error.hide()
        for button in (self._open_btn, self._toggle_btn, self._retry_btn, self._remove_btn):
            button.setEnabled(False)

    def set_record(
        self, record: DownloadRecord, cover_path: str | Path | None = None
    ) -> None:
        self._record = record
        self._cover.set_cover(cover_path)
        self._title.setText(record.filename or "Unnamed download")
        scope = " \xb7 ".join(part for part in (record.collection, record.system) if part)
        self._scope.setText(scope or "Indexed file")
        self._torrent.setText(record.torrent_name or "Torrent not submitted yet")
        self._status_badge.setText(record.status.value.replace("_", " ").title())
        self._set_status_state(record.status.value)
        self._progress.setValue(max(0, min(100, int(record.progress * 100))))
        self._properties.set_rows([
            ("Download speed", format_speed(record.speed) if record.speed > 0 else "\u2014"),
            ("Upload speed", format_speed(record.upload_speed) if record.upload_speed > 0 else "\u2014"),
            ("Peers / Seeds", f"{record.peers} / {record.seeds}"),
            ("Ratio", f"{record.ratio:.2f}"),
        ])
        self._destination.setText(record.destination or record.save_path or "\u2014")
        self._destination.setToolTip(record.destination or record.save_path)
        self._error.setText(record.error_message or "")
        self._error.setVisible(bool(record.error_message))

        active = record.status in {
            DownloadStatus.STARTING,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.SEEDING,
        }
        resumable = record.status in {DownloadStatus.QUEUED, DownloadStatus.PAUSED}
        self._toggle_btn.setText("Pause" if active else "Resume")
        self._toggle_btn.setIcon(Icons.pause() if active else Icons.play())
        self._toggle_btn.setEnabled(active or resumable)
        self._retry_btn.setVisible(record.status == DownloadStatus.FAILED)
        self._retry_btn.setEnabled(record.status == DownloadStatus.FAILED)
        self._open_btn.setEnabled(bool(record.destination or record.save_path))
        self._remove_btn.setEnabled(True)

    def _set_status_state(self, state: str) -> None:
        kind_map = {
            "downloading": BadgeKind.INFO,
            "seeding": BadgeKind.SUCCESS,
            "completed": BadgeKind.SUCCESS,
            "failed": BadgeKind.ERROR,
            "paused": BadgeKind.WARNING,
            "queued": BadgeKind.NEUTRAL,
            "starting": BadgeKind.INFO,
            "cancelled": BadgeKind.WARNING,
        }
        kind = kind_map.get(state, BadgeKind.NEUTRAL)
        self._status_badge.set_kind(kind)

    def _emit_open(self) -> None:
        if self._record is not None:
            self.open_folder_requested.emit(
                self._record.destination or self._record.save_path
            )

    def _emit_toggle(self) -> None:
        if self._record is None:
            return
        if self._record.status in {
            DownloadStatus.STARTING,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.SEEDING,
        }:
            self.pause_requested.emit(self._record.queue_id)
        else:
            self.resume_requested.emit(self._record.queue_id)

    def _emit_retry(self) -> None:
        if self._record is not None:
            self.retry_requested.emit(self._record.queue_id)

    def _emit_remove(self) -> None:
        if self._record is not None:
            self.remove_requested.emit(self._record.queue_id)
