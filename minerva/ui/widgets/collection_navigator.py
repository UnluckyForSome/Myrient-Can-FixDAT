"""Two-line collection navigator used by the Collections dashboard."""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.domain.collections import CollectionStatus, CollectionSummary
from minerva.ui.icons import Icons
from minerva.ui.theme import ThemeTokens

_SUMMARY_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 1


class CollectionListModel(QtCore.QAbstractListModel):
    """Small immutable-snapshot model for collection summaries."""

    def __init__(self, summaries: list[CollectionSummary] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._summaries = list(summaries or [])

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._summaries)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._summaries):
            return None
        summary = self._summaries[index.row()]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return summary.name
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            return f"{summary.name}\n{summary.systems:,} systems \xb7 {summary.files:,} files"
        if role == _SUMMARY_ROLE:
            return summary
        return None

    def set_summaries(self, summaries: list[CollectionSummary]) -> None:
        self.beginResetModel()
        self._summaries = list(summaries)
        self.endResetModel()

    def summary_at(self, row: int) -> CollectionSummary | None:
        if 0 <= row < len(self._summaries):
            return self._summaries[row]
        return None

    def index_for_name(self, name: str | None) -> int:
        if not name:
            return 0
        for row, summary in enumerate(self._summaries):
            if summary.name == name:
                return row
        return 0


class _CollectionFilterProxy(QtCore.QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFilterCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterRole(QtCore.Qt.ItemDataRole.DisplayRole)


class _CollectionDelegate(QtWidgets.QStyledItemDelegate):
    """Paint collection name, scope summary and a restrained status pill."""

    def __init__(self, tokens: ThemeTokens = ThemeTokens(), parent=None) -> None:
        super().__init__(parent)
        self._tokens = tokens

    def sizeHint(self, option, index):  # noqa: N802
        return QtCore.QSize(260, 70)

    def paint(self, painter: QtGui.QPainter, option, index) -> None:
        summary = index.data(_SUMMARY_ROLE)
        if not isinstance(summary, CollectionSummary):
            return super().paint(painter, option, index)

        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QtWidgets.QStyle.StateFlag.State_MouseOver)
        rect = option.rect.adjusted(4, 3, -4, -3)

        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        if selected:
            painter.setBrush(QtGui.QColor(self._tokens.surface_raised))
        elif hovered:
            painter.setBrush(QtGui.QColor(self._tokens.surface_raised).lighter(103))
        else:
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 7, 7)
        if selected:
            painter.setBrush(QtGui.QColor(self._tokens.accent))
            painter.drawRoundedRect(QtCore.QRect(rect.left(), rect.top() + 8, 3, rect.height() - 16), 2, 2)

        icon_rect = QtCore.QRect(rect.left() + 12, rect.top() + 14, 26, 26)
        painter.drawPixmap(icon_rect, Icons.collections().pixmap(20, 20))

        title_rect = QtCore.QRect(icon_rect.right() + 10, rect.top() + 8, rect.width() - 126, 24)
        title_font = QtGui.QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QtGui.QColor(self._tokens.text))
        title = painter.fontMetrics().elidedText(summary.name, QtCore.Qt.TextElideMode.ElideRight, title_rect.width())
        painter.drawText(title_rect, QtCore.Qt.AlignmentFlag.AlignVCenter, title)

        subtitle_rect = QtCore.QRect(title_rect.left(), title_rect.bottom() + 3, rect.width() - 64, 20)
        subtitle_font = QtGui.QFont(option.font)
        subtitle_font.setPointSize(max(8, option.font.pointSize() - 1))
        painter.setFont(subtitle_font)
        painter.setPen(QtGui.QColor(self._tokens.text_muted))
        painter.drawText(
            subtitle_rect,
            QtCore.Qt.AlignmentFlag.AlignVCenter,
            f"{summary.systems:,} systems \xb7 {summary.files:,} files",
        )

        label, fg, bg = self._status_style(summary.status)
        pill_font = QtGui.QFont(subtitle_font)
        pill_font.setBold(True)
        painter.setFont(pill_font)
        fm = QtGui.QFontMetrics(pill_font)
        pill_width = fm.horizontalAdvance(label) + 16
        pill = QtCore.QRect(rect.right() - pill_width - 10, rect.top() + 11, pill_width, 22)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(bg))
        painter.drawRoundedRect(pill, 10, 10)
        painter.setPen(QtGui.QColor(fg))
        painter.drawText(pill, QtCore.Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    def _status_style(self, status: CollectionStatus) -> tuple[str, str, str]:
        if status == CollectionStatus.INDEXED:
            return "Indexed", self._tokens.success, self._tokens.success_surface
        if status == CollectionStatus.PARTIAL:
            return "Partial", self._tokens.warning, self._tokens.warning_surface
        return "Missing", self._tokens.error, self._tokens.error_surface


class CollectionNavigator(QtWidgets.QFrame):
    """Searchable collection list with rich summary rows."""

    collection_changed = QtCore.pyqtSignal(object)
    open_requested = QtCore.pyqtSignal(object)
    remove_requested = QtCore.pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("navigatorPanel")
        self.setMinimumWidth(280)
        self.setMaximumWidth(360)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        heading = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel()
        icon.setPixmap(Icons.collections().pixmap(18, 18))
        icon.setFixedSize(20, 20)
        heading.addWidget(icon)
        title = QtWidgets.QLabel("Indexed collections")
        title.setObjectName("sectionTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        self._count = QtWidgets.QLabel("0")
        self._count.setObjectName("panelCount")
        heading.addWidget(self._count)
        root.addLayout(heading)

        self.search = QtWidgets.QLineEdit()
        self.search.setObjectName("collectionSearch")
        self.search.setPlaceholderText("Search collections\u2026")
        self.search.addAction(Icons.search(), QtWidgets.QLineEdit.ActionPosition.LeadingPosition)
        root.addWidget(self.search)

        self.model = CollectionListModel(parent=self)
        self.proxy = _CollectionFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.view = QtWidgets.QListView()
        self.view.setObjectName("collectionNavigator")
        self.view.setModel(self.proxy)
        self.view.setItemDelegate(_CollectionDelegate(parent=self.view))
        self.view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.selectionModel().selectionChanged.connect(self._emit_selection)
        self.view.customContextMenuRequested.connect(self._show_context_menu)
        root.addWidget(self.view, 1)

        self.search.textChanged.connect(self.proxy.setFilterFixedString)

    def set_summaries(self, summaries: list[CollectionSummary]) -> None:
        self.model.set_summaries(summaries)
        self._count.setText(f"{len(summaries):,}")

    def selected_summary(self) -> CollectionSummary | None:
        rows = self.view.selectionModel().selectedRows()
        if not rows:
            return None
        source = self.proxy.mapToSource(rows[0])
        return self.model.summary_at(source.row())

    def select_name(self, name: str | None) -> None:
        target = self.model.index_for_name(name)
        if self.model.rowCount() == 0:
            return
        source = self.model.index(target, 0)
        proxy = self.proxy.mapFromSource(source)
        if proxy.isValid():
            self.view.setCurrentIndex(proxy)

    def _emit_selection(self) -> None:
        summary = self.selected_summary()
        if summary is not None:
            self.collection_changed.emit(summary)

    def _show_context_menu(self, point: QtCore.QPoint) -> None:
        index = self.view.indexAt(point)
        if not index.isValid():
            return
        self.view.setCurrentIndex(index)
        summary = self.selected_summary()
        if summary is None:
            return
        menu = QtWidgets.QMenu(self)
        open_action = menu.addAction(Icons.folder_open(), "Open source folder")
        remove_action = menu.addAction(Icons.trash(), "Remove from index")
        chosen = menu.exec(self.view.viewport().mapToGlobal(point))
        if chosen == open_action:
            self.open_requested.emit(summary)
        elif chosen == remove_action:
            self.remove_requested.emit(summary)
