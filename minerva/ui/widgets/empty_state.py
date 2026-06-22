"""
Empty state — placeholder for views with no data.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.ui.icons import Icons
from minerva.ui.theme import ThemeTokens
from minerva.ui.density import Density


class EmptyState(QtWidgets.QWidget):
    """Empty state placeholder with icon, title, description, and optional action.

    Centred content with a large icon (72 px), a title label, an optional body
    label, and an optional action button.  Typical use::

        empty = EmptyState(
            parent=stack,
            icon=Icons.search,
            title="No results found",
            description="Try adjusting your search or filter criteria.",
            action_text="Clear Filters",
        )
        empty.action_clicked.connect(self._clear_filters)
    """

    action_clicked = QtCore.pyqtSignal()

    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        icon: QtGui.QIcon | None = None,
        title: str = "",
        description: str = "",
        action_text: str = "",
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMPACT,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._density = density

        layout = QtWidgets.QVBoxLayout(self)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(8)

        # ── Icon ───────────────────────────────────────────────────────────────
        self._icon_label = QtWidgets.QLabel()
        self._icon_label.setFixedSize(72, 72)
        self._icon_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        if icon is not None:
            self._icon_label.setPixmap(icon.pixmap(72, 72))
        layout.addWidget(self._icon_label)

        # ── Title ──────────────────────────────────────────────────────────────
        self._title_label = QtWidgets.QLabel(title)
        self._title_label.setObjectName("emptyStateTitle")
        self._title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        # ── Description ────────────────────────────────────────────────────────
        self._desc_label: QtWidgets.QLabel | None = None
        if description:
            self._desc_label = QtWidgets.QLabel(description)
            self._desc_label.setObjectName("emptyStateDescription")
            self._desc_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self._desc_label.setWordWrap(True)
            layout.addWidget(self._desc_label)

        # ── Action button ──────────────────────────────────────────────────────
        self._action_btn: QtWidgets.QPushButton | None = None
        if action_text:
            self._action_btn = QtWidgets.QPushButton(action_text)
            self._action_btn.setObjectName("accentButton")
            self._action_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            self._action_btn.clicked.connect(self.action_clicked.emit)
            # Wrap button in a centred horizontal layout
            btn_row = QtWidgets.QHBoxLayout()
            btn_row.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            btn_row.addWidget(self._action_btn)
            layout.addLayout(btn_row)

        layout.addStretch(1)

    # ── Setters ─────────────────────────────────────────────────────────────────

    def set_icon(self, icon: QtGui.QIcon) -> None:
        self._icon_label.setPixmap(icon.pixmap(72, 72))

    def set_title(self, text: str) -> None:
        self._title_label.setText(text)

    def set_description(self, text: str) -> None:
        if self._desc_label is not None:
            self._desc_label.setText(text)
        else:
            self._desc_label = QtWidgets.QLabel(text)
            self._desc_label.setObjectName("emptyStateDescription")
            self._desc_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self._desc_label.setWordWrap(True)
            # Insert after the title
            idx = self.layout().indexOf(self._title_label)
            self.layout().insertWidget(idx + 1, self._desc_label)

    def set_action_text(self, text: str) -> None:
        if self._action_btn is not None:
            self._action_btn.setText(text)
        elif text:
            self._action_btn = QtWidgets.QPushButton(text)
            self._action_btn.setObjectName("accentButton")
            self._action_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            self._action_btn.clicked.connect(self.action_clicked.emit)
            btn_row = QtWidgets.QHBoxLayout()
            btn_row.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            btn_row.addWidget(self._action_btn)
            self.layout().addLayout(btn_row)



