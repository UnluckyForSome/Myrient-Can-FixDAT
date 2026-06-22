"""Reference-quality reports dashboard with navigator, workspace and inspector."""

from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from minerva.app.app_state import AppState
from minerva.app.pages.base import BasePage
from minerva.ui.theme import ThemeTokens
from minerva.ui.widgets.content_state import ContentState
from minerva.ui.widgets.metric_card import MetricCard, MetricKind
from minerva.ui.widgets.metric_strip import MetricStrip
from minerva.ui.widgets.notification_banner import NotificationBanner
from minerva.ui.widgets.page_header import PageHeader
from minerva.ui.widgets.report_navigator import ReportNavigator
from minerva.ui.widgets.responsive_workspace import ResponsiveWorkspace
from minerva.ui.widgets.segmented_control import SegmentedControl
from minerva.ui.widgets.status_badge import BadgeKind, StatusBadge
from minerva.ui.widgets.surface_panel import SurfacePanel
from minerva.ui.widgets.property_list import PropertyList
from minerva.ui.widgets.match_detail_panel import MatchDetailPanel
from minerva.app.task_runner import TaskRunner
from minerva.services.report_acquisition import ReportAcquisitionService
from minerva.domain.reports import ReportSummary, ReviewEntry
from minerva.ui.icons import Icons
from minerva.ui.models.delegates import DisplayDelegate, SizeDelegate
from minerva.ui.models.record_model import ColumnSpec, RecordListModel
from minerva.ui.widgets.empty_state import EmptyState
from minerva_db import DatEntry, MinervaDB, parse_dat_file, parse_rv_fix_csv
from minerva_state import MinervaState

log = logging.getLogger(__name__)


class ReportsPageState(enum.Enum):
    EMPTY = "empty"
    LOADING = "loading"
    RESULTS = "results"
    ERROR = "error"


@dataclass(frozen=True)
class ReportEntryView:
    entry: ReviewEntry
    best_match: str = ""
    collection: str = ""
    system: str = ""

    @property
    def category(self) -> str:
        if self.entry.automatic_method == "exact":
            return "exact"
        if self.entry.automatic_method in {"fts5", "trigram", "keyword", "fuzzy"}:
            return "fuzzy"
        return "unmatched"


_ENTRY_COLUMNS: list[ColumnSpec[ReportEntryView]] = [
    ColumnSpec("Requested title", lambda row: row.entry.filename),
    ColumnSpec("Proposed match", lambda row: row.best_match or "No suggested match"),
    ColumnSpec(
        "Confidence",
        lambda row: row.entry.automatic_confidence,
        format_fn=lambda value: f"{value:.0%}" if value is not None else "\u2014",
    ),
    ColumnSpec("Match", lambda row: row.entry.automatic_method or "none"),
    ColumnSpec("Size", lambda row: row.entry.size),
    ColumnSpec("Decision", lambda row: row.entry.decision),
]


class _EntryFilter(QtCore.QSortFilterProxyModel):
    """Filter entries by decision-based segments and text.

    Segments: all | pending | approved | ignored
    "approved" covers both accept and fuzzy decisions.
    "ignored" covers reject decisions.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.category = "all"
        self.decision = "all"
        self.text = ""

    def filterAcceptsRow(self, source_row, source_parent):  # noqa: N802
        model = self.sourceModel()
        if model is None:
            return True
        row = model._records[source_row]  # noqa: SLF001
        if self.category != "all":
            raw_decision = (row.entry.decision or "pending").lower()
            if self.category == "pending":
                if raw_decision != "pending":
                    return False
            elif self.category == "approved":
                if raw_decision not in {"accept", "fuzzy"}:
                    return False
            elif self.category == "ignored":
                if raw_decision != "reject":
                    return False
        if self.decision != "all":
            raw = (row.entry.decision or "pending").lower()
            if raw != self.decision:
                return False
        if self.text:
            needle = self.text.casefold()
            return needle in row.entry.filename.casefold() or needle in row.best_match.casefold()
        return True


class _ConfidenceDelegate(QtWidgets.QStyledItemDelegate):
    """Compact confidence bar that remains legible in a dense table."""

    def __init__(self, tokens: ThemeTokens = ThemeTokens(), parent=None) -> None:
        super().__init__(parent)
        self._tokens = tokens

    def paint(self, painter, option, index) -> None:
        style = option.widget.style() if option.widget else QtWidgets.QApplication.style()
        style.drawPrimitive(QtWidgets.QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget)
        value = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(value, (float, int)):
            painter.save()
            painter.setPen(QtGui.QColor(self._tokens.text_muted))
            painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, "\u2014")
            painter.restore()
            return
        value = max(0.0, min(1.0, float(value)))
        painter.save()
        rect = option.rect.adjusted(10, 12, -10, -12)
        track = QtCore.QRect(rect.left(), rect.center().y() + 5, rect.width(), 4)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(self._tokens.surface_raised))
        painter.drawRoundedRect(track, 2, 2)
        fill = QtCore.QRect(track.left(), track.top(), int(track.width() * value), track.height())
        painter.setBrush(QtGui.QColor(self._tokens.success if value >= 0.95 else self._tokens.accent))
        painter.drawRoundedRect(fill, 2, 2)
        painter.setPen(QtGui.QColor(self._tokens.text))
        painter.drawText(
            QtCore.QRect(rect.left(), option.rect.top(), rect.width(), 24),
            Qt.AlignmentFlag.AlignCenter,
            f"{value:.0%}",
        )
        painter.restore()


class _PillDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, kind: str, tokens: ThemeTokens = ThemeTokens(), parent=None) -> None:
        super().__init__(parent)
        self._kind = kind
        self._tokens = tokens

    def paint(self, painter, option, index) -> None:
        style = option.widget.style() if option.widget else QtWidgets.QApplication.style()
        style.drawPrimitive(QtWidgets.QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget)
        raw = str(index.data(Qt.ItemDataRole.UserRole) or "").casefold()
        label, fg, bg = self._style(raw)
        painter.save()
        font = QtGui.QFont(option.font)
        font.setPointSize(max(9, option.font.pointSize() - 1))
        font.setBold(True)
        painter.setFont(font)
        fm = QtGui.QFontMetrics(font)
        width = min(option.rect.width() - 12, fm.horizontalAdvance(label) + 18)
        rect = QtCore.QRect(
            option.rect.center().x() - width // 2,
            option.rect.center().y() - 11,
            width,
            22,
        )
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(bg))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QtGui.QColor(fg))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    def _style(self, value: str) -> tuple[str, str, str]:
        if self._kind == "method":
            if value == "exact":
                return "Exact", self._tokens.success, self._tokens.success_bg
            if value in {"fts5", "trigram", "keyword", "fuzzy"}:
                return "Fuzzy", self._tokens.accent, self._tokens.info_bg
            if value == "manual":
                return "Manual", self._tokens.purple, self._tokens.purple_bg
            return "None", self._tokens.text_muted, self._tokens.surface_raised
        if value in {"accept", "approved"}:
            return "Approved", self._tokens.success, self._tokens.success_bg
        if value in {"reject", "ignored"}:
            return "Ignored", self._tokens.warning, self._tokens.warning_bg
        if value == "fuzzy":
            return "Approved", self._tokens.accent, self._tokens.info_bg
        return "Pending", self._tokens.text_muted, self._tokens.surface_raised


def _match_task(
    generation: int,
    entries: list[dict],
    collection: str,
    system: str,
) -> tuple[int, dict]:
    db = MinervaDB()
    values = [DatEntry(filename=item["filename"], size=item["size"]) for item in entries]
    return generation, db.match_dat_detailed(values, collection=collection, system=system)


def _rematch_json_task(report_id: str) -> dict:
    """Run rematch for a JSON (library) report in a worker thread."""
    from minerva.services.report_acquisition import ReportAcquisitionService as _Svc

    svc = _Svc(state=MinervaState())
    counts = svc.match_report(report_id)
    return {
        "report_id": report_id,
        "ready": counts.ready,
        "review_required": counts.review_required,
        "not_found": counts.not_found,
    }


class ReportsPage(BasePage):
    """Reference-quality reports dashboard with navigator, workspace and inspector."""

    def __init__(self, app_state: AppState) -> None:
        super().__init__(app_state)
        self.setObjectName("pageSurface")
        self._pool = QtCore.QThreadPool.globalInstance()
        self._generation = 0
        self._selected_report_id: str | None = None
        self._updating = False  # ponytail: guard for signal recursion

        self._entry_model = RecordListModel([], _ENTRY_COLUMNS, self)
        self._entry_proxy = _EntryFilter(self)
        self._entry_proxy.setSourceModel(self._entry_model)
        self._entry_view = self._build_entry_view()

        # ── Header ──────────────────────────────────────────────────────
        self._header = PageHeader(
            "Reports",
            "Import and review repair reports",
        )
        self._import_btn = self._header.add_action("Add report", Icons.add(), primary=True)
        self._rematch_btn = self._header.add_action("Match again", Icons.refresh())
        self._queue_all_btn = self._header.add_action("Queue all ready", Icons.download())
        self._delete_btn = self._header.add_action("Remove", Icons.trash(), danger=True)
        self._rematch_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)
        self._queue_all_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._on_import)
        self._rematch_btn.clicked.connect(self._rematch_selected)
        self._queue_all_btn.clicked.connect(self._queue_all_ready)
        self._delete_btn.clicked.connect(self._delete_selected)

        # ── KPI strip ──────────────────────────────────────────────────
        self._card_requested = MetricCard(
            "Total requested", "0", icon=Icons.file(), subtitle="Select a report",
        )
        self._card_pending = MetricCard(
            "Pending review", "0", MetricKind.WARNING, icon=Icons.status_warning(),
            subtitle="",
        )
        self._card_matched = MetricCard(
            "Matched", "0", MetricKind.SUCCESS, icon=Icons.status_success(),
            subtitle="0 exact \xb7 0 fuzzy",
        )
        self._card_unmatched = MetricCard(
            "Unmatched", "0", MetricKind.INFO, icon=Icons.chart(),
            subtitle="Nothing outstanding",
        )
        self._metric_strip = MetricStrip([
            self._card_requested,
            self._card_pending,
            self._card_matched,
            self._card_unmatched,
        ])

        # ── Navigator (left) ───────────────────────────────────────────
        self._navigator = ReportNavigator()
        self._report_model = self._navigator.model
        self._report_view = self._navigator.view
        self._navigator.current_report_changed.connect(self._on_report_selected)
        self._navigator.report_activated.connect(lambda _report: self._review_selected())
        self._navigator.context_menu_requested.connect(self._show_report_menu)

        # ── Center panel: SurfacePanel with search + filters + table ───
        self._surface_panel = SurfacePanel("Reports")

        # Search bar (compact, single-line)
        self._search = QtWidgets.QLineEdit()
        self._search.setObjectName("reportSearch")
        self._search.setPlaceholderText("Search requested titles or proposed matches\u2026")
        self._search.setClearButtonEnabled(True)
        self._search.addAction(Icons.search(), QtWidgets.QLineEdit.ActionPosition.LeadingPosition)
        self._search.textChanged.connect(self._set_entry_text_filter)
        self._surface_panel.body_layout.addWidget(self._search)

        # Filter row: segments + decision dropdown + count
        filter_row = QtWidgets.QWidget()
        filter_row_layout = QtWidgets.QHBoxLayout(filter_row)
        filter_row_layout.setContentsMargins(0, 0, 0, 0)
        filter_row_layout.setSpacing(8)

        self._segments = SegmentedControl([
            ("all", "All"),
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("ignored", "Ignored"),
        ])
        self._segments.current_changed.connect(self._set_entry_category)
        filter_row_layout.addWidget(self._segments)
        filter_row_layout.addStretch(1)

        self._decision_filter = QtWidgets.QComboBox()
        self._decision_filter.setObjectName("reportFilterCombo")
        self._decision_filter.addItem("Any decision", "all")
        self._decision_filter.addItem("Pending", "pending")
        self._decision_filter.addItem("Approved", "accept")
        self._decision_filter.addItem("Ignored", "reject")
        self._decision_filter.addItem("Fuzzy approved", "fuzzy")
        self._decision_filter.currentIndexChanged.connect(self._on_decision_filter)
        self._decision_filter.setMinimumWidth(120)
        filter_row_layout.addWidget(self._decision_filter)

        self._result_count = QtWidgets.QLabel("0 results")
        self._result_count.setObjectName("resultsCount")
        filter_row_layout.addWidget(self._result_count)

        self._surface_panel.body_layout.addWidget(filter_row)
        self._surface_panel.body_layout.addWidget(self._entry_view, 1)

        # ── Inspector (right): MatchDetailPanel replacing InspectorScaffold ─
        self._match_detail = MatchDetailPanel(app_state)
        self._match_detail.decision_changed.connect(self._on_decision_changed)
        self._match_detail.bulk_decision_requested.connect(self._on_bulk_decision)

        # Queue approved button — single action replacing dual queue mechanisms
        self._queue_approved_btn = QtWidgets.QPushButton("Queue approved")
        self._queue_approved_btn.setIcon(Icons.download())
        self._queue_approved_btn.setObjectName("accentButton")
        self._queue_approved_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._queue_approved_btn.clicked.connect(self._queue_approved)
        self._match_detail.layout().addWidget(self._queue_approved_btn)

        # Discovery aliases: detail panel + download/export button.
        self._detail_widget = self._match_detail
        self._inspector = self._match_detail  # ponytail: backward compat for existing refs

        # ── Responsive workspace ────────────────────────────────────────
        self._workspace = ResponsiveWorkspace(
            self._navigator, self._surface_panel, self._match_detail,
        )

        # ── State stack ─────────────────────────────────────────────────────────
        self._empty_state = EmptyState(
            icon=Icons.file(),
            title="No reports imported",
            description="Drop a FixDAT or CSV here, or choose Add report to start matching.",
            action_text="Add report",
        )
        self._empty_state.action_clicked.connect(self._on_import)
        self._no_index_state = EmptyState(
            icon=Icons.search(),
            title="Index not built",
            description="Build the torrent index to enable matching.",
            action_text="Build Index",
        )
        self._no_index_state.action_clicked.connect(self._rebuild_index)
        self._no_qbit_state = EmptyState(
            icon=Icons.status_warning(),
            title="Can't reach qBittorrent",
            description="Check your qBittorrent connection settings.",
            action_text="Open Settings",
        )
        self._no_qbit_state.action_clicked.connect(self._open_settings)
        self._loading_state = EmptyState(
            icon=Icons.refresh(),
            title="Importing and matching",
            description="Analysing entries and searching the index for candidates.",
        )
        self._error_state = EmptyState(
            icon=Icons.status_error(),
            title="Report operation failed",
            description="",
            action_text="Retry",
        )
        self._error_state.action_clicked.connect(self.refresh)

        self._state = ContentState()
        self._state.set_content(self._build_content_widget())
        self._state.set_empty(self._empty_state)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        root.addWidget(self._header)
        root.addWidget(self._state, 1)

    # ── Table construction ──────────────────────────────────────────────

    def _build_entry_view(self) -> QtWidgets.QTableView:
        view = QtWidgets.QTableView()
        view.setObjectName("reportEntries")
        view.setModel(self._entry_proxy)
        view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        view.setAlternatingRowColors(True)
        view.setShowGrid(False)
        view.setWordWrap(False)
        view.verticalHeader().hide()
        view.verticalHeader().setDefaultSectionSize(36)  # compact rows
        view.horizontalHeader().setHighlightSections(False)
        view.horizontalHeader().setStretchLastSection(False)
        view.setItemDelegate(DisplayDelegate(view))
        view.setItemDelegateForColumn(2, _ConfidenceDelegate(parent=view))
        view.setItemDelegateForColumn(3, _PillDelegate("method", parent=view))
        view.setItemDelegateForColumn(4, SizeDelegate(view))
        view.setItemDelegateForColumn(5, _PillDelegate("decision", parent=view))
        # Column ratios: title/match get stretch, others fixed width
        view.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        view.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for column, width in {2: 100, 3: 82, 4: 86, 5: 94}.items():
            view.horizontalHeader().setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.Fixed)
            view.setColumnWidth(column, width)
        view.doubleClicked.connect(lambda _index: self._review_selected())
        view.selectionModel().selectionChanged.connect(self._on_entry_selection_changed)
        return view

    # ── State management ────────────────────────────────────────────────

    def _set_state(self, state: ReportsPageState) -> None:
        if state == ReportsPageState.EMPTY:
            self._state.set_empty(self._empty_state)
        elif state == ReportsPageState.LOADING:
            self._state.set_loading("Importing and matching\u2026")
        elif state == ReportsPageState.ERROR:
            self._state.set_error("")
        elif state == ReportsPageState.RESULTS:
            if self._state.currentIndex() != 3:
                content = self._build_content_widget()
                self._state.set_content(content)

    def _build_content_widget(self) -> QtWidgets.QWidget:
        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)
        content_layout.addWidget(self._metric_strip)
        content_layout.addWidget(self._workspace, 1)
        return content

    def activate(self) -> None:
        self.refresh()
        self._wire_signals()
        self._wire_shortcuts()

    def _wire_signals(self) -> None:
        """Subscribe to ReportStore signals with _updating guard."""
        self._app_state.reports.report_updated.connect(self._on_report_updated)
        self._app_state.reports.entries_updated.connect(self._on_entries_updated)

    def _wire_shortcuts(self) -> None:
        """Add keyboard shortcuts A/I/Space/Q/Ctrl+O/Ctrl+F/Esc."""
        from PyQt6 import QtGui

        shortcuts = [
            ("A", self._shortcut_approve),
            ("I", self._shortcut_ignore),
            ("Space", self._shortcut_toggle),
            ("Q", self._shortcut_queue),
            ("Ctrl+O", self._on_import),
            ("Ctrl+F", self._shortcut_focus_search),
            ("Esc", self._shortcut_deselect),
        ]
        for key, callback in shortcuts:
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), self)
            shortcut.activated.connect(callback)

    # ── Signal handlers with _updating guard ────────────────────────────

    def _on_report_updated(self, report_id: str) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            if report_id == self._selected_report_id:
                self._on_report_selected(None)  # force refresh
        finally:
            self._updating = False

    def _on_entries_updated(self, report_id: str) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            if report_id == self._selected_report_id:
                self._refresh_entry_data()
        finally:
            self._updating = False

    def _on_decision_changed(self, report_id: str, entry_id: str, decision: str) -> None:
        """Handle decision change from MatchDetailPanel."""
        if self._updating:
            return
        self._updating = True
        try:
            MinervaState().set_entry_decision(report_id, entry_id, decision)
            self._refresh_entry_data()
            # Auto-advance: check if all entries reviewed
            self._check_review_complete(report_id)
        finally:
            self._updating = False

    def _on_bulk_decision(self, report_id: str, filter_type: str, threshold: int) -> None:
        """Handle bulk approve from MatchDetailPanel."""
        if self._updating:
            return
        self._updating = True
        try:
            entries = MinervaState().get_entries(report_id)
            decision = "accept" if filter_type == "exact" else "fuzzy"
            updated = 0
            for entry in entries:
                if entry.decision != "pending":
                    continue
                method = (entry.automatic_method or "").lower()
                if filter_type == "exact" and method == "exact":
                    MinervaState().set_entry_decision(report_id, entry.entry_id, decision)
                    updated += 1
                elif filter_type == "fuzzy" and method in {"fts5", "trigram", "keyword", "fuzzy"}:
                    conf = entry.automatic_confidence or 0
                    if conf * 100 >= threshold:
                        MinervaState().set_entry_decision(report_id, entry.entry_id, decision)
                        updated += 1
            if updated > 0:
                self._refresh_entry_data()
                self._check_review_complete(report_id)
                NotificationBanner.show_success(
                    self, "Bulk approve",
                    f"{updated} {filter_type} entries approved",
                )
        finally:
            self._updating = False

    def _check_review_complete(self, report_id: str) -> None:
        """Show actionable toast when all entries in a report have been reviewed."""
        try:
            entries = MinervaState().get_entries(report_id)
            pending = sum(1 for e in entries if e.decision == "pending")
            if pending == 0 and len(entries) > 0:
                approved = sum(1 for e in entries if e.decision in {"accept", "fuzzy"})
                if approved > 0:
                    from minerva.ui.notifications import NotificationService
                    ns = NotificationService(self)
                    ns.action(
                        "Review complete",
                        f"Queue {approved} approved entries?",
                        "Queue",
                        self._queue_approved,
                    )
        except Exception:
            log.debug("Failed to check review completion", exc_info=True)

    # ── Keyboard shortcut handlers ──────────────────────────────────────

    def _shortcut_approve(self) -> None:
        if self._selected_report_id:
            indexes = self._entry_view.selectionModel().selectedRows()
            for idx in indexes:
                source = self._entry_proxy.mapToSource(idx)
                row = self._entry_model._records[source.row()]  # noqa: SLF001
                self._on_decision_changed(
                    self._selected_report_id, row.entry.entry_id, "accept"
                )

    def _shortcut_ignore(self) -> None:
        if self._selected_report_id:
            indexes = self._entry_view.selectionModel().selectedRows()
            for idx in indexes:
                source = self._entry_proxy.mapToSource(idx)
                row = self._entry_model._records[source.row()]  # noqa: SLF001
                self._on_decision_changed(
                    self._selected_report_id, row.entry.entry_id, "reject"
                )

    def _shortcut_toggle(self) -> None:
        """Toggle between approve and ignore for selected entry."""
        if self._selected_report_id:
            indexes = self._entry_view.selectionModel().selectedRows()
            for idx in indexes:
                source = self._entry_proxy.mapToSource(idx)
                row = self._entry_model._records[source.row()]  # noqa: SLF001
                current = (row.entry.decision or "pending").lower()
                new_decision = "reject" if current in {"accept", "fuzzy"} else "accept"
                self._on_decision_changed(
                    self._selected_report_id, row.entry.entry_id, new_decision
                )

    def _shortcut_queue(self) -> None:
        self._queue_approved()

    def _shortcut_focus_search(self) -> None:
        self._search.setFocus()

    def _shortcut_deselect(self) -> None:
        self._entry_view.clearSelection()
        self._match_detail.clear()

    def _rebuild_index(self) -> None:
        """Rebuild the torrent index from configured torrent directory."""
        try:
            from minerva_db import build_index
            build_index()
            NotificationBanner.show_success(self, "Index rebuilt", "Torrent index is now up to date")
            self.refresh()
        except Exception as exc:
            NotificationBanner.show_error(self, "Index build failed", str(exc))

    def _open_settings(self) -> None:
        """Navigate to the Settings page."""
        shell = self.window()
        from minerva.app.page_id import PageId
        if hasattr(shell, "show_page"):
            shell.show_page(PageId.SETTINGS)

    def _refresh_entry_data(self) -> None:
        """Reload entry data for the currently selected report."""
        if self._selected_report_id is None:
            return
        try:
            entries = MinervaState().get_entries(self._selected_report_id)
            self._set_entry_data(entries)
        except Exception:
            log.debug("Failed to refresh entry data", exc_info=True)

    def refresh(self) -> None:
        try:
            reports = MinervaState().list_reports()
        except Exception as exc:
            self._error_state.set_description(str(exc))
            self._set_state(ReportsPageState.ERROR)
            return
        self._navigator.set_reports(reports, self._selected_report_id)
        self._queue_all_btn.setEnabled(bool(reports))
        self._set_state(ReportsPageState.RESULTS if reports else ReportsPageState.EMPTY)
        if not reports:
            self._show_report(None)

    # ── Import / match ──────────────────────────────────────────────────

    def _on_import(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Import fix reports", "", "Fix reports (*.dat *.csv *.json);;All files (*)",
        )
        for path in paths:
            if path.suffix.lower() == ".json":
                self._import_library_report(path)
            else:
                self._import_file(Path(path))

    def _import_library_report(self, path: Path, report_id: str | None = None) -> None:
        """Import a romresolve library-report JSON and refresh the list.

        Creates one report per platform_id, each scoped to the matching
        Minerva system for accurate matching.
        """
        try:
            state = MinervaState()
            svc = ReportAcquisitionService(state=state)
            reports = svc.import_library_report(path, report_id=report_id)
            if reports:
                self._selected_report_id = reports[0].id
            self.refresh()
        except Exception as exc:
            self._error_state.set_description(str(exc))
            self._set_state(ReportsPageState.ERROR)

    def _import_file(self, path: Path, report_id: str | None = None) -> None:
        clean_name = path.name.split("#")[0]
        if clean_name.lower().endswith(".json"):
            self._import_library_report(path, report_id)
            return
        try:
            info = parse_rv_fix_csv(path) if path.suffix.lower() == ".csv" else parse_dat_file(path)
            if not info.entries:
                NotificationBanner.show_warning(self, "Empty report", str(path))
                return
            state = MinervaState()
            existing = state.get_report_by_path(path)
            if existing and report_id is None:
                reply = QtWidgets.QMessageBox.question(
                    self, "Reimport report",
                    f'"{existing.name}" is already imported. Replace its matching results?',
                )
                if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                    return
                report_id = existing.id
            report_id = report_id or uuid.uuid4().hex
            report = ReportSummary(
                id=report_id,
                path=str(path),
                name=info.name or path.stem,
                collection=info.collection,
                system=info.system,
                imported_at=datetime.now(timezone.utc).isoformat(),
                requested_count=len(info.entries),
                status="matching",
            )
            if existing:
                state.update_report(
                    report_id,
                    name=report.name, collection=report.collection, system=report.system,
                    requested_count=report.requested_count, status="matching",
                )
            else:
                state.save_report(report)
            self._selected_report_id = report_id
            self._set_state(ReportsPageState.LOADING)
            self._generation += 1
            gen = self._generation
            task = TaskRunner(
                _match_task, gen,
                [{"filename": entry.filename, "size": entry.size} for entry in info.entries],
                info.collection or "", info.system or "",
            )
            task.signals.result.connect(lambda payload, rid=report_id: self._on_match_result(gen, rid, payload))
            task.signals.error.connect(lambda details, rid=report_id: self._on_match_error(gen, rid, details))
            self._pool.start(task)
        except Exception as exc:
            self._error_state.set_description(str(exc))
            self._set_state(ReportsPageState.ERROR)

    def _on_match_result(self, generation: int, report_id: str, payload: object) -> None:
        if generation != self._generation:
            return
        _returned_gen, match_result = payload  # type: ignore[misc]
        results_list = match_result["results"]
        summary = match_result["summary"]
        state = MinervaState()
        entries: list[ReviewEntry] = []
        for ordinal, result in enumerate(results_list):
            entry: DatEntry = result["entry"]
            entries.append(ReviewEntry(
                id=f"{report_id}_{ordinal}",
                report_id=report_id,
                ordinal=ordinal,
                filename=entry.filename,
                size=entry.size,
                automatic_file_id=result.get("automatic_file_id"),
                automatic_method=result.get("automatic_method"),
                automatic_confidence=result.get("automatic_confidence"),
                decision="pending",
            ))
        state.save_entries(entries)
        state.update_report(
            report_id,
            matched_count=summary["exact"],
            fuzzy_count=summary["fuzzy"],
            unmatched_count=summary["unmatched"],
            status="ready",
        )
        state.add_event(
            "match",
            f"Matched report {report_id}: {summary['exact']} exact, "
            f"{summary['fuzzy']} fuzzy, {summary['unmatched']} unmatched",
        )
        self.refresh()

    def _on_match_error(self, generation: int, report_id: str, details: str) -> None:
        if generation != self._generation:
            return
        self._error_state.set_description(details)
        self._set_state(ReportsPageState.ERROR)

    def _on_rematch_result(self, generation: int, report_id: str, payload: dict) -> None:
        if generation != self._generation:
            return
        self.refresh()

    # ── Report selection ────────────────────────────────────────────────

    def _on_report_selected(self, report: ReportSummary | None) -> None:
        self._selected_report_id = report.id if report else None
        self._show_report(report)

    def _on_entry_selection_changed(self) -> None:
        """Update MatchDetailPanel when an entry row is selected."""
        indexes = self._entry_view.selectionModel().selectedRows()
        if not indexes or self._selected_report_id is None:
            self._match_detail.clear()
            return
        source = self._entry_proxy.mapToSource(indexes[0])
        row = self._entry_model._records[source.row()]  # noqa: SLF001
        self._match_detail.show_entry(self._selected_report_id, row.entry, row.system)

    def _show_report(self, report: ReportSummary | None) -> None:
        enabled = report is not None
        self._rematch_btn.setEnabled(enabled)
        self._delete_btn.setEnabled(enabled)
        self._queue_approved_btn.setEnabled(enabled)

        if report is None:
            self._entry_model.set_records([])
            self._segments.set_counts({"all": 0, "pending": 0, "approved": 0, "ignored": 0})
            self._result_count.setText("0 results")
            self._surface_panel.clear_count()
            self._clear_inspector()
            self._card_requested.set_value("0")
            self._card_requested.set_subtitle("Select a report")
            self._card_pending.set_value("0")
            self._card_pending.set_subtitle("")
            self._card_matched.set_value("0")
            self._card_matched.set_subtitle("0 exact \xb7 0 fuzzy")
            self._card_unmatched.set_value("0")
            self._card_unmatched.set_subtitle("Nothing outstanding")
            return

        entries = MinervaState().get_entries(report.id)
        ids = [entry.automatic_file_id for entry in entries if entry.automatic_file_id]
        item_map = {item.id: item for item in MinervaDB().get_files_by_ids(ids)} if ids else {}
        rows = [
            ReportEntryView(
                entry=entry,
                best_match=item_map[entry.automatic_file_id].stem if entry.automatic_file_id in item_map else "",
                collection=item_map[entry.automatic_file_id].collection if entry.automatic_file_id in item_map else "",
                system=item_map[entry.automatic_file_id].system if entry.automatic_file_id in item_map else "",
            )
            for entry in entries
        ]
        self._entry_model.set_records(rows)
        counts = {
            "all": len(rows),
            "pending": sum(row.entry.decision == "pending" for row in rows),
            "approved": sum(row.entry.decision in {"accept", "fuzzy"} for row in rows),
            "ignored": sum(row.entry.decision == "reject" for row in rows),
        }
        self._segments.set_counts(counts)
        self._surface_panel.set_count(len(rows))
        self._update_visible_count()

        matched = report.matched_count + report.fuzzy_count
        pending_count = sum(1 for e in entries if e.decision == "pending")
        self._card_requested.set_value(f"{report.requested_count:,}")
        self._card_requested.set_subtitle("Selected report")
        self._card_pending.set_value(f"{pending_count:,}")
        self._card_pending.set_subtitle("All reviewed" if not pending_count else f"{pending_count:,} pending")
        self._card_matched.set_value(f"{matched:,}")
        self._card_matched.set_subtitle(f"{report.matched_count:,} exact \xb7 {report.fuzzy_count:,} fuzzy")
        self._card_unmatched.set_value(f"{report.unmatched_count:,}")
        self._card_unmatched.set_subtitle("Requires review" if report.unmatched_count else "Nothing outstanding")

        self._update_inspector(report, entries)

    # ── Inspector helpers ───────────────────────────────────────────────

    def _clear_inspector(self) -> None:
        """Reset the match detail panel to a clean 'no selection' state."""
        self._match_detail.clear()

    def _update_inspector(self, report: ReportSummary, entries: list[ReviewEntry]) -> None:
        """Update match detail panel with report context."""
        # Update segment counts with decision-based values
        counts = {
            "all": len(entries),
            "pending": sum(1 for e in entries if e.decision == "pending"),
            "approved": sum(1 for e in entries if e.decision in {"accept", "fuzzy"}),
            "ignored": sum(1 for e in entries if e.decision == "reject"),
        }
        self._segments.set_counts(counts)

    def _status_kind(self, status: str) -> BadgeKind:
        value = (status or "").lower()
        if value in {"ready", "reviewed"}:
            return BadgeKind.SUCCESS
        if value == "matching":
            return BadgeKind.INFO
        if value == "failed":
            return BadgeKind.ERROR
        if value in {"draft", "pending"}:
            return BadgeKind.WARNING
        return BadgeKind.NEUTRAL

    # ── Filtering ───────────────────────────────────────────────────────

    def _set_entry_category(self, category: str) -> None:
        self._entry_proxy.category = category
        self._entry_proxy.invalidateFilter()
        self._update_visible_count()

    def _on_decision_filter(self, index: int) -> None:
        self._entry_proxy.decision = self._decision_filter.itemData(index) or "all"
        self._entry_proxy.invalidateFilter()
        self._update_visible_count()

    def _set_entry_text_filter(self, text: str) -> None:
        self._entry_proxy.text = text.strip()
        self._entry_proxy.invalidateFilter()
        self._update_visible_count()

    def _update_visible_count(self) -> None:
        count = self._entry_proxy.rowCount()
        self._result_count.setText(f"{count:,} result" if count == 1 else f"{count:,} results")

    # ── Actions ─────────────────────────────────────────────────────────

    def _selected_report(self) -> ReportSummary | None:
        return self._navigator.current_report()

    def _rematch_selected(self) -> None:
        report = self._selected_report()
        if report is None:
            return
        path = Path(report.path)
        # Strip URL-style fragment (#platform-id) before checking suffix
        clean_name = path.name.split("#")[0]
        if clean_name.lower().endswith(".json"):
            # Romresolve library report — entries already saved,
            # re-run matching in a worker thread.
            self._set_state(ReportsPageState.LOADING)
            self._generation += 1
            gen = self._generation
            task = TaskRunner(_rematch_json_task, report.id)
            task.signals.result.connect(lambda payload, rid=report.id: self._on_rematch_result(gen, rid, payload))
            task.signals.error.connect(lambda details, rid=report.id: self._on_match_error(gen, rid, details))
            self._pool.start(task)
            return
        self._import_file(path, report_id=report.id)

    def _queue_all_ready(self) -> None:
        """Queue ready entries from every report at once."""
        try:
            self._set_state(ReportsPageState.LOADING)
            svc = ReportAcquisitionService(state=MinervaState())
            result = svc.queue_all_ready()
            NotificationBanner.show_success(
                self,
                "Queue updated",
                f"Queued {result.added} ROMs "
                f"({result.skipped_active} already active, "
                f"{result.skipped_missing} missing).",
            )
            self.refresh()
        except Exception as exc:
            self._error_state.set_description(str(exc))
            self._set_state(ReportsPageState.ERROR)

    def _review_selected(self) -> None:
        """Focus the MatchDetailPanel for inline review instead of navigating."""
        # ponytail: match review is now inline via MatchDetailPanel,
        # not a separate page. Select the first pending entry.
        if self._selected_report_id is None:
            return
        self._match_detail.expand() if hasattr(self._match_detail, "expand") else None

    def _queue_approved(self) -> None:
        report = self._selected_report()
        if report is None:
            return
        entries = MinervaState().get_entries(report.id)
        approved = [
            entry
            for entry in entries
            if entry.decision in {"accept", "fuzzy"}
            and (entry.selected_file_id or entry.automatic_file_id) is not None
        ]
        if not approved:
            NotificationBanner.show_warning(
                self, "Nothing approved", "Approve matches before adding them to the queue"
            )
            return
        shell = self.window()
        controller = getattr(shell, "download_controller", None)
        if controller is None:
            NotificationBanner.show_error(
                self, "Downloads unavailable",
                "The qBittorrent controller is not initialised",
            )
            return
        ids = [entry.selected_file_id or entry.automatic_file_id for entry in approved]
        items = {item.id: item for item in MinervaDB().get_files_by_ids(ids)}
        output_root = Path(
            QtCore.QSettings("MinervaFixDAT", "MinervaGUI").value("output_dir", "downloads", str)
        )
        queue: list[tuple[int, str, str | None]] = []
        for entry in approved:
            file_id = entry.selected_file_id or entry.automatic_file_id
            item = items.get(file_id)
            if item is None:
                continue
            destination = output_root / item.collection / item.system / item.basename
            queue.append((item.id, str(destination), entry.id))
        controller.add_many_to_queue(queue)
        NotificationBanner.show_success(
            self, "Added to queue", f"Queued {len(queue):,} reviewed files"
        )

    def _export_reviewed(self) -> None:
        report = self._selected_report()
        if report is None:
            return
        entries = MinervaState().get_entries(report.id)
        ids = [
            entry.selected_file_id or entry.automatic_file_id
            for entry in entries
            if entry.decision in {"accept", "fuzzy"}
            and (entry.selected_file_id or entry.automatic_file_id)
        ]
        items = MinervaDB().get_files_by_ids(ids)
        if not items:
            NotificationBanner.show_warning(self, "Nothing approved", "Review and approve matches first")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export reviewed DAT", f"{report.name}-reviewed.dat", "DAT files (*.dat)",
        )
        if not path:
            return
        rows = [{"stem": item.stem, "basename": item.basename, "size": item.size} for item in items]
        Path(path).write_text(
            MinervaDB().build_synthetic_dat(rows, f"{report.name} reviewed", report.system, report.collection),
            encoding="utf-8",
        )
        NotificationBanner.show_success(self, "DAT exported", path)

    def _open_source_folder(self) -> None:
        report = self._selected_report()
        if report:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(Path(report.path).parent)))

    def _delete_selected(self) -> None:
        report = self._selected_report()
        if report is None:
            return
        if QtWidgets.QMessageBox.question(
            self, "Remove report", f'Remove "{report.name}" and its review decisions?',
        ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        MinervaState().delete_report(report.id)
        self._selected_report_id = None
        self.refresh()

    def _show_report_menu(self, report: ReportSummary, global_pos: QtCore.QPoint) -> None:
        row = self._navigator.model.index_of(report.id)
        if row >= 0:
            self._navigator.view.setCurrentIndex(self._navigator.model.index(row, 0))
        self._selected_report_id = report.id
        menu = QtWidgets.QMenu(self)
        review = menu.addAction(Icons.search(), "Review matches")
        rematch = menu.addAction(Icons.refresh(), "Match again")
        export = menu.addAction(Icons.file(), "Export reviewed DAT")
        reveal = menu.addAction(Icons.folder_open(), "Open source folder")
        menu.addSeparator()
        remove = menu.addAction(Icons.trash(), "Remove report")
        chosen = menu.exec(global_pos)
        if chosen == review:
            self._review_selected()
        elif chosen == rematch:
            self._rematch_selected()
        elif chosen == export:
            self._export_reviewed()
        elif chosen == reveal:
            self._open_source_folder()
        elif chosen == remove:
            self._delete_selected()

    def handle_drop(self, event: QtGui.QDropEvent) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        valid = [path for path in paths if path.suffix.lower() in {".dat", ".csv"}]
        for path in valid:
            self._import_file(path)
