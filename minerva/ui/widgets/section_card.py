"""
Section card — titled card with optional icon and content area.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.ui.theme import ThemeTokens
from minerva.ui.density import Density


class SectionCard(QtWidgets.QFrame):
    """Card with optional title, icon, and content area.

    Provides a ``content_layout()`` accessor so callers can add arbitrary
    widgets to the card body::

        card = SectionCard(title="Details", icon=Icons.reports())
        label = QtWidgets.QLabel("Some content")
        card.content_layout().addWidget(label)
    """

    def __init__(
        self,
        title: str = "",
        icon: QtGui.QIcon | None = None,
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMPACT,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._density = density

        self.setObjectName("surfaceCard")

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(density.card_padding, density.card_padding,
                                        density.card_padding, density.card_padding)
        main_layout.setSpacing(8)

        # ── Header row ─────────────────────────────────────────────────────────
        if title or icon is not None:
            header_row = QtWidgets.QHBoxLayout()
            header_row.setSpacing(8)

            if icon is not None:
                icon_label = QtWidgets.QLabel()
                icon_label.setFixedSize(20, 20)
                icon_label.setPixmap(icon.pixmap(20, 20))
                header_row.addWidget(icon_label)

            if title:
                title_label = QtWidgets.QLabel(title)
                title_label.setObjectName("sectionTitle")
                header_row.addWidget(title_label)

            header_row.addStretch(1)
            main_layout.addLayout(header_row)

        # ── Separator ──────────────────────────────────────────────────────────
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        sep.setObjectName("separator")
        main_layout.addWidget(sep)

        # ── Content area ───────────────────────────────────────────────────────
        self._content_layout = QtWidgets.QVBoxLayout()
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(6)
        main_layout.addLayout(self._content_layout)

    def content_layout(self) -> QtWidgets.QVBoxLayout:
        """Return the content layout for adding child widgets."""
        return self._content_layout



