"""Responsive workspace — three-pane layout with breakpoint modes."""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets


class ResponsiveWorkspace(QtWidgets.QWidget):
    """Three-slot layout helper with WIDE / MEDIUM / COMPACT breakpoints.

    Slots:
        ``navigator`` — left pane (sidebar / navigation).
        ``workspace`` — centre pane (primary content).
        ``inspector`` — right pane (detail inspector).

    Breakpoints:
        WIDE    (>= 1500 px):  ``[navigator | workspace | inspector]`` via QSplitter.
        MEDIUM  (1150-1499):   inspector hidden by default, toggled via right-edge drawer.
        COMPACT (< 1150):      only workspace visible; navigator/inspector drawers toggle.
    """

    WIDE = "wide"
    MEDIUM = "medium"
    COMPACT = "compact"

    NAVIGATOR_PREFERRED = 280
    NAVIGATOR_MIN = 240
    INSPECTOR_PREFERRED = 340
    INSPECTOR_MIN = 300
    WORKSPACE_MIN = 650

    def __init__(
        self,
        navigator: QtWidgets.QWidget,
        workspace: QtWidgets.QWidget,
        inspector: QtWidgets.QWidget,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._mode = self.WIDE
        self._inspector_visible = True
        self._navigator_visible = True

        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)

        self._navigator = navigator
        self._workspace = workspace
        self._inspector = inspector

        self._splitter.addWidget(navigator)
        self._splitter.addWidget(workspace)
        self._splitter.addWidget(inspector)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.setSizes([self.NAVIGATOR_PREFERRED, self.WORKSPACE_MIN, self.INSPECTOR_PREFERRED])

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._splitter)

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._sync_visibility()

    def current_mode(self) -> str:
        return self._mode

    def set_inspector_visible(self, visible: bool) -> None:
        self._inspector_visible = visible
        self._sync_visibility()

    def set_navigator_visible(self, visible: bool) -> None:
        self._navigator_visible = visible
        self._sync_visibility()

    def _sync_visibility(self) -> None:
        if self._mode == self.WIDE:
            self._navigator.setVisible(True)
            self._inspector.setVisible(self._inspector_visible)
        elif self._mode == self.MEDIUM:
            self._navigator.setVisible(True)
            self._inspector.setVisible(False)  # drawer overlay approach
        else:  # COMPACT
            self._navigator.setVisible(False)
            self._inspector.setVisible(False)
