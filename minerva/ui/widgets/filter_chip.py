"""Compact toggle chip used for active filters and metadata tags."""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from minerva.ui.density import Density
from minerva.ui.theme import ThemeTokens


class FilterChip(QtWidgets.QPushButton):
    """Compact toggle chip used for active filters and metadata tags."""

    def __init__(
        self,
        text: str,
        checked: bool = False,
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMPACT,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._tokens = tokens
        self._density = density
        self.setCheckable(True)
        self.setChecked(checked)
        self.setObjectName("filterChip")
        self.setMinimumHeight(26)
        self.setMaximumHeight(28)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)


