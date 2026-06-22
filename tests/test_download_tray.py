"""
Tests for DownloadTray — expand/collapse/toggle, auto-collapse timer,
qbit status dot, speed label, toasts, set_content.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock, patch

from PyQt6 import QtCore, QtWidgets

from minerva.app.app_state import AppState
from minerva.ui.widgets.download_tray import DownloadTray, _format_speed


@dataclass
class _FakeRuntime:
    """Minimal DownloadRuntime stand-in for testing."""
    record_id: str = "r1"
    download_speed: int = 0
    upload_speed: int = 0
    progress: float = 0.0


def test_tray_constructs(qtbot):
    """GIVEN an AppState WHEN DownloadTray is constructed THEN it exists
    with collapsed height."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    qtbot.add_widget(tray)

    assert tray is not None
    assert tray.height() <= DownloadTray.collapsed_height


def test_tray_expand(qtbot):
    """GIVEN a collapsed DownloadTray WHEN expand() is called THEN
    height increases to expanded_height."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    qtbot.add_widget(tray)

    tray.expand()
    # The widget should be in expanded state
    assert tray.is_expanded


def test_tray_collapse(qtbot):
    """GIVEN an expanded DownloadTray WHEN collapse() is called THEN
    height returns to collapsed_height."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    qtbot.add_widget(tray)

    tray.expand()
    tray.collapse()
    assert not tray.is_expanded


def test_tray_toggle(qtbot):
    """GIVEN a collapsed DownloadTray WHEN toggle() is called THEN
    it expands. Calling toggle() again collapses it."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    qtbot.add_widget(tray)

    tray.toggle()
    assert tray.is_expanded

    tray.toggle()
    assert not tray.is_expanded


def test_tray_auto_collapse_timer(qtbot):
    """GIVEN a DownloadTray WHEN auto-expanded THEN it auto-collapses
    after auto_expand_ms."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    tray.auto_expand_ms = 100  # ponytail: short timer for test speed
    qtbot.add_widget(tray)

    tray.auto_expand()
    assert tray.is_expanded

    qtbot.wait(200)
    assert not tray.is_expanded


def test_tray_qbit_dot_connected(qtbot):
    """GIVEN a DownloadTray WHEN qbit_state is True THEN dot is green."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    qtbot.add_widget(tray)

    app_state.qbit_state = True
    # The dot color should indicate connected
    assert tray.qbit_connected is True


def test_tray_qbit_dot_disconnected(qtbot):
    """GIVEN a DownloadTray WHEN qbit_state is False THEN dot is red."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    qtbot.add_widget(tray)

    app_state.qbit_state = False
    assert tray.qbit_connected is False


def test_tray_set_content(qtbot):
    """GIVEN a DownloadTray WHEN set_content(widget) is called THEN
    the widget is displayed in the expanded area."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    qtbot.add_widget(tray)

    content = QtWidgets.QWidget()
    qtbot.add_widget(content)

    tray.set_content(content)
    # Content should be set
    assert tray.content_widget is content


def test_tray_queue_changed_auto_expand(qtbot):
    """GIVEN a collapsed DownloadTray WHEN queue_changed fires THEN
    the tray auto-expands."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    tray.auto_expand_ms = 100
    qtbot.add_widget(tray)

    assert not tray.is_expanded

    app_state.queue_changed.emit()

    assert tray.is_expanded

    qtbot.wait(200)
    assert not tray.is_expanded


def test_tray_speed_label_exists(qtbot):
    """GIVEN a DownloadTray WHEN constructed THEN it has a speed label."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    qtbot.add_widget(tray)

    assert tray._speed_label is not None


def test_tray_runtime_updates_speed(qtbot):
    """GIVEN a DownloadTray WHEN runtime_changed fires with speed data THEN
    the speed label shows aggregate speed."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    qtbot.add_widget(tray)

    runtimes = [
        _FakeRuntime(record_id="r1", download_speed=1024 * 1024),
        _FakeRuntime(record_id="r2", download_speed=512 * 1024),
    ]
    tray._on_runtime_changed(runtimes)

    assert "MB/s" in tray._speed_label.text()


def test_format_speed_zero():
    """GIVEN 0 bytes/sec WHEN formatted THEN '0 B/s'."""
    assert _format_speed(0) == "0 B/s"


def test_format_speed_bytes():
    """GIVEN 100 bytes/sec WHEN formatted THEN '100.0 B/s'."""
    assert _format_speed(100) == "100.0 B/s"


def test_format_speed_megabytes():
    """GIVEN 1.5 MB/sec WHEN formatted THEN shows MB/s."""
    assert _format_speed(int(1.5 * 1024 * 1024)) == "1.5 MB/s"


def test_tray_qbit_dot_unknown(qtbot):
    """GIVEN a DownloadTray WHEN qbit_state is None THEN dot is gray."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    qtbot.add_widget(tray)

    # Set qbit_state to None (unknown)
    tray._on_qbit_state_changed(None)
    assert tray._qbit_connected is None
    # The dot style should contain gray
    style = tray._dot.styleSheet()
    assert "#888888" in style


def test_tray_qbit_disconnect_toast(qtbot):
    """GIVEN a connected DownloadTray WHEN qbit disconnects THEN
    a warning toast is shown."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    qtbot.add_widget(tray)

    # Start connected
    tray._qbit_connected = True
    tray._prev_qbit_connected = True

    from minerva.ui.widgets.notification_banner import NotificationBanner
    with patch.object(NotificationBanner, "show_warning") as mock_warn:
        tray._on_qbit_state_changed(False)

    mock_warn.assert_called_once()
    assert "connection lost" in mock_warn.call_args[0][1].lower()


def test_tray_qbit_connect_no_toast(qtbot):
    """GIVEN a disconnected DownloadTray WHEN qbit connects THEN
    no disconnect toast is shown."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    qtbot.add_widget(tray)

    tray._qbit_connected = False
    tray._prev_qbit_connected = False

    from minerva.ui.widgets.notification_banner import NotificationBanner
    with patch.object(NotificationBanner, "show_warning") as mock_warn:
        tray._on_qbit_state_changed(True)

    mock_warn.assert_not_called()


def test_tray_download_complete_toast(qtbot):
    """GIVEN a DownloadTray WHEN activity_event 'check' fires THEN
    a success toast is shown."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    qtbot.add_widget(tray)

    from minerva.ui.widgets.notification_banner import NotificationBanner
    with patch.object(NotificationBanner, "show_success") as mock_success:
        tray._on_activity_event("check", "Game.iso")

    mock_success.assert_called_once()
    assert "Game.iso" in mock_success.call_args[0][2]


def test_tray_activity_event_ignored(qtbot):
    """GIVEN a DownloadTray WHEN non-check activity_event fires THEN
    no toast is shown."""
    app_state = AppState()
    tray = DownloadTray(app_state)
    qtbot.add_widget(tray)

    from minerva.ui.widgets.notification_banner import NotificationBanner
    with patch.object(NotificationBanner, "show_success") as mock_success:
        tray._on_activity_event("download-speed", "123456")

    mock_success.assert_not_called()
