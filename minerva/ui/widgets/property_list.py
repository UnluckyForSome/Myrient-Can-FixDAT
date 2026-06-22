"""Property list — key/value rows with middle-elision, 96 px labels."""

from __future__ import annotations

from typing import Sequence

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.ui.icons import Icons


class _ElidedValue(QtWidgets.QLabel):
    """A label that elides its text to fit its available width."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setObjectName("propertyListValue")
        self.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setToolTip(text)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        self._update_text()

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._update_text()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_text()

    def _update_text(self) -> None:
        width = max(40, self.width())
        self.setText(
            self.fontMetrics().elidedText(
                self._full_text,
                QtCore.Qt.TextElideMode.ElideMiddle,
                width,
            )
        )


class PropertyList(QtWidgets.QWidget):
    """Reusable key/value list with middle-elision, tooltips, and optional copy.

    Label column: fixed minimum width 96 px, right-aligned, ``text_muted`` colour.
    Value column: ``Expanding`` size policy, ``ElideMiddle``, full text in tooltip,
    ``TextSelectableByMouse`` always on.
    """

    def __init__(
        self,
        rows: Sequence[tuple[str, str]] = (),
        *,
        copy_values: bool = False,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._copy_values = copy_values
        self.setObjectName("propertyList")

        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)

        # Track rows as (key_label, value_label, copy_button_or_none)
        self._rows: list[tuple[QtWidgets.QLabel, _ElidedValue, QtWidgets.QToolButton | None]] = []

        if rows:
            self.set_rows(rows)

    def _build_row(self, key: str, value: str) -> tuple[QtWidgets.QLabel, _ElidedValue, QtWidgets.QToolButton | None]:
        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        key_label = QtWidgets.QLabel(key)
        key_label.setObjectName("propertyListLabel")
        key_label.setFixedWidth(96)
        key_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignTop
        )
        row_layout.addWidget(key_label)

        value_label = _ElidedValue(value)
        row_layout.addWidget(value_label, 1)

        copy_btn: QtWidgets.QToolButton | None = None
        if self._copy_values:
            copy_btn = QtWidgets.QToolButton()
            copy_btn.setObjectName("iconButton")
            copy_btn.setIcon(Icons.copy())
            copy_btn.setToolTip("Copy value")
            copy_btn.clicked.connect(
                lambda _checked=False, text=value: QtWidgets.QApplication.clipboard().setText(text)
            )
            row_layout.addWidget(copy_btn)

        self._layout.addWidget(row)
        return (key_label, value_label, copy_btn)

    def set_rows(self, rows: Sequence[tuple[str, str]]) -> None:
        """Replace all rows."""
        self.clear()
        for key, value in rows:
            self._rows.append(self._build_row(key, value))

    def set_row(self, key: str, value: str) -> None:
        """Update an existing row's value, or append a new row."""
        for k_label, v_label, _copy in self._rows:
            if k_label.text() == key:
                v_label.set_full_text(value)
                return
        self._rows.append(self._build_row(key, value))

    def clear(self) -> None:
        """Remove all rows."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()
