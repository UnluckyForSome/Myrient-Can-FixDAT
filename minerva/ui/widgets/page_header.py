"""Reusable desktop page header with compact action strip."""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.ui.density import Density
from minerva.ui.theme import ThemeTokens


class PageHeader(QtWidgets.QWidget):
    """Page title/subtitle on the left and restrained actions on the right."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMPACT,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._density = density
        self.setObjectName("pageHeader")

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(24)

        text_layout = QtWidgets.QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setObjectName("pageTitle")
        text_layout.addWidget(self.title_label)

        self.subtitle_label = QtWidgets.QLabel(subtitle)
        self.subtitle_label.setObjectName("pageSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        text_layout.addWidget(self.subtitle_label)
        root.addLayout(text_layout, 1)

        self._actions = QtWidgets.QHBoxLayout()
        self._actions.setContentsMargins(0, 0, 0, 0)
        self._actions.setSpacing(8)
        self._actions.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(self._actions)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))

    def add_action(
        self,
        text: str,
        icon: QtGui.QIcon | None = None,
        *,
        primary: bool = False,
        danger: bool = False,
    ) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        if icon is not None:
            button.setIcon(icon)
            button.setIconSize(QtCore.QSize(16, 16))
        button.setObjectName(
            "dangerButton" if danger else "primaryButton" if primary else "subtleButton"
        )
        self._actions.addWidget(button)
        return button


