"""
Reusable right-side inspector panel — thin convenience wrapper around
:class:`InspectorScaffold`.

This shim exists for backward compatibility during the 0016 migration.
Callers should migrate to ``InspectorScaffold`` directly by 0017a.
"""

from __future__ import annotations

from warnings import warn

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.ui.density import Density
from minerva.ui.icons import Icons
from minerva.ui.theme import ThemeTokens
from minerva.ui.widgets.inspector_scaffold import InspectorScaffold
from minerva.ui.widgets.property_list import PropertyList
from minerva.ui.widgets.status_badge import BadgeKind, StatusBadge


class InspectorSection:
    """Backward-compat section descriptor.

    .. deprecated::
        Use ``PropertyList`` rows directly in 0017a.
    """

    def __init__(self, title: str, rows: list[tuple[str, str]] | None = None):
        warn("InspectorSection is deprecated; use PropertyList directly", DeprecationWarning, stacklevel=2)
        self.title = title
        self.rows = rows or []


class InspectorPanel(InspectorScaffold):
    """
    .. deprecated::
        Use ``InspectorScaffold`` directly. This class will be removed in 0017a.
    """

    def __init__(
        self,
        title: str = "Details",
        icon: QtGui.QIcon | None = None,
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMPACT,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(title, parent=parent)
        warn(
            "InspectorPanel is deprecated; use InspectorScaffold directly",
            DeprecationWarning,
            stacklevel=2,
        )
        self._tokens = tokens
        self._density = density
        self._property_lists: list[PropertyList] = []

        # Update the title from sectionTitle to something useful
        self._name = QtWidgets.QLabel("Select a report")
        self._name.setObjectName("inspectorTitle")
        self._name.setWordWrap(True)
        self.hero_layout.addWidget(self._name)

        self._status = StatusBadge("No selection", BadgeKind.NEUTRAL)
        self.status_layout.addWidget(self._status)

    def clear(self, message: str = "Select a report") -> None:
        self._name.setText(message)
        self._status.setText("No selection")
        self._status.set_kind(BadgeKind.NEUTRAL)
        self.set_sections([])
        self.set_actions_enabled(False)

    def set_header(self, name: str, status: str, kind: BadgeKind) -> None:
        self._name.setText(name)
        self._status.setText(status)
        self._status.set_kind(kind)

    def set_sections(self, sections: list[InspectorSection]) -> None:
        # Remove old property lists
        for pl in self._property_lists:
            self.body_layout.removeWidget(pl)
            pl.deleteLater()
        self._property_lists.clear()

        for section in sections:
            title = QtWidgets.QLabel(section.title.upper())
            title.setObjectName("inspectorSectionTitle")
            self.body_layout.addWidget(title)
            pl = PropertyList(section.rows)
            self.body_layout.addWidget(pl)
            self._property_lists.append(pl)

    def add_action(
        self,
        text: str,
        icon: QtGui.QIcon | None = None,
        *,
        primary: bool = False,
    ) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        if icon is not None:
            button.setIcon(icon)
        button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        button.setObjectName("actionGroupPrimary" if primary else "actionGroupSecondary")
        self.actions_layout.addWidget(button)
        return button

    def set_actions_enabled(self, enabled: bool) -> None:
        for i in range(self.actions_layout.count()):
            widget = self.actions_layout.itemAt(i).widget()
            if widget is not None:
                widget.setEnabled(enabled)

    def apply_tokens(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens
        self._status.apply_tokens(tokens)

    def apply_density(self, density: Density) -> None:
        self._density = density
