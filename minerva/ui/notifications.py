"""
Notification service — transient toasts using NotificationBanner and
confirmation dialogs using QMessageBox.

Usage::

    from minerva.ui.notifications import NotificationService
    ns = NotificationService(parent_widget)
    ns.info("Search complete", "Found 42 results")
    ns.success("Download done")
    ns.warning("Disk space low")
    ns.error("Connection failed", "Check your network")
    if ns.confirm("Delete?", "This cannot be undone."):
        # proceed

Transient toasts use ``NotificationBanner`` — a styled QFrame that slides in
from the top of the parent widget.  Confirmation dialogs use
``QMessageBox.question``.

This file must NOT import ``qfluentwidgets`` — the notification contract is
pure PyQt6.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6 import QtCore, QtWidgets

from minerva.ui.widgets.notification_banner import NotificationBanner


class NotificationService:
    """Transient on-screen notifications and modal confirmations.

    ``parent`` should be the main window or the widget over which
    notifications should appear.
    """

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        self._parent = parent

    # ── Toasts ────────────────────────────────────────────────────────────

    def info(self, title: str, body: str = "") -> None:
        NotificationBanner.show_info(self._parent, title, body)

    def success(self, title: str, body: str = "") -> None:
        NotificationBanner.show_success(self._parent, title, body)

    def warning(self, title: str, body: str = "") -> None:
        NotificationBanner.show_warning(self._parent, title, body)

    def error(self, title: str, body: str = "") -> None:
        NotificationBanner.show_error(self._parent, title, body)

    # ── Confirmations ─────────────────────────────────────────────────────

    def confirm(self, title: str, body: str) -> bool:
        """Show a modal confirmation dialog.

        Returns ``True`` if the user clicked Yes.
        """
        reply = QtWidgets.QMessageBox.question(
            self._parent,
            title,
            body,
            QtWidgets.QMessageBox.StandardButton.Yes,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        return reply == QtWidgets.QMessageBox.StandardButton.Yes

    # ── Action toasts ─────────────────────────────────────────────────────

    def action(self, title: str, body: str, action_label: str, callback: Callable) -> None:
        """Show a toast with an action button.

        The toast displays *title* and *body*, plus a button labeled
        *action_label*. If the user clicks the button, *callback* is invoked.
        """
        banner = NotificationBanner.show_info(self._parent, title, body, duration=8000)
        # ponytail: add an action button to the existing banner layout.
        # The banner's internal layout is a QHBoxLayout with icon, text, close.
        btn = QtWidgets.QPushButton(action_label, banner)
        btn.setObjectName("notificationAction")
        btn.setFixedHeight(24)
        btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: (callback(), banner._on_close()))

        # Insert before the close button (last widget in layout)
        layout = banner.layout()
        if layout is not None:
            layout.insertWidget(layout.count() - 1, btn)
