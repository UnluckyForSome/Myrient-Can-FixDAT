"""Purpose-built game inspector for the Library dashboard."""

from __future__ import annotations

from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.domain.library import LibraryItem
from minerva.ui.icons import Icons
from minerva.ui.widgets.cover_art import CoverLabel
from minerva.ui.widgets.inspector_scaffold import InspectorScaffold
from minerva.ui.widgets.property_list import PropertyList
from minerva.ui.widgets.status_badge import BadgeKind, StatusBadge
from minerva.ui.widgets.tag_flow import TagFlow


class LibraryInspector(InspectorScaffold):
    """Cover, metadata, tags and actions for the selected library item."""

    queue_requested = QtCore.pyqtSignal()
    dat_requested = QtCore.pyqtSignal()
    copy_requested = QtCore.pyqtSignal()
    open_requested = QtCore.pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__("Game details", parent=parent)
        self.setMinimumWidth(320)
        self.setMaximumWidth(390)

        # ── Hero ────────────────────────────────────────────────────────
        self.cover = CoverLabel(154, 205)
        self.hero_layout.addWidget(self.cover, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)

        self.title = QtWidgets.QLabel("Select a game")
        self.title.setObjectName("inspectorTitle")
        self.title.setWordWrap(True)
        self.title.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        self.hero_layout.addWidget(self.title)

        self.subtitle = QtWidgets.QLabel("Choose a row to inspect its source and metadata.")
        self.subtitle.setObjectName("mutedLabel")
        self.subtitle.setWordWrap(True)
        self.subtitle.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        self.hero_layout.addWidget(self.subtitle)

        # ── Status ──────────────────────────────────────────────────────
        self.status = StatusBadge("No selection", BadgeKind.NEUTRAL)
        self.status_layout.addWidget(self.status)

        # ── Body — metadata via PropertyList ────────────────────────────
        tags_title = QtWidgets.QLabel("TAGS & REGIONS")
        tags_title.setObjectName("inspectorSectionTitle")
        self.body_layout.addWidget(tags_title)

        self._properties = PropertyList(
            [
                ("Collection", "\u2014"),
                ("System", "\u2014"),
                ("Size", "\u2014"),
                ("Source", "\u2014"),
                ("Path", "\u2014"),
            ],
            copy_values=True,
        )
        self.body_layout.addWidget(self._properties)

        self.tags = TagFlow()
        self.tags.setMaximumHeight(80)
        self.body_layout.addWidget(self.tags)

        # ── Actions ─────────────────────────────────────────────────────
        self.queue_button = QtWidgets.QPushButton(Icons.add(), "Add to queue")
        self.queue_button.setObjectName("actionGroupPrimary")
        self.queue_button.clicked.connect(self.queue_requested.emit)
        self.actions_layout.addWidget(self.queue_button)

        actions_row = QtWidgets.QHBoxLayout()
        actions_row.setSpacing(8)
        self.dat_button = QtWidgets.QPushButton(Icons.file(), "Generate DAT")
        self.dat_button.setObjectName("actionGroupSecondary")
        self.dat_button.clicked.connect(self.dat_requested.emit)
        actions_row.addWidget(self.dat_button)
        self.copy_button = QtWidgets.QPushButton(Icons.copy(), "Copy path")
        self.copy_button.setObjectName("actionGroupSecondary")
        self.copy_button.clicked.connect(self.copy_requested.emit)
        actions_row.addWidget(self.copy_button)
        self.actions_layout.addLayout(actions_row)

        self.open_button = QtWidgets.QPushButton(Icons.folder_open(), "Open downloaded file")
        self.open_button.setObjectName("actionGroupSecondary")
        self.open_button.clicked.connect(self.open_requested.emit)
        self.actions_layout.addWidget(self.open_button)

        self.clear()

    def clear(self) -> None:  # type: ignore[override]
        self.cover.set_placeholder()
        self.title.setText("Select a game")
        self.subtitle.setText("Choose a row to inspect its source and metadata.")
        self.status.setText("No selection")
        self.status.set_kind(BadgeKind.NEUTRAL)
        self._properties.set_rows([
            ("Collection", "\u2014"),
            ("System", "\u2014"),
            ("Size", "\u2014"),
            ("Source", "\u2014"),
            ("Path", "\u2014"),
        ])
        self.tags.set_tags([])
        self.set_actions_enabled(False)

    def set_item(
        self,
        item: LibraryItem,
        cover_path: str | Path | None,
        *,
        downloaded: bool,
    ) -> None:
        self.cover.set_cover(cover_path)
        self.title.setText(item.stem)
        self.subtitle.setText(item.basename)
        self.status.setText("Downloaded" if downloaded else "Indexed source")
        self.status.set_kind(BadgeKind.SUCCESS if downloaded else BadgeKind.NEUTRAL)
        self._properties.set_rows([
            ("Collection", item.collection or "Unknown"),
            ("System", item.system or "Unknown"),
            ("Size", self._format_size(item.size)),
            ("Source", item.source_torrent),
            ("Path", item.path_in_torrent),
        ])
        self.tags.set_tags(list(dict.fromkeys((*item.regions, *item.tags))))
        self.set_actions_enabled(True)
        self.open_button.setEnabled(downloaded)

    def set_actions_enabled(self, enabled: bool) -> None:
        self.queue_button.setEnabled(enabled)
        self.dat_button.setEnabled(enabled)
        self.copy_button.setEnabled(enabled)
        self.open_button.setEnabled(enabled)

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{value:.1f} TB"
