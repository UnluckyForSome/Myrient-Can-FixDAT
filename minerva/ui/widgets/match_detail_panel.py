"""MatchDetailPanel — inline match review panel replacing InspectorScaffold.

Provides: candidate list, per-entry approve/ignore, bulk actions
(approve all exact, approve fuzzy above threshold), CDRomance search,
comparison view, export/generate DAT.

Occupies the inspector slot in the ResponsiveWorkspace 3-zone layout.
"""

from __future__ import annotations

import logging
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.app.app_state import AppState
from minerva.domain.reports import ReviewEntry
from minerva.ui.icons import Icons
from minerva.ui.theme import ThemeTokens

log = logging.getLogger(__name__)


# ── CDRomance / RetroGameTalk search helpers ──────────────────────────────

_SYSTEM_TO_CDR_SLUG = {
    "Sony - PlayStation": "psx-iso",
    "Sony - PlayStation 2": "ps2-iso",
    "Sony - PlayStation Portable": "psp",
    "Sony - PlayStation Vita": "vita",
    "Sega - Dreamcast": "dc-iso",
    "Sega - Saturn": "sega_saturn_isos",
    "Sega - Mega Drive - Genesis": "sega_genesis_roms",
    "Sega - Sega CD": "sega_cd_isos",
    "Sega - 32X": "sega_32x_roms",
    "Sega - Master System": "sms_roms",
    "Sega - Game Gear": "game-gear",
    "Nintendo - Wii": "wii-iso",
    "Nintendo - GameCube": "gamecube",
    "Nintendo - Nintendo 64": "n64-roms",
    "Nintendo - Super Nintendo": "snes-rom",
    "Nintendo - Nintendo Entertainment System": "nes-roms",
    "Nintendo - Famicom Disk System": "famicom_disk_system",
    "Nintendo - Nintendo DS": "nds-roms",
    "Nintendo - Game Boy Advance": "gba-roms",
    "Nintendo - Game Boy Color": "gameboy-color-roms",
    "Nintendo - Game Boy": "gameboy-roms",
    "NEC - PC Engine - TurboGrafx-16": "turbografx-16",
    "NEC - PC Engine CD - TurboGrafx-CD": "turbografx-cd",
    "NEC - PC-FX": "pc-fx",
    "SNK - Neo Geo Pocket Color": "neo-geo-pocket",
    "SNK - Neo Geo CD": "neo-geo-cd",
    "Panasonic - 3DO Interactive Multiplayer": "3do-iso",
    "Bandai - WonderSwan": "wonderswan",
    "Microsoft - MSX": "msx-roms",
    "Microsoft - Windows": "windows",
    "DOS": "msdos",
}


class MatchDetailPanel(QtWidgets.QWidget):
    """Inline match detail panel — replaces InspectorScaffold in the
    3-zone Reports workspace.

    Parameters
    ----------
    app_state : AppState
        Shared application state for signal bus access.
    """

    decision_changed = QtCore.pyqtSignal(str, str, str)  # report_id, entry_id, decision
    bulk_decision_requested = QtCore.pyqtSignal(str, str, int)  # report_id, filter_type, threshold

    def __init__(
        self,
        app_state: AppState,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._current_report_id: str | None = None
        self._current_entry_id: str | None = None
        self._current_system: str | None = None
        self._current_filename: str | None = None
        self._threshold_value = 95

        self.setObjectName("matchDetailPanel")
        self.setMinimumWidth(310)

        self._build_ui()

    # ── Public API ──────────────────────────────────────────────────────

    @property
    def current_entry_id(self) -> str | None:
        return self._current_entry_id

    @property
    def comparison_widget(self) -> QtWidgets.QWidget:
        return self._comparison

    @property
    def export_button(self) -> QtWidgets.QPushButton:
        return self._export_btn

    @property
    def generate_dat_button(self) -> QtWidgets.QPushButton:
        return self._generate_btn

    def show_entry(self, report_id: str, entry: ReviewEntry, system: str | None = None) -> None:
        """Display match details for *entry* in *report_id*."""
        self._current_report_id = report_id
        self._current_entry_id = entry.id
        self._current_system = system
        self._current_filename = entry.filename
        self._title_label.setText(entry.filename)

        # Build match info from DB lookup
        from minerva_db import MinervaDB
        db = MinervaDB()

        match_name = "—"
        match_region = "—"
        match_source = "—"
        match_size = "—"
        if entry.automatic_file_id is not None:
            items = db.get_files_by_ids([entry.automatic_file_id])
            if items:
                it = items[0]
                match_name = it.basename
                match_region = ", ".join(it.regions) if it.regions else "—"
                match_source = it.source_torrent or "—"
                match_size = f"{it.size / 1024 / 1024:.1f} MB"

        size_str = f"{entry.size / 1024 / 1024:.1f} MB" if entry.size else "—"
        method = entry.automatic_method or "none"
        confidence = f"{entry.automatic_confidence:.0%}" if entry.automatic_confidence is not None else "—"

        self._comparison_detail.setText(
            f"<table cellpadding='2'>"
            f"<tr><td><b>Resolution</b></td><td>{entry.resolution.value}</td></tr>"
            f"<tr><td><b>Decision</b></td><td>{entry.decision}</td></tr>"
            f"<tr><td><b>Method</b></td><td>{method}</td></tr>"
            f"<tr><td><b>Confidence</b></td><td>{confidence}</td></tr>"
            f"<tr><td><b>Matched file</b></td><td>{match_name}</td></tr>"
            f"<tr><td><b>Region</b></td><td>{match_region}</td></tr>"
            f"<tr><td><b>Source</b></td><td>{match_source}</td></tr>"
            f"<tr><td><b>Requested size</b></td><td>{size_str}</td></tr>"
            f"<tr><td><b>Actual size</b></td><td>{match_size}</td></tr>"
            f"</table>"
        )

        # Build candidates list
        candidates_html = self._build_candidates_html(db, entry, system)
        self._candidates_detail.setText(candidates_html)

        self._approve_btn.setEnabled(True)
        self._ignore_btn.setEnabled(True)

    def clear(self) -> None:
        """Clear the panel — no entry selected."""
        self._current_report_id = None
        self._current_entry_id = None
        self._current_system = None
        self._current_filename = None
        self._title_label.setText("Select an entry to review")
        self._comparison_detail.setText("No entry selected")
        self._candidates_detail.setText("No entry selected")
        self._approve_btn.setEnabled(False)
        self._ignore_btn.setEnabled(False)

    def approve_entry(self) -> None:
        """Approve the current entry — emit decision_changed with 'accept'."""
        if self._current_report_id and self._current_entry_id:
            self.decision_changed.emit(
                self._current_report_id, self._current_entry_id, "accept"
            )

    def ignore_entry(self) -> None:
        """Ignore the current entry — emit decision_changed with 'reject'."""
        if self._current_report_id and self._current_entry_id:
            self.decision_changed.emit(
                self._current_report_id, self._current_entry_id, "reject"
            )

    def approve_all_exact(self) -> None:
        """Bulk-approve all exact-match entries in the current report."""
        if self._current_report_id is None:
            return
        self.bulk_decision_requested.emit(self._current_report_id, "exact", 0)

    def approve_fuzzy_above_threshold(self, threshold: int) -> None:
        """Bulk-approve fuzzy matches above *threshold*% confidence."""
        if self._current_report_id is None:
            return
        self._threshold_value = threshold
        self.bulk_decision_requested.emit(self._current_report_id, "fuzzy", threshold)

    def build_cdromance_url(self, game_name: str, system: str | None = None) -> str:
        """Build a CDRomance search URL scoped to *system*."""
        slug = _SYSTEM_TO_CDR_SLUG.get(system or "")
        encoded = quote(game_name)
        if slug:
            return f"https://cdromance.org/{slug}/?s={encoded}"
        return f"https://cdromance.org/?s={encoded}"

    # ── UI construction ─────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ── Header ──────────────────────────────────────────────────────
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)
        heading = QtWidgets.QLabel("Match Detail")
        heading.setObjectName("sectionTitle")
        header.addWidget(heading)
        header.addStretch(1)
        root.addLayout(header)

        self._title_label = QtWidgets.QLabel("Select an entry to review")
        self._title_label.setObjectName("inspectorTitle")
        self._title_label.setWordWrap(True)
        root.addWidget(self._title_label)

        sep = QtWidgets.QFrame()
        sep.setObjectName("separator")
        sep.setFixedHeight(1)
        root.addWidget(sep)

        # ── Per-entry actions ───────────────────────────────────────────
        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(8)

        self._approve_btn = QtWidgets.QPushButton("Approve")
        self._approve_btn.setIcon(Icons.check())
        self._approve_btn.setObjectName("primaryButton")
        self._approve_btn.setFixedHeight(32)
        self._approve_btn.setEnabled(False)
        self._approve_btn.clicked.connect(self.approve_entry)
        action_row.addWidget(self._approve_btn)

        self._ignore_btn = QtWidgets.QPushButton("Ignore")
        self._ignore_btn.setIcon(Icons.skip())
        self._ignore_btn.setObjectName("secondaryButton")
        self._ignore_btn.setFixedHeight(32)
        self._ignore_btn.setEnabled(False)
        self._ignore_btn.clicked.connect(self.ignore_entry)
        action_row.addWidget(self._ignore_btn)

        self._cdr_btn = QtWidgets.QPushButton("CDRomance")
        self._cdr_btn.setIcon(Icons.search())
        self._cdr_btn.setObjectName("secondaryButton")
        self._cdr_btn.setFixedHeight(32)
        self._cdr_btn.clicked.connect(self._on_cdromance)
        action_row.addWidget(self._cdr_btn)

        action_row.addStretch(1)
        root.addLayout(action_row)

        # ── Comparison view ─────────────────────────────────────────────
        self._comparison = QtWidgets.QWidget()
        comp_layout = QtWidgets.QVBoxLayout(self._comparison)
        comp_layout.setContentsMargins(0, 0, 0, 0)
        comp_layout.setSpacing(8)
        self._comparison_title = QtWidgets.QLabel("Comparison")
        self._comparison_title.setObjectName("sectionTitle")
        comp_layout.addWidget(self._comparison_title)
        self._comparison_detail = QtWidgets.QLabel("No entry selected")
        self._comparison_detail.setObjectName("mutedLabel")
        self._comparison_detail.setWordWrap(True)
        comp_layout.addWidget(self._comparison_detail)

        self._candidates_title = QtWidgets.QLabel("Top candidates")
        self._candidates_title.setObjectName("sectionTitle")
        comp_layout.addWidget(self._candidates_title)

        self._candidates_detail = QtWidgets.QLabel("No entry selected")
        self._candidates_detail.setObjectName("mutedLabel")
        self._candidates_detail.setWordWrap(True)
        comp_layout.addWidget(self._candidates_detail)

        comp_layout.addStretch(1)
        root.addWidget(self._comparison, 1)

        # ── Bulk actions ────────────────────────────────────────────────
        bulk_sep = QtWidgets.QFrame()
        bulk_sep.setObjectName("separator")
        bulk_sep.setFixedHeight(1)
        root.addWidget(bulk_sep)

        bulk_label = QtWidgets.QLabel("Bulk actions")
        bulk_label.setObjectName("sectionTitle")
        root.addWidget(bulk_label)

        threshold_row = QtWidgets.QHBoxLayout()
        self._threshold_spin = QtWidgets.QSpinBox()
        self._threshold_spin.setRange(50, 100)
        self._threshold_spin.setValue(95)
        self._threshold_spin.setSuffix("% confidence")
        threshold_row.addWidget(self._threshold_spin)
        root.addLayout(threshold_row)

        bulk_btn_row1 = QtWidgets.QHBoxLayout()
        bulk_btn_row1.setSpacing(6)
        approve_exact_btn = QtWidgets.QPushButton("Approve exact")
        approve_exact_btn.setIcon(Icons.check())
        approve_exact_btn.setFixedHeight(28)
        approve_exact_btn.clicked.connect(self.approve_all_exact)
        bulk_btn_row1.addWidget(approve_exact_btn)

        approve_fuzzy_btn = QtWidgets.QPushButton("Approve fuzzy")
        approve_fuzzy_btn.setIcon(Icons.status_warning())
        approve_fuzzy_btn.setFixedHeight(28)
        approve_fuzzy_btn.clicked.connect(
            lambda: self.approve_fuzzy_above_threshold(self._threshold_spin.value())
        )
        bulk_btn_row1.addWidget(approve_fuzzy_btn)
        root.addLayout(bulk_btn_row1)

        # ── Export / Generate ────────────────────────────────────────────
        export_row = QtWidgets.QHBoxLayout()
        export_row.setSpacing(6)
        self._export_btn = QtWidgets.QPushButton("Export")
        self._export_btn.setIcon(Icons.download())
        self._export_btn.setFixedHeight(28)
        export_row.addWidget(self._export_btn)

        self._generate_btn = QtWidgets.QPushButton("Generate DAT")
        self._generate_btn.setIcon(Icons.file())
        self._generate_btn.setFixedHeight(28)
        export_row.addWidget(self._generate_btn)
        root.addLayout(export_row)

        root.addStretch(1)

    # ── Candidates helper ──────────────────────────────────────────────────

    def _build_candidates_html(self, db, entry: ReviewEntry, system: str | None) -> str:
        """Build HTML showing top match candidates."""
        from minerva_db import DatEntry

        dat = DatEntry(filename=entry.filename, size=entry.size)
        scope_system = system or ""
        results = db.match_dat_detailed([dat], collection="", system=scope_system, candidate_limit=5)

        if not results.get("results"):
            return "No candidates found"

        candidates = results["results"][0].get("candidates", [])
        if not candidates:
            return "No candidates found"

        # Get regions for all candidates
        file_ids = [c["file_id"] for c in candidates]
        regions_map = db.get_file_regions(file_ids)

        rows = []
        for c in candidates:
            fid = c["file_id"]
            conf = c.get("confidence", 0)
            method = c.get("method", "?")
            title = c.get("title", "—")
            regions = regions_map.get(fid, [])
            region_str = ", ".join(regions) if regions else "—"
            is_selected = fid == entry.automatic_file_id
            marker = "▶ " if is_selected else "  "
            conf_str = f"{conf:.0%}"
            style = "font-weight:bold;" if is_selected else ""
            rows.append(
                f"<tr style='{style}'><td>{marker}</td>"
                f"<td>{title[:50]}</td><td>{conf_str}</td>"
                f"<td>{method}</td><td>{region_str}</td></tr>"
            )

        return (
            "<table cellpadding='2' width='100%'>"
            "<tr><td></td><td><b>Title</b></td><td><b>Conf</b></td>"
            "<td><b>Method</b></td><td><b>Region</b></td></tr>"
            + "".join(rows) + "</table>"
        )

    # ── CDRomance search ────────────────────────────────────────────────

    def _on_cdromance(self) -> None:
        """Open CDRomance search in the browser."""
        if self._current_entry_id is None:
            return
        # Use the entry filename for the search query
        search_name = getattr(self, "_current_filename", None) or self._current_entry_id
        url = self.build_cdromance_url(
            search_name,
            self._current_system,
        )
        webbrowser.open(url)
