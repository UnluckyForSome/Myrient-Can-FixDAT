"""Collapsible, count-aware facet list used by the Library browser."""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.domain.library import FacetCount

_VALUE_ROLE = QtCore.Qt.ItemDataRole.UserRole
_COUNT_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1


class _FacetDelegate(QtWidgets.QStyledItemDelegate):
    """Paint a compact checkbox row with a right-aligned count pill."""

    def paint(self, painter, option, index) -> None:
        painter.save()
        style = option.widget.style() if option.widget else QtWidgets.QApplication.style()
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style.drawControl(QtWidgets.QStyle.ControlElement.CE_ItemViewItem, opt, painter, option.widget)

        rect = option.rect.adjusted(8, 0, -8, 0)
        check = QtWidgets.QStyleOptionButton()
        check.state = QtWidgets.QStyle.StateFlag.State_Enabled
        if index.data(QtCore.Qt.ItemDataRole.CheckStateRole) == QtCore.Qt.CheckState.Checked:
            check.state |= QtWidgets.QStyle.StateFlag.State_On
        else:
            check.state |= QtWidgets.QStyle.StateFlag.State_Off
        check.rect = QtCore.QRect(rect.left(), rect.center().y() - 8, 16, 16)
        style.drawControl(QtWidgets.QStyle.ControlElement.CE_CheckBox, check, painter, option.widget)

        count = int(index.data(_COUNT_ROLE) or 0)
        count_text = f"{count:,}"
        count_width = painter.fontMetrics().horizontalAdvance(count_text) + 14
        count_rect = QtCore.QRect(rect.right() - count_width, rect.center().y() - 10, count_width, 20)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(option.palette.alternateBase())
        painter.drawRoundedRect(count_rect, 9, 9)
        painter.setPen(option.palette.placeholderText().color())
        painter.drawText(count_rect, QtCore.Qt.AlignmentFlag.AlignCenter, count_text)

        label_rect = QtCore.QRect(
            check.rect.right() + 8,
            rect.top(),
            max(20, count_rect.left() - check.rect.right() - 16),
            rect.height(),
        )
        painter.setPen(option.palette.text().color())
        label = str(index.data(QtCore.Qt.ItemDataRole.DisplayRole) or "")
        label = painter.fontMetrics().elidedText(label, QtCore.Qt.TextElideMode.ElideRight, label_rect.width())
        painter.drawText(label_rect, QtCore.Qt.AlignmentFlag.AlignVCenter, label)
        painter.restore()

    def sizeHint(self, option, index):
        return QtCore.QSize(180, 31)

    def editorEvent(self, event, model, option, index) -> bool:
        if event.type() != QtCore.QEvent.Type.MouseButtonRelease:
            return False
        current = index.data(QtCore.Qt.ItemDataRole.CheckStateRole)
        new_state = (
            QtCore.Qt.CheckState.Unchecked
            if current == QtCore.Qt.CheckState.Checked
            else QtCore.Qt.CheckState.Checked
        )
        return model.setData(index, new_state, QtCore.Qt.ItemDataRole.CheckStateRole)


class FacetList(QtWidgets.QFrame):
    """Collapsible facet group with selected-count feedback."""

    selection_changed = QtCore.pyqtSignal()

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self.setObjectName("facetGroup")

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self._header = QtWidgets.QToolButton()
        self._header.setObjectName("facetHeader")
        self._header.setText(title)
        self._header.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._header.setArrowType(QtCore.Qt.ArrowType.DownArrow)
        self._header.setCheckable(True)
        self._header.setChecked(True)
        self._header.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._header.toggled.connect(self._set_expanded)
        root.addWidget(self._header)

        self._list = QtWidgets.QListWidget()
        self._list.setObjectName("facetList")
        self._list.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.setItemDelegate(_FacetDelegate(self._list))
        self._list.itemChanged.connect(self._on_item_changed)
        root.addWidget(self._list)

    def set_facets(self, facets: list[FacetCount] | tuple[FacetCount, ...], selected: set[str]) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for facet in facets:
            item = QtWidgets.QListWidgetItem(facet.value.title())
            item.setData(_VALUE_ROLE, facet.value)
            item.setData(_COUNT_ROLE, facet.count)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.CheckState.Checked if facet.value in selected else QtCore.Qt.CheckState.Unchecked
            )
            item.setToolTip(f"{facet.value.title()} \xb7 {facet.count:,} items")
            self._list.addItem(item)
        self._list.blockSignals(False)
        visible_rows = min(7, max(1, self._list.count()))
        self._list.setFixedHeight(visible_rows * 31 + 2)
        self._update_header()

    def selected_values(self) -> set[str]:
        values: set[str] = set()
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                values.add(str(item.data(_VALUE_ROLE)))
        return values

    def clear_selection(self) -> None:
        self._list.blockSignals(True)
        for row in range(self._list.count()):
            self._list.item(row).setCheckState(QtCore.Qt.CheckState.Unchecked)
        self._list.blockSignals(False)
        self._update_header()
        self.selection_changed.emit()

    def uncheck_value(self, value: str) -> None:
        self._list.blockSignals(True)
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.data(_VALUE_ROLE) == value:
                item.setCheckState(QtCore.Qt.CheckState.Unchecked)
                break
        self._list.blockSignals(False)
        self._update_header()

    def _set_expanded(self, expanded: bool) -> None:
        self._list.setVisible(expanded)
        self._header.setArrowType(
            QtCore.Qt.ArrowType.DownArrow if expanded else QtCore.Qt.ArrowType.RightArrow
        )

    def _on_item_changed(self, _item) -> None:
        self._update_header()
        self.selection_changed.emit()

    def _update_header(self) -> None:
        selected = len(self.selected_values())
        suffix = f"  {selected}" if selected else ""
        self._header.setText(f"{self._title}{suffix}")
