"""Surface panel — a QFrame with title, subtitle, count, header actions, and body layout."""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.ui.widgets.panel_header import PanelHeader


class SurfacePanel(QtWidgets.QFrame):
    """A single containing surface with a pre-configured header and body layout.

    Replaces the repeated hand-built ``QFrame`` + ``QLabel`` header + layout
    blocks found across every page.
    """

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        icon: QtGui.QIcon | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("surfacePanel")

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = PanelHeader(title, subtitle, icon)
        root.addWidget(self._header)

        # Separator between header and body
        sep = QtWidgets.QFrame()
        sep.setObjectName("separator")
        sep.setFixedHeight(1)
        root.addWidget(sep)

        body = QtWidgets.QWidget()
        self.body_layout = QtWidgets.QVBoxLayout(body)
        self.body_layout.setContentsMargins(12, 8, 12, 12)
        self.body_layout.setSpacing(8)
        root.addWidget(body, 1)

        # Expose header actions for caller convenience
        self.header_actions: QtWidgets.QHBoxLayout = self._header.actions_layout

    def set_count(self, n: int) -> None:
        self._header.set_count(n)

    def clear_count(self) -> None:
        self._header.set_count(None)

    def set_subtitle(self, text: str) -> None:
        self._header.set_subtitle(text)

    def set_title(self, text: str) -> None:
        self._header.set_title(text)

    def add_action(self, text: str, icon: QtGui.QIcon | None = None) -> QtWidgets.QPushButton:
        """Add an action button to the header actions layout. Returns the button."""
        btn = QtWidgets.QPushButton(icon, text)
        btn.setObjectName("panelHeaderButton")
        self.header_actions.addWidget(btn)
        return btn
