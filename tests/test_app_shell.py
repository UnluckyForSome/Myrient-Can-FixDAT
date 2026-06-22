"""
Integration tests for AppShell — construction, sidebar, drop, closeEvent.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.app.page_id import PageId


# ==============================================================================
# E2E smoke — click each sidebar action and verify page shown
# ==============================================================================

def test_e2e_sidebar_actions_show_correct_pages(app_shell, qtbot):
    """GIVEN AppShell WHEN each sidebar row is clicked THEN the correct
    page is shown in the stacked widget."""
    shell = app_shell
    sidebar = shell.sidebar
    assert sidebar is not None

    stack = shell.findChild(QtWidgets.QStackedWidget)
    assert stack is not None

    # 3 top-level sidebar pages
    expected_types = {
        PageId.REPORTS: "ReportsPage",
        PageId.LIBRARY: "LibraryPage",
        PageId.SETTINGS: "SettingsPage",
    }

    for pid, expected_name in expected_types.items():
        shell.show_page(pid)
        current = stack.currentWidget()
        assert current is not None, f"No widget shown for {pid}"
        type_name = type(current).__name__
        assert type_name == expected_name, (
            f"Expected {expected_name} for {pid}, got {type_name}"
        )


# ==============================================================================
# Construction
# ==============================================================================

def test_shell_constructs_without_db(app_shell):
    """GIVEN AppShell WHEN constructed THEN it creates a window with
    native chrome and no DB dependency."""
    shell = app_shell
    assert shell.windowTitle() == "Minerva FixDAT"
    # Native chrome — no FramelessWindowHint
    assert not (
        shell.windowFlags() & QtCore.Qt.WindowType.FramelessWindowHint
    )


def test_shell_has_status_bar(app_shell):
    """GIVEN AppShell WHEN constructed THEN a status bar is present."""
    shell = app_shell
    assert shell.statusBar() is not None


# ==============================================================================
# Sidebar
# ==============================================================================

def test_sidebar_lists_three_entries(app_shell):
    """GIVEN AppShell WHEN opened THEN the sidebar has exactly 3 rows."""
    sidebar = app_shell.sidebar
    assert sidebar is not None
    assert len(sidebar.rows) == 3


def test_shell_has_download_tray(app_shell):
    """GIVEN AppShell WHEN constructed THEN a DownloadTray exists
    below the stacked widget."""
    tray = app_shell.tray
    assert tray is not None
    assert not tray.is_expanded


def test_tray_toggle_connected_to_sidebar(app_shell, qtbot):
    """GIVEN AppShell WHEN sidebar tray toggle is clicked THEN
    the download tray toggles."""
    shell = app_shell
    assert not shell.tray.is_expanded

    shell.sidebar.tray_toggle.click()

    assert shell.tray.is_expanded

    shell.sidebar.tray_toggle.click()

    assert not shell.tray.is_expanded


def test_sidebar_action_switches_stack(app_shell):
    """GIVEN AppShell with REPORTS shown WHEN the LIBRARY sidebar
    action is triggered THEN the stacked widget shows the Library
    page."""
    shell = app_shell

    # Initially REPORTS is the default
    shell.show_page(PageId.LIBRARY)

    stack = shell.findChild(QtWidgets.QStackedWidget)
    assert stack is not None
    current = stack.currentWidget()
    assert current is not None


def test_show_page_reuses_cached_instance(app_shell):
    """GIVEN AppShell with pages that have been shown WHEN show_page
    is called again THEN the same widget instance is returned."""
    shell = app_shell

    shell.show_page(PageId.REPORTS)
    first = shell.findChild(QtWidgets.QStackedWidget).currentWidget()

    shell.show_page(PageId.LIBRARY)
    shell.show_page(PageId.REPORTS)

    second = shell.findChild(QtWidgets.QStackedWidget).currentWidget()
    assert first is second


# ==============================================================================
# Drop routing
# ==============================================================================

def test_drop_routed_to_active_page(app_shell, qtbot):
    """GIVEN AppShell with a page that implements handle_drop WHEN a
    drop event is delivered THEN the active page's handle_drop is
    called."""
    shell = app_shell

    # Show REPORTS and spy on its handle_drop
    shell.show_page(PageId.REPORTS)
    current = shell.findChild(QtWidgets.QStackedWidget).currentWidget()

    with patch.object(current, "handle_drop") as mock_handle:
        # Create a synthetic drop event
        mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile("/tmp/test.dat")])
        event = QtGui.QDropEvent(
            QtCore.QPointF(50, 50),
            QtCore.Qt.DropAction.CopyAction,
            mime,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        shell.dropEvent(event)

        mock_handle.assert_called_once_with(event)


# ==============================================================================
# closeEvent
# ==============================================================================

def test_close_event_without_worker_proceeds(app_shell, monkeypatch):
    """GIVEN AppShell with no active worker WHEN closeEvent fires THEN
    the event is accepted."""
    shell = app_shell
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QMessageBox.question",
        lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Yes,
    )

    event = QtGui.QCloseEvent()
    shell.closeEvent(event)
    assert event.isAccepted()


def test_close_event_while_idle_does_not_prompt(app_shell, monkeypatch):
    """GIVEN AppShell with idle WorkerManager WHEN closeEvent fires
    THEN no QMessageBox is shown (worker not active)."""
    shell = app_shell
    assert not shell.worker_manager.is_active()

    question_calls = []
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QMessageBox.question",
        lambda *a, **kw: (
            question_calls.append(1)
            or QtWidgets.QMessageBox.StandardButton.Yes
        ),
    )

    event = QtGui.QCloseEvent()
    shell.closeEvent(event)

    assert len(question_calls) == 0, "No prompt expected when idle"
    assert event.isAccepted()


def test_close_event_while_worker_active_prompts_and_aborts(
    app_shell, monkeypatch,
):
    """GIVEN AppShell with active worker WHEN closeEvent fires and
    user clicks Cancel THEN the event is ignored."""
    shell = app_shell

    # Make worker report active
    monkeypatch.setattr(
        shell.worker_manager,
        "is_active",
        lambda: True,
    )

    # Simulate user clicking Cancel
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QMessageBox.question",
        lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Cancel,
    )

    event = QtGui.QCloseEvent()
    shell.closeEvent(event)

    assert not event.isAccepted(), "Close should be aborted on Cancel"


# ==============================================================================
# Worker survival across page swaps
# ==============================================================================


def test_worker_survives_page_swap(app_shell, qtbot, monkeypatch):
    """GIVEN AppShell with a running DownloadWorker WHEN show_page swaps
    pages THEN the worker continues running AND WorkerManager.is_active()
    remains True."""
    from unittest.mock import Mock

    from minerva.app.page_id import PageId

    shell = app_shell

    # Attach a mocked worker that reports running
    worker = Mock()
    worker.isRunning.return_value = True
    shell.worker_manager.download_worker = worker  # type: ignore[assignment]

    # Page swap: REPORTS → LIBRARY → REPORTS
    shell.show_page(PageId.LIBRARY)
    shell.show_page(PageId.REPORTS)

    # Worker must still be running after two page swaps
    assert shell.worker_manager.is_active() is True
    worker.stop.assert_not_called()

    # Now simulate shutdown
    worker.isRunning.side_effect = [True, False]
    shell.worker_manager.prepare_shutdown(timeout_ms=100)
    worker.stop.assert_called_once()

    # Reset for fixture teardown closeEvent
    worker.isRunning.side_effect = None
    worker.isRunning.return_value = False


# ==============================================================================
# closeEvent
# ==============================================================================


def test_close_event_calls_prepare_close_on_pages(app_shell, monkeypatch):
    """GIVEN AppShell with a constructed page WHEN closeEvent fires
    THEN prepare_close is called on that page."""
    shell = app_shell

    # Construct the Reports page
    shell.show_page(PageId.REPORTS)
    page = shell.findChild(QtWidgets.QStackedWidget).currentWidget()

    monkeypatch.setattr(
        "PyQt6.QtWidgets.QMessageBox.question",
        lambda *a, **kw: QtWidgets.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(shell, "_auto_save_queue", lambda: None)
    monkeypatch.setattr(shell, "_save_settings", lambda: None)

    with patch.object(page, "prepare_close") as mock_prep:
        event = QtGui.QCloseEvent()
        shell.closeEvent(event)
        mock_prep.assert_called_once()
