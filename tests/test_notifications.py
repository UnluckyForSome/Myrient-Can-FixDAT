"""
Tests for NotificationService (NotificationBanner + QMessageBox).

No tests assert fallback behaviour — the QFluentWidgets path no longer exists.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6 import QtWidgets


@pytest.fixture
def notification_parent(qtbot):
    """A simple QMainWindow to serve as the parent for notifications."""
    win = QtWidgets.QMainWindow()
    win.setCentralWidget(QtWidgets.QWidget())
    win.show()
    qtbot.addWidget(win)
    return win


def test_toast_methods_call_notification_banner(notification_parent):
    """GIVEN a NotificationService WHEN each toast variant is called
    THEN the corresponding NotificationBanner classmethod is invoked with
    the correct parent, title, and body."""
    from minerva.ui.notifications import NotificationService
    from minerva.ui.widgets.notification_banner import NotificationBanner

    ns = NotificationService(notification_parent)

    with (
        patch.object(NotificationBanner, "show_info") as mock_info,
        patch.object(NotificationBanner, "show_success") as mock_success,
        patch.object(NotificationBanner, "show_warning") as mock_warning,
        patch.object(NotificationBanner, "show_error") as mock_error,
    ):
        ns.info("Info Title", "Info body")
        ns.success("Success Title", "Success body")
        ns.warning("Warning Title", "Warning body")
        ns.error("Error Title", "Error body")

    mock_info.assert_called_once_with(notification_parent, "Info Title", "Info body")
    mock_success.assert_called_once_with(
        notification_parent, "Success Title", "Success body"
    )
    mock_warning.assert_called_once_with(
        notification_parent, "Warning Title", "Warning body"
    )
    mock_error.assert_called_once_with(
        notification_parent, "Error Title", "Error body"
    )


def test_confirm_returns_true_on_yes(notification_parent):
    """GIVEN a NotificationService WHEN confirm() is called and the user
    clicks Yes THEN the method returns True."""
    from minerva.ui.notifications import NotificationService

    ns = NotificationService(notification_parent)

    with patch.object(
        QtWidgets.QMessageBox,
        "question",
        return_value=QtWidgets.QMessageBox.StandardButton.Yes,
    ) as mock_q:
        result = ns.confirm("Title", "Body?")

    assert result is True
    mock_q.assert_called_once()


def test_confirm_returns_false_on_no(notification_parent):
    """GIVEN a NotificationService WHEN confirm() is called and the user
    clicks No THEN the method returns False."""
    from minerva.ui.notifications import NotificationService

    ns = NotificationService(notification_parent)

    with patch.object(
        QtWidgets.QMessageBox,
        "question",
        return_value=QtWidgets.QMessageBox.StandardButton.No,
    ) as mock_q:
        result = ns.confirm("Title", "Body?")

    assert result is False
    mock_q.assert_called_once()


def test_no_qfluentwidgets_imports():
    """GIVEN the notifications.py source WHEN parsed by ast THEN no
    qfluentwidgets import statement exists."""
    source_path = (
        Path(__file__).resolve().parents[1]
        / "minerva"
        / "ui"
        / "notifications.py"
    )
    assert source_path.is_file(), f"{source_path} not found"

    tree = ast.parse(source_path.read_text("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            if "qfluentwidgets" in node.module:
                pytest.fail(f"Found qfluentwidgets import at line {node.lineno}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if "qfluentwidgets" in alias.name:
                    pytest.fail(f"Found qfluentwidgets import at line {node.lineno}")


def test_action_creates_button_and_fires_callback(notification_parent, qtbot):
    """GIVEN a NotificationService WHEN action() is called THEN a banner
    appears with an action button and clicking it fires the callback."""
    from minerva.ui.notifications import NotificationService

    ns = NotificationService(notification_parent)
    callback_fired = []

    ns.action("Title", "Body text", "Do it", lambda: callback_fired.append(True))

    # Find the action button in the parent's children
    action_buttons = notification_parent.findChildren(
        QtWidgets.QPushButton, "notificationAction"
    )
    assert len(action_buttons) >= 1, "Action button not found in banner"

    # Click the action button
    action_buttons[-1].click()
    assert callback_fired == [True], "Callback was not fired on action button click"
