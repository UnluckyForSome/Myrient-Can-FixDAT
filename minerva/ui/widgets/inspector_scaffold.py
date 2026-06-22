"""Inspector scaffold — a QFrame shell with hero/status/body/actions slots."""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets


class InspectorScaffold(QtWidgets.QFrame):
    """A shell that specialised inspectors compose inside.

    Provides fixed layout slots so subclasses don't re-implement the
    same header + scroll + actions arrangement.
    """

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("inspectorPanel")
        self.setMinimumWidth(310)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ── Header ──────────────────────────────────────────────────────
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)
        heading = QtWidgets.QLabel(title)
        heading.setObjectName("sectionTitle")
        header.addWidget(heading)
        header.addStretch(1)
        root.addLayout(header)

        title_label = QtWidgets.QLabel(subtitle or "")
        title_label.setObjectName("inspectorTitle")
        title_label.setWordWrap(True)
        title_label.setVisible(bool(subtitle))
        root.addWidget(title_label)

        sep = QtWidgets.QFrame()
        sep.setObjectName("separator")
        sep.setFixedHeight(1)
        root.addWidget(sep)

        # ── Hero ────────────────────────────────────────────────────────
        self._hero = QtWidgets.QWidget()
        self.hero_layout = QtWidgets.QVBoxLayout(self._hero)
        self.hero_layout.setContentsMargins(0, 0, 0, 0)
        self.hero_layout.setSpacing(8)
        root.addWidget(self._hero)

        # ── Status ──────────────────────────────────────────────────────
        self._status = QtWidgets.QWidget()
        self.status_layout = QtWidgets.QHBoxLayout(self._status)
        self.status_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._status, 0, QtCore.Qt.AlignmentFlag.AlignLeft)

        # ── Body (scrollable) ───────────────────────────────────────────
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("inspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body_widget = QtWidgets.QWidget()
        self.body_layout = QtWidgets.QVBoxLayout(body_widget)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(12)
        scroll.setWidget(body_widget)
        root.addWidget(scroll, 1)

        # ── Actions (sticky bottom) ─────────────────────────────────────
        action_sep = QtWidgets.QFrame()
        action_sep.setObjectName("separator")
        action_sep.setFixedHeight(1)
        root.addWidget(action_sep)

        self._actions = QtWidgets.QWidget()
        self.actions_layout = QtWidgets.QVBoxLayout(self._actions)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(8)
        root.addWidget(self._actions)
        root.addStretch(1)
