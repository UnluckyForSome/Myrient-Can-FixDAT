"""Compact mutually-exclusive segmented control with optional counts."""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets


class SegmentedControl(QtWidgets.QFrame):
    """A compact row of checkable buttons that behaves as one control."""

    current_changed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        items: list[tuple[str, str]] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("segmentedControl")
        self._labels: dict[str, str] = {}
        self._counts: dict[str, int] = {}
        self._buttons: dict[str, QtWidgets.QPushButton] = {}
        self._group = QtWidgets.QButtonGroup(self)
        self._group.setExclusive(True)

        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(2)

        for key, label in items or []:
            self.add_segment(key, label)

    def add_segment(self, key: str, label: str) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(label)
        button.setObjectName("segmentButton")
        button.setCheckable(True)
        button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda checked, value=key: self._on_clicked(value, checked))
        self._group.addButton(button)
        self._layout.addWidget(button)
        self._labels[key] = label
        self._counts[key] = 0
        self._buttons[key] = button
        if len(self._buttons) == 1:
            button.setChecked(True)
        return button

    def _on_clicked(self, key: str, checked: bool) -> None:
        if checked:
            self.current_changed.emit(key)

    def set_current(self, key: str) -> None:
        button = self._buttons.get(key)
        if button is not None:
            button.setChecked(True)

    def current_key(self) -> str:
        for key, button in self._buttons.items():
            if button.isChecked():
                return key
        return ""

    def set_count(self, key: str, count: int) -> None:
        if key not in self._buttons:
            return
        self._counts[key] = max(0, count)
        self._buttons[key].setText(f"{self._labels[key]}  {self._counts[key]}")

    def set_counts(self, counts: dict[str, int]) -> None:
        for key, count in counts.items():
            self.set_count(key, count)
