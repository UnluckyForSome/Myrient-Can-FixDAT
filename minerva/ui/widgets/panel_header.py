"""Panel header — title, subtitle, icon, count badge, and actions toolbar."""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets


class PanelHeader(QtWidgets.QWidget):
    """Header row with title, subtitle, count badge and an actions slot.

    Used internally by SurfacePanel but also exposed for cases where the
    caller wants only a standalone header.
    """

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        icon: QtGui.QIcon | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("panelHeader")

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)

        if icon is not None:
            icon_label = QtWidgets.QLabel()
            icon_label.setPixmap(icon.pixmap(18, 18))
            icon_label.setFixedSize(20, 20)
            root.addWidget(icon_label)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        title_row = QtWidgets.QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self._title = QtWidgets.QLabel(title)
        self._title.setObjectName("panelHeaderTitle")
        title_row.addWidget(self._title)
        self._count = QtWidgets.QLabel()
        self._count.setObjectName("panelCount")
        self._count.setVisible(False)
        title_row.addWidget(self._count)
        title_row.addStretch(1)
        text_col.addLayout(title_row)

        self._subtitle = QtWidgets.QLabel(subtitle)
        self._subtitle.setObjectName("mutedLabel")
        self._subtitle.setVisible(bool(subtitle))
        text_col.addWidget(self._subtitle)

        root.addLayout(text_col, 1)

        self.actions_layout = QtWidgets.QHBoxLayout()
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(4)
        root.addLayout(self.actions_layout)

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def set_subtitle(self, text: str) -> None:
        self._subtitle.setText(text)
        self._subtitle.setVisible(bool(text))

    def set_count(self, n: int | None) -> None:
        if n is None:
            self._count.setVisible(False)
        else:
            self._count.setText(str(n))
            self._count.setVisible(True)
