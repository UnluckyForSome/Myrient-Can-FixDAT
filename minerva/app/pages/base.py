"""
Shared page base class for all shell-managed pages.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from minerva.app.app_state import AppState


# ── Helpers ────────────────────────────────────────────────────────────────


def _state_label(text: str) -> QtWidgets.QLabel:
    """Create a centered QLabel for page EMPTY/LOADING/ERROR states."""
    label = QtWidgets.QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setObjectName("stateLabel")
    return label


class BasePage(QtWidgets.QWidget):
    """Abstract page widget managed by AppShell via PageRegistry.

    Subclasses receive an ``AppState`` reference and should read from it
    rather than holding parallel copies of AppState fields.

    Lifecycle
    ---------
    * ``activate()``  — called when the page becomes visible.
    * ``deactivate()`` — called when the page is no longer visible.
    * ``refresh()``   — called when the page should reload its data.
    * ``prepare_close()`` — called before the shell destroys the page.
    """

    notification_requested = QtCore.pyqtSignal(object)  # NotificationPayload
    status_message_requested = QtCore.pyqtSignal(str)

    def __init__(
        self,
        app_state: AppState,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_state = app_state

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def app_state(self) -> AppState:
        return self._app_state

    def activate(self) -> None:
        """Called when this page becomes the visible page."""

    def can_deactivate(self) -> bool:
        """Return False to cancel navigation away from this page."""
        return True

    def deactivate(self) -> None:
        """Called when this page is no longer visible."""

    def refresh(self) -> None:
        """Called when the page should reload its data."""

    def handle_drop(self, event: QtGui.QDropEvent) -> None:
        """Override in pages that accept file drops."""

    def prepare_close(self) -> None:
        """Override to flush buffers / disconnect signals before close."""
