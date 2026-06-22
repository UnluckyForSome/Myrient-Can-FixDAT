"""
Sidebar navigation widget for the Minerva app shell.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.app.page_id import PageId
from minerva.ui.density import Density
from minerva.ui.icons import Icons
from minerva.ui.theme import ThemeTokens


class SidebarRow(QtWidgets.QPushButton):
    """A single row in the sidebar — icon + label, wired to a QAction.

    The row's active state is toggled by the ``active`` property and
    rendered via dynamic stylesheet.
    """

    def __init__(
        self,
        page_id: PageId,
        icon: QtGui.QIcon,
        label: str,
        action: QtGui.QAction,
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMFORTABLE,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._page_id = page_id
        self._action = action
        self._tokens = tokens
        self._density = density
        self._active = False

        self.setFixedHeight(density.nav_height)
        self.setIcon(icon)
        self.setIconSize(QtCore.QSize(18, 18))
        self.setText(label)
        self.setObjectName("sidebarRow")

        # Wire click → action.trigger()
        self.clicked.connect(self._action.trigger)

        self._update_style()

    def apply_tokens(self, tokens: ThemeTokens) -> None:
        """Refresh this row's palette after the global theme changes."""
        self._tokens = tokens
        self._update_style()

    def apply_density(self, density: Density) -> None:
        """Refresh this row's height after the global density changes."""
        self._density = density
        self.setFixedHeight(density.nav_height)

    @property
    def page_id(self) -> PageId:
        return self._page_id

    @property
    def is_active(self) -> bool:
        return self._active

    def set_active(self, active: bool) -> None:
        self._active = active
        self._update_style()

    def _update_style(self) -> None:
        bg = self._tokens.surface if self._active else self._tokens.background
        border = (
            f"border-left: 3px solid {self._tokens.accent};"
            if self._active
            else "border-left: 3px solid transparent;"
        )
        color = self._tokens.accent if self._active else self._tokens.text

        self.setStyleSheet(
            f"QPushButton#sidebarRow {{"
            f"  background-color: {bg};"
            f"  {border}"
            f"  color: {color};"
            f"  text-align: left;"
            f"  padding-left: 16px;"
            f"  border-radius: 0;"
            f"  font-size: 13px;"
            f"  border-right: none;"
            f"  border-top: none;"
            f"  border-bottom: none;"
            f"}}"
            f"QPushButton#sidebarRow:hover {{"
            f"  background-color: {self._tokens.surface};"
            f"}}"
        )


class AppSidebar(QtWidgets.QWidget):
    """Fixed-width sidebar with 3 navigation rows and a tray toggle.

    Parameters
    ----------
    actions : dict[PageId, QtGui.QAction]
        One QAction per top-level page.  The same QAction instances
        are wired into the sidebar row and the menu bar.
    tokens : ThemeTokens
        Colour tokens for the active / inactive visual.
    density : Density
        Used for row height (``nav_height``).
    """

    # Emitted when a row is clicked (after the action triggers).
    row_activated = QtCore.pyqtSignal(PageId)
    # Emitted when the tray toggle button is clicked.
    tray_toggled = QtCore.pyqtSignal()

    def __init__(
        self,
        actions: dict[PageId, QtGui.QAction],
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMFORTABLE,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._density = density
        self._rows: dict[PageId, SidebarRow] = {}

        self.setFixedWidth(240)
        self.setObjectName("appSidebar")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header label ────────────────────────────────────────────────
        header = QtWidgets.QLabel("MINERVA")
        header.setFixedHeight(48)
        header.setStyleSheet(
            f"color: {tokens.text};"
            f"font-size: 11px;"
            f"padding: 12px 8px 12px 16px;"
            f"background-color: {tokens.background};"
            f"font-weight: 600;"
            f"letter-spacing: 1px;"
        )
        layout.addWidget(header)

        # ── Separator ────────────────────────────────────────────────────
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {tokens.surface}; border: none;")
        layout.addWidget(sep)

        # ── Sidebar rows (3 destinations) ────────────────────────────────
        icon_map = {
            PageId.REPORTS: Icons.reports(),
            PageId.LIBRARY: Icons.library(),
            PageId.SETTINGS: Icons.settings(),
        }

        label_map = {
            PageId.REPORTS: "Fix Reports",
            PageId.LIBRARY: "Library",
            PageId.SETTINGS: "Settings",
        }

        order = [
            PageId.REPORTS,
            PageId.LIBRARY,
            PageId.SETTINGS,
        ]

        for pid in order:
            if pid not in actions:
                continue
            action = actions[pid]
            icon = icon_map[pid]
            label = label_map[pid]
            row = SidebarRow(
                page_id=pid,
                icon=icon,
                label=label,
                action=action,
                tokens=tokens,
                density=density,
            )
            self._rows[pid] = row
            layout.addWidget(row)

        layout.addStretch(1)

        # ── Selection badge ───────────────────────────────────────────────
        self._selection_badge = QtWidgets.QLabel("", self)
        self._selection_badge.setObjectName("selection_badge")
        self._selection_badge.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._selection_badge.setFixedHeight(28)
        self._selection_badge.setStyleSheet(
            f"color: {tokens.text}; font-size: 11px; padding: 0 16px; opacity: 0.7;"
        )
        layout.addWidget(self._selection_badge)

        # ── Tray toggle button ────────────────────────────────────────────
        self._tray_toggle = QtWidgets.QPushButton("Downloads")
        self._tray_toggle.setObjectName("trayToggle")
        self._tray_toggle.setFixedHeight(36)
        self._tray_toggle.setIcon(Icons.download())
        self._tray_toggle.setIconSize(QtCore.QSize(16, 16))
        self._tray_toggle.setStyleSheet(
            f"QPushButton#trayToggle {{"
            f"  background-color: {tokens.background};"
            f"  color: {tokens.text};"
            f"  text-align: left;"
            f"  padding-left: 16px;"
            f"  border: none;"
            f"  border-top: 1px solid {tokens.surface};"
            f"  font-size: 12px;"
            f"}}"
            f"QPushButton#trayToggle:hover {{"
            f"  background-color: {tokens.surface};"
            f"}}"
        )
        self._tray_toggle.clicked.connect(self.tray_toggled.emit)
        layout.addWidget(self._tray_toggle)

        # Style the sidebar background
        self.setStyleSheet(
            f"QWidget#appSidebar {{ background-color: {tokens.background}; }}"
        )

    # ── Selection badge ─────────────────────────────────────────────────

    def set_selection_count(self, count: int) -> None:
        """Show how many items are currently selected."""
        if count > 0:
            self._selection_badge.setText(f"{count} selected")
        else:
            self._selection_badge.setText("")

    @property
    def rows(self) -> dict[PageId, SidebarRow]:
        return self._rows

    @property
    def tray_toggle(self) -> QtWidgets.QPushButton:
        return self._tray_toggle

    def set_active(self, page_id: PageId) -> None:
        """Highlight the row for *page_id* and deactivate others."""
        for pid, row in self._rows.items():
            row.set_active(pid == page_id)

    # ── Theme reactivity ───────────────────────────────────────────────

    def apply_tokens(self, tokens: ThemeTokens) -> None:
        """Propagate new colour tokens to header, separator, badge, and rows."""
        self._tokens = tokens
        self.setStyleSheet(
            f"QWidget#appSidebar {{ background-color: {tokens.background}; }}"
        )
        for child in self.findChildren(QtWidgets.QWidget):
            if isinstance(child, SidebarRow):
                child.apply_tokens(tokens)
            elif child.objectName() == "selection_badge":
                child.setStyleSheet(
                    f"color: {tokens.text}; font-size: 11px; padding: 0 16px; opacity: 0.7;"
                )
            elif child.objectName() == "trayToggle":
                child.setStyleSheet(
                    f"QPushButton#trayToggle {{"
                    f"  background-color: {tokens.background};"
                    f"  color: {tokens.text};"
                    f"  text-align: left;"
                    f"  padding-left: 16px;"
                    f"  border: none;"
                    f"  border-top: 1px solid {tokens.surface};"
                    f"  font-size: 12px;"
                    f"}}"
                    f"QPushButton#trayToggle:hover {{"
                    f"  background-color: {tokens.surface};"
                    f"}}"
                )
        # The header label has no objectName, so refresh by index.
        layout = self.layout()
        if layout is not None and layout.count() > 0:
            header = layout.itemAt(0).widget()
            if isinstance(header, QtWidgets.QLabel):
                header.setStyleSheet(
                    f"color: {tokens.text};"
                    f"font-size: 11px;"
                    f"padding: 12px 8px 12px 16px;"
                    f"background-color: {tokens.background};"
                    f"font-weight: 600;"
                    f"letter-spacing: 1px;"
                )
            sep = layout.itemAt(1).widget()
            if isinstance(sep, QtWidgets.QFrame):
                sep.setStyleSheet(
                    f"background-color: {tokens.surface}; border: none;"
                )

    def apply_density(self, density: Density) -> None:
        """Propagate new density to every row."""
        self._density = density
        for child in self.findChildren(QtWidgets.QWidget):
            if isinstance(child, SidebarRow):
                child.apply_density(density)
