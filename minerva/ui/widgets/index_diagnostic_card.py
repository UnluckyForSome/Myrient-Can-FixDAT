"""Compact diagnostic card for index maintenance status."""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.ui.theme import ThemeTokens
from minerva.ui.widgets.status_badge import BadgeKind, StatusBadge


class IndexDiagnosticCard(QtWidgets.QFrame):
    """Small status card with one concise action."""

    action_requested = QtCore.pyqtSignal()

    def __init__(
        self,
        title: str,
        icon: QtGui.QIcon,
        action_text: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("diagnosticCard")
        self.setMinimumHeight(150)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 13, 14, 13)
        root.setSpacing(7)

        header = QtWidgets.QHBoxLayout()
        icon_label = QtWidgets.QLabel()
        icon_label.setObjectName("diagnosticIcon")
        icon_label.setFixedSize(28, 28)
        icon_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        icon_label.setPixmap(icon.pixmap(16, 16))
        header.addWidget(icon_label)
        heading = QtWidgets.QLabel(title)
        heading.setObjectName("diagnosticTitle")
        header.addWidget(heading, 1)
        self.badge = StatusBadge("Idle", BadgeKind.NEUTRAL)
        header.addWidget(self.badge)
        root.addLayout(header)

        self.value = QtWidgets.QLabel("\u2014")
        self.value.setObjectName("diagnosticValue")
        root.addWidget(self.value)
        self.description = QtWidgets.QLabel("")
        self.description.setObjectName("diagnosticDescription")
        self.description.setWordWrap(True)
        root.addWidget(self.description, 1)

        self.button = QtWidgets.QPushButton(action_text)
        self.button.setObjectName("diagnosticAction")
        self.button.clicked.connect(self.action_requested.emit)
        root.addWidget(self.button, 0, QtCore.Qt.AlignmentFlag.AlignLeft)

    def set_state(
        self,
        value: str,
        description: str,
        badge: str,
        kind: BadgeKind = BadgeKind.NEUTRAL,
    ) -> None:
        self.value.setText(value)
        self.description.setText(description)
        self.badge.setText(badge)
        self.badge.set_kind(kind)

    def set_action_text(self, text: str) -> None:
        self.button.setText(text)

    def set_busy(self, busy: bool, text: str | None = None) -> None:
        self.button.setEnabled(not busy)
        if text is not None:
            self.button.setText(text)
