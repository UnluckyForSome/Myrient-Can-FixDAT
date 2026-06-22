"""Action group — standardised primary/secondary/destructive button stack."""

from __future__ import annotations

from typing import Callable, Sequence

from PyQt6 import QtCore, QtWidgets


class ActionGroup(QtWidgets.QWidget):
    """Standardised button stack with consistent spacing and role-based styling.

    Roles:
        ``Primary`` — ``actionGroupPrimary`` (accent background).
        ``Secondary`` — ``actionGroupSecondary`` (subtle background).
        ``Destructive`` — ``actionGroupDestructive`` (danger border).
    """

    Primary = 0
    Secondary = 1
    Destructive = 2

    _ROLE_OBJECT_NAMES = {
        Primary: "actionGroupPrimary",
        Secondary: "actionGroupSecondary",
        Destructive: "actionGroupDestructive",
    }

    def __init__(
        self,
        actions: Sequence[tuple[str, Callable[[], None], int]] = (),
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

        self._buttons: list[tuple[QtWidgets.QPushButton, int]] = []
        if actions:
            self.set_actions(actions)

    def set_actions(self, actions: Sequence[tuple[str, Callable[[], None], int]]) -> None:
        """Replace all action buttons."""
        # Clear existing
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._buttons.clear()

        for text, callback, role in actions:
            button = QtWidgets.QPushButton(text)
            button.setObjectName(self._ROLE_OBJECT_NAMES.get(role, "actionGroupSecondary"))
            button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(callback)
            self._layout.addWidget(button)
            self._buttons.append((button, role))

    def set_enabled(self, role: int, enabled: bool) -> None:
        """Enable or disable all buttons of the given role."""
        for button, btn_role in self._buttons:
            if btn_role == role:
                button.setEnabled(enabled)
