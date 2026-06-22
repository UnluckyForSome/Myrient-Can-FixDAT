"""Right-side collection inspector used by the Collections dashboard."""

from __future__ import annotations

from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.domain.collections import CollectionStatus, CollectionSummary, ReferenceDat, SystemSummary
from minerva.ui.icons import Icons
from minerva.ui.widgets.inspector_scaffold import InspectorScaffold
from minerva.ui.widgets.property_list import PropertyList
from minerva.ui.widgets.status_badge import BadgeKind, StatusBadge


class CollectionInspector(InspectorScaffold):
    """Collection scope, coverage and actions for the current selection."""

    open_requested = QtCore.pyqtSignal()
    import_requested = QtCore.pyqtSignal()
    remove_requested = QtCore.pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__("Collection details", parent=parent)
        self.setMinimumWidth(320)
        self.setMaximumWidth(400)

        # ── Hero ────────────────────────────────────────────────────────
        self.title = QtWidgets.QLabel("Select a collection")
        self.title.setObjectName("inspectorTitle")
        self.title.setWordWrap(True)
        self.hero_layout.addWidget(self.title)

        self.subtitle = QtWidgets.QLabel(
            "Choose a collection to inspect systems, references, and source health."
        )
        self.subtitle.setObjectName("mutedLabel")
        self.subtitle.setWordWrap(True)
        self.hero_layout.addWidget(self.subtitle)

        # ── Status ──────────────────────────────────────────────────────
        self.status = StatusBadge("No selection", BadgeKind.NEUTRAL)
        self.status_layout.addWidget(self.status)

        # ── Body — metadata via PropertyList ────────────────────────────
        section = QtWidgets.QLabel("INDEX SUMMARY")
        section.setObjectName("inspectorSectionTitle")
        self.body_layout.addWidget(section)

        self._properties = PropertyList(
            [
                ("Systems", "\u2014"),
                ("Indexed files", "\u2014"),
                ("Reference DATs", "\u2014"),
                ("Known coverage", "\u2014"),
                ("Source folder", "\u2014"),
            ],
        )
        self.body_layout.addWidget(self._properties)

        coverage_title = QtWidgets.QLabel("REFERENCE COVERAGE")
        coverage_title.setObjectName("inspectorSectionTitle")
        self.body_layout.addWidget(coverage_title)

        self.coverage = QtWidgets.QProgressBar()
        self.coverage.setObjectName("collectionCoverage")
        self.coverage.setRange(0, 100)
        self.coverage.setTextVisible(True)
        self.body_layout.addWidget(self.coverage)

        self.coverage_note = QtWidgets.QLabel(
            "Import a reference DAT to calculate expected coverage."
        )
        self.coverage_note.setObjectName("mutedLabel")
        self.coverage_note.setWordWrap(True)
        self.body_layout.addWidget(self.coverage_note)

        # ── Actions ─────────────────────────────────────────────────────
        self.open_button = QtWidgets.QPushButton(Icons.folder_open(), "Open source folder")
        self.open_button.setObjectName("actionGroupPrimary")
        self.open_button.clicked.connect(self.open_requested.emit)
        self.actions_layout.addWidget(self.open_button)

        self.import_button = QtWidgets.QPushButton(Icons.upload(), "Import reference DAT")
        self.import_button.setObjectName("actionGroupSecondary")
        self.import_button.clicked.connect(self.import_requested.emit)
        self.actions_layout.addWidget(self.import_button)

        self.remove_button = QtWidgets.QPushButton(Icons.trash(), "Remove from index")
        self.remove_button.setObjectName("actionGroupDestructive")
        self.remove_button.clicked.connect(self.remove_requested.emit)
        self.actions_layout.addWidget(self.remove_button)

        self.clear()

    def clear(self) -> None:  # type: ignore[override]
        self.title.setText("Select a collection")
        self.subtitle.setText(
            "Choose a collection to inspect systems, references, and source health."
        )
        self.status.setText("No selection")
        self.status.set_kind(BadgeKind.NEUTRAL)
        self._properties.set_rows([
            ("Systems", "\u2014"),
            ("Indexed files", "\u2014"),
            ("Reference DATs", "\u2014"),
            ("Known coverage", "\u2014"),
            ("Source folder", "\u2014"),
        ])
        self.coverage.setValue(0)
        self.coverage.setFormat("Unknown")
        self.coverage_note.setText("Import a reference DAT to calculate expected coverage.")
        self.set_actions_enabled(False)

    def set_collection(
        self,
        summary: CollectionSummary,
        systems: list[SystemSummary],
        references: list[ReferenceDat],
        source_folder: Path,
    ) -> None:
        self.title.setText(summary.name)
        self.subtitle.setText(
            f"{summary.systems:,} systems \xb7 {summary.files:,} indexed files"
        )
        status_text, kind = self._map_status(summary.status)
        self.status.setText(status_text)
        self.status.set_kind(kind)
        self._properties.set_rows([
            ("Systems", f"{summary.systems:,}"),
            ("Indexed files", f"{summary.files:,}"),
            ("Reference DATs", f"{len(references):,}"),
            ("Source folder", str(source_folder)),
        ])

        known = [item for item in systems if item.expected_files]
        indexed_known = sum(item.files for item in known)
        expected_known = sum(item.expected_files or 0 for item in known)
        if expected_known:
            ratio = min(1.0, indexed_known / expected_known)
            self.coverage.setValue(round(ratio * 100))
            self.coverage.setFormat(f"{ratio:.1%}")
            self._properties.set_row("Known coverage", f"{ratio:.1%}")
            self.coverage_note.setText(
                f"Based on {len(known):,} system reference"
                f"{'' if len(known) == 1 else 's'} \xb7 "
                f"{indexed_known:,} of {expected_known:,} expected files indexed."
            )
        else:
            self.coverage.setValue(0)
            self.coverage.setFormat("Unknown")
            self._properties.set_row("Known coverage", "Unknown")
            self.coverage_note.setText(
                "No imported reference DAT covers this collection yet."
            )
        self.set_actions_enabled(True)

    def set_actions_enabled(self, enabled: bool) -> None:
        self.open_button.setEnabled(enabled)
        self.import_button.setEnabled(enabled)
        self.remove_button.setEnabled(enabled)

    @staticmethod
    def _map_status(status: CollectionStatus) -> tuple[str, BadgeKind]:
        if status == CollectionStatus.INDEXED:
            return "Indexed", BadgeKind.SUCCESS
        if status == CollectionStatus.PARTIAL:
            return "Partial", BadgeKind.WARNING
        return "Missing", BadgeKind.ERROR
