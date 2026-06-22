"""Two-line report navigator used by the Reports dashboard."""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.domain.reports import ReportSummary
from minerva.ui.icons import Icons
from minerva.ui.theme import ThemeTokens

_REPORT_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 1


class ReportListModel(QtCore.QAbstractListModel):
    def __init__(self, reports: list[ReportSummary] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._reports = list(reports or [])

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._reports)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._reports):
            return None
        report = self._reports[index.row()]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return report.name
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            return f"{report.name}\n{report.path}"
        if role == _REPORT_ROLE:
            return report
        return None

    def set_reports(self, reports: list[ReportSummary]) -> None:
        self.beginResetModel()
        self._reports = list(reports)
        self.endResetModel()

    def report_at(self, row: int) -> ReportSummary | None:
        return self._reports[row] if 0 <= row < len(self._reports) else None

    def index_of(self, report_id: str | None) -> int:
        if not report_id:
            return -1
        return next((i for i, report in enumerate(self._reports) if report.id == report_id), -1)


class _ReportFilterProxy(QtCore.QSortFilterProxyModel):
    """Filter reports by text, status, collection, and system."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text = ""
        self._status_filter: set[str] = set()  # empty = show all
        self._collection: str = ""
        self._system: str = ""
        self.setFilterRole(_REPORT_ROLE)
        self.setDynamicSortFilter(True)

    def set_text(self, text: str) -> None:
        self._text = text.strip().casefold()
        self.invalidateFilter()

    def set_status_filter(self, statuses: set[str]) -> None:
        self._status_filter = {s.casefold() for s in statuses}
        self.invalidateFilter()

    def set_collection(self, value: str) -> None:
        self._collection = value
        self.invalidateFilter()

    def set_system(self, value: str) -> None:
        self._system = value
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):  # noqa: N802
        model = self.sourceModel()
        if not isinstance(model, ReportListModel):
            return True
        report = model.report_at(source_row)
        if report is None:
            return False
        if self._status_filter:
            raw = (report.status or "draft").casefold()
            if raw not in self._status_filter:
                return False
        if self._collection and (report.collection or "").casefold() != self._collection:
            return False
        if self._system and (report.system or "").casefold() != self._system:
            return False
        if self._text:
            haystack = " ".join((
                report.name, report.collection or "", report.system or "",
                report.status or "", str(report.requested_count),
            )).casefold()
            if self._text not in haystack:
                return False
        return True


class _ReportDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, tokens: ThemeTokens = ThemeTokens(), parent=None) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._icon = Icons.reports()

    def sizeHint(self, option, index):  # noqa: N802
        return QtCore.QSize(max(270, option.rect.width()), 76)

    def paint(self, painter: QtGui.QPainter, option, index) -> None:
        report: ReportSummary | None = index.data(_REPORT_ROLE)
        if report is None:
            return super().paint(painter, option, index)

        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(2, 2, -2, -2)
        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QtWidgets.QStyle.StateFlag.State_MouseOver)

        if selected:
            painter.setBrush(QtGui.QColor(self._tokens.surface_raised))
            painter.setPen(QtGui.QPen(QtGui.QColor(self._tokens.border)))
        elif hovered:
            painter.setBrush(QtGui.QColor(self._tokens.surface_raised))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
        else:
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 7, 7)

        if selected:
            accent = QtCore.QRect(rect.left(), rect.top() + 8, 3, rect.height() - 16)
            painter.fillRect(accent, QtGui.QColor(self._tokens.accent))

        x = rect.left() + 12
        icon_rect = QtCore.QRect(x, rect.top() + 15, 20, 20)
        self._icon.paint(painter, icon_rect)
        x += 30

        status_text, status_fg, status_bg = self._status_style(report.status)
        status_font = QtGui.QFont(option.font)
        status_font.setPointSize(max(9, option.font.pointSize() - 1))
        status_font.setBold(True)
        painter.setFont(status_font)
        status_width = QtGui.QFontMetrics(status_font).horizontalAdvance(status_text) + 18
        status_rect = QtCore.QRect(
            rect.right() - status_width - 10,
            rect.top() + 11,
            status_width,
            22,
        )
        painter.setBrush(QtGui.QColor(status_bg))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawRoundedRect(status_rect, 10, 10)
        painter.setPen(QtGui.QColor(status_fg))
        painter.drawText(status_rect, QtCore.Qt.AlignmentFlag.AlignCenter, status_text)

        title_font = QtGui.QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QtGui.QColor(self._tokens.text))
        title_width = max(40, status_rect.left() - x - 10)
        title = QtGui.QFontMetrics(title_font).elidedText(
            report.name,
            QtCore.Qt.TextElideMode.ElideRight,
            title_width,
        )
        painter.drawText(
            QtCore.QRect(x, rect.top() + 10, title_width, 24),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            title,
        )

        subtitle_font = QtGui.QFont(option.font)
        subtitle_font.setPointSize(max(9, option.font.pointSize() - 1))
        painter.setFont(subtitle_font)
        painter.setPen(QtGui.QColor(self._tokens.text_muted))
        scope = report.system or report.collection or "Unknown scope"
        subtitle = f"{scope}  \xb7  {report.requested_count:,} entries"
        subtitle = QtGui.QFontMetrics(subtitle_font).elidedText(
            subtitle,
            QtCore.Qt.TextElideMode.ElideRight,
            rect.right() - x - 12,
        )
        painter.drawText(
            QtCore.QRect(x, rect.top() + 39, rect.right() - x - 12, 22),
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            subtitle,
        )
        painter.restore()

    def _status_style(self, status: str) -> tuple[str, str, str]:
        value = (status or "draft").lower()
        if value in {"ready", "reviewed"}:
            return value.title(), self._tokens.success, self._tokens.success_surface
        if value == "matching":
            return "Matching", self._tokens.accent, self._tokens.info_surface
        if value == "failed":
            return "Failed", self._tokens.error, self._tokens.error_surface
        if value == "archived":
            return "Archived", self._tokens.text_muted, self._tokens.surface_raised
        return value.title(), self._tokens.warning, self._tokens.warning_surface

    def apply_tokens(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens


class ReportNavigator(QtWidgets.QFrame):
    """Card-like report list with search and status filtering."""

    current_report_changed = QtCore.pyqtSignal(object)
    report_activated = QtCore.pyqtSignal(object)
    context_menu_requested = QtCore.pyqtSignal(object, QtCore.QPoint)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("navigatorPanel")
        self.setMinimumWidth(280)
        self.setMaximumWidth(360)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Header ──────────────────────────────────────────────────────
        header = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel()
        icon.setPixmap(Icons.reports().pixmap(17, 17))
        header.addWidget(icon)
        title = QtWidgets.QLabel("Imported reports")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._count = QtWidgets.QLabel("0")
        self._count.setObjectName("panelCount")
        header.addWidget(self._count)
        root.addLayout(header)

        # ── Search ──────────────────────────────────────────────────────
        self._search = QtWidgets.QLineEdit()
        self._search.setObjectName("reportNavigatorSearch")
        self._search.setPlaceholderText("Filter reports\u2026")
        self._search.setClearButtonEnabled(True)
        self._search.addAction(
            Icons.search(), QtWidgets.QLineEdit.ActionPosition.LeadingPosition
        )
        root.addWidget(self._search)

        # ── Collection + System combo filters ──────────────────────────
        filter_row = QtWidgets.QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(4)

        self._collection_filter = QtWidgets.QComboBox()
        self._collection_filter.setObjectName("reportFilterCombo")
        self._collection_filter.addItem("All collections", "")
        self._collection_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self._collection_filter, 1)

        self._system_filter = QtWidgets.QComboBox()
        self._system_filter.setObjectName("reportFilterCombo")
        self._system_filter.addItem("All systems", "")
        self._system_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self._system_filter, 1)

        root.addLayout(filter_row)

        # ── Status filter row ───────────────────────────────────────────
        status_bar = QtWidgets.QHBoxLayout()
        status_bar.setContentsMargins(0, 0, 0, 0)
        status_bar.setSpacing(4)
        self._status_buttons: dict[str, QtWidgets.QPushButton] = {}
        for key, label in (
            ("ready", "Ready"),
            ("matching", "Matching"),
            ("draft", "Draft"),
            ("failed", "Failed"),
        ):
            btn = QtWidgets.QPushButton(label)
            btn.setObjectName("filterChip")
            btn.setCheckable(True)
            btn.setChecked(False)
            btn.clicked.connect(lambda _checked, k=key: self._toggle_status(k))
            status_bar.addWidget(btn)
            self._status_buttons[key] = btn
        root.addLayout(status_bar)

        # ── Model + proxy + view ────────────────────────────────────────
        # ponytail: model is Python-owned (self.model) rather than Qt-parented
        # to the navigator, so it survives navigator C++ destruction during
        # teardown and is never collected mid-use. The strong reference here
        # and on the page (ReportsPage._report_model) govern its lifetime.
        self.model = ReportListModel()
        self.proxy = _ReportFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self.view = QtWidgets.QListView()
        self.view.setObjectName("reportNavigator")
        self.view.setModel(self.proxy)
        self.view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setMouseTracking(True)
        self.delegate = _ReportDelegate(parent=self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.view.doubleClicked.connect(self._on_activated)
        self.view.customContextMenuRequested.connect(self._on_context_menu)
        root.addWidget(self.view, 1)

        self._empty = QtWidgets.QLabel("No reports imported")
        self._empty.setObjectName("emptyInline")
        self._empty.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._empty)

        self._search.textChanged.connect(self._on_text_changed)

    def _on_text_changed(self, text: str) -> None:
        self.proxy.set_text(text)
        self._apply_filters()

    def _populate_filter_combos(self, reports: list[ReportSummary]) -> None:
        """Rebuild collection and system combo boxes from the current reports."""
        collections: set[str] = set()
        systems: set[str] = set()
        for report in reports:
            if report.collection:
                collections.add(report.collection)
            if report.system:
                systems.add(report.system)

        self._collection_filter.blockSignals(True)
        self._collection_filter.clear()
        self._collection_filter.addItem("All collections", "")
        for value in sorted(collections):
            self._collection_filter.addItem(value, value)
        self._collection_filter.blockSignals(False)

        self._system_filter.blockSignals(True)
        self._system_filter.clear()
        self._system_filter.addItem("All systems", "")
        for value in sorted(systems):
            self._system_filter.addItem(value, value)
        self._system_filter.blockSignals(False)

    def _apply_filters(self) -> None:
        self.proxy.set_collection(self._collection_filter.currentData() or "")
        self.proxy.set_system(self._system_filter.currentData() or "")
        visible = self.proxy.rowCount() > 0
        self.view.setVisible(visible)
        self._empty.setVisible(not visible and self.model.rowCount() > 0)

    def _toggle_status(self, key: str) -> None:
        active = {k for k, btn in self._status_buttons.items() if btn.isChecked()}
        self.proxy.set_status_filter(active)
        self._apply_filters()

    def set_reports(self, reports: list[ReportSummary], selected_id: str | None = None) -> None:
        self.model.set_reports(reports)
        self._count.setText(str(len(reports)))
        self._populate_filter_combos(reports)
        self._apply_filters()
        if self.proxy.rowCount() > 0:
            row = self._find_proxy_row(selected_id)
            if row >= 0:
                self.view.setCurrentIndex(self.proxy.index(row, 0))
        else:
            self._empty.setVisible(True)

    def _find_proxy_row(self, report_id: str | None) -> int:
        if not report_id:
            return 0
        for row in range(self.proxy.rowCount()):
            source = self.proxy.mapToSource(self.proxy.index(row, 0))
            report = self.model.report_at(source.row())
            if report and report.id == report_id:
                return row
        return 0

    def current_report(self) -> ReportSummary | None:
        proxy_index = self.view.currentIndex()
        if not proxy_index.isValid():
            return None
        source = self.proxy.mapToSource(proxy_index)
        return self.model.report_at(source.row())

    def _on_selection_changed(self) -> None:
        report = self.current_report()
        if report is not None:
            self.current_report_changed.emit(report)

    def _on_activated(self, index: QtCore.QModelIndex) -> None:
        source = self.proxy.mapToSource(index)
        self.report_activated.emit(self.model.report_at(source.row()))

    def _on_context_menu(self, pos: QtCore.QPoint) -> None:
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        source = self.proxy.mapToSource(index)
        report = self.model.report_at(source.row())
        if report is not None:
            self.context_menu_requested.emit(report, self.view.viewport().mapToGlobal(pos))

    def apply_tokens(self, tokens: ThemeTokens) -> None:
        self.delegate.apply_tokens(tokens)
        self.view.viewport().update()
