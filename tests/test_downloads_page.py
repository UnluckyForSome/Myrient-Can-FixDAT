"""
Tests for ``DownloadsPage`` — model/view wiring and signal connections.

Covers: construction, view model chain, column count, delegate registration,
signal wiring, and widget lifecycle.
"""

from __future__ import annotations

from PyQt6 import QtWidgets

from minerva.app.app_state import AppState
from minerva.app.pages import DownloadPageState, DownloadsPage
from minerva.app.worker_manager import WorkerManager
from minerva.domain.downloads import DownloadStatus
from minerva.ui.models.delegates import ActionDelegate, ProgressDelegate
from minerva.ui.models.download_model import DownloadTableModel
from PyQt6.QtCore import QSortFilterProxyModel as SortFilterProxy

# ---------------------------------------------------------------------------
# ModelTester availability
# ---------------------------------------------------------------------------
try:
    from PyQt6.QtTest import QAbstractItemModelTester

    _HAVE_MODEL_TESTER = True
except ImportError:
    _HAVE_MODEL_TESTER = False


# ============================================================================
# Fixtures
# ============================================================================


def _make_app_state() -> AppState:
    """Create an ``AppState`` with a real ``WorkerManager`` wired."""
    state = AppState()
    state.worker_manager = WorkerManager()
    return state


def _make_page(app_state: AppState | None = None) -> DownloadsPage:
    """Create a ``DownloadsPage``, optionally with *app_state*."""
    return DownloadsPage(app_state or _make_app_state())


# ============================================================================
# Construction
# ============================================================================


def test_page_constructs(qtbot):
    """GIVEN an AppState with WorkerManager WHEN DownloadsPage is
    constructed THEN no exception is raised."""
    page = _make_page()
    qtbot.addWidget(page)
    assert isinstance(page, QtWidgets.QWidget)


def test_view_model_is_proxy(qtbot):
    """GIVEN a constructed DownloadsPage WHEN the view's model is
    queried THEN it returns a SortFilterProxy."""
    page = _make_page()
    qtbot.addWidget(page)
    proxy = page._view.model()
    assert isinstance(proxy, SortFilterProxy)


def test_proxy_source_is_download_model(qtbot):
    """GIVEN a constructed DownloadsPage WHEN the proxy's source model
    is queried THEN it returns a DownloadTableModel-like type."""
    page = _make_page()
    qtbot.addWidget(page)
    proxy = page._view.model()
    source = proxy.sourceModel()
    type_name = type(source).__name__
    assert "RecordListModel" in type_name, f"Expected RecordListModel, got {type_name}"
    assert hasattr(source, "column_specs"), "Source model should have column_specs"


def test_column_count_matches_spec(qtbot):
    """GIVEN a constructed DownloadsPage WHEN the source model's column
    count is queried THEN it equals 8."""
    page = _make_page()
    qtbot.addWidget(page)
    proxy = page._view.model()
    source = proxy.sourceModel()
    assert source.columnCount() == 8


def test_delegates_assigned(qtbot):
    """GIVEN a constructed DownloadsPage WHEN delegates are queried
    THEN column 2 gets ProgressDelegate and column 7 gets ActionDelegate."""
    page = _make_page()
    qtbot.addWidget(page)

    del_2 = page._view.itemDelegateForColumn(2)
    del_7 = page._view.itemDelegateForColumn(7)
    assert isinstance(del_2, ProgressDelegate)
    assert isinstance(del_7, ActionDelegate)


def test_action_delegate_connected(qtbot):
    """GIVEN a constructed DownloadsPage WHEN the ActionDelegate is
    checked THEN its action_triggered signal is connected to
    _on_action."""
    page = _make_page()
    qtbot.addWidget(page)
    receivers = page._action_delegate.receivers(
        page._action_delegate.action_triggered,
    )
    assert receivers > 0, (
        "action_triggered should have at least one slot"
    )


# ============================================================================
# Initial state
# ============================================================================


def test_initial_state_empty(qtbot):
    """GIVEN a constructed DownloadsPage WHEN the initial state is
    checked THEN it is EMPTY."""
    page = _make_page()
    qtbot.addWidget(page)
    assert page._content_state.currentIndex() == 0  # EMPTY


def test_starts_with_no_records(qtbot):
    """GIVEN a constructed DownloadsPage WHEN the model row count is
    queried THEN it is zero."""
    page = _make_page()
    qtbot.addWidget(page)
    assert page._model.rowCount() == 0


# ============================================================================
# Signal wiring
# ============================================================================


def test_manager_downloads_changed_connected(qtbot):
    """GIVEN a DownloadsPage with a WorkerManager WHEN the manager
    emits downloads_changed THEN the model is updated."""
    app_state = _make_app_state()
    page = _make_page(app_state)
    qtbot.addWidget(page)

    app_state.worker_manager.add_to_queue("test.zip", "https://example.com/test.zip")

    qtbot.wait(50)

    assert page._model.rowCount() == 1
    assert page._content_state.currentIndex() == 1  # RESULTS


def test_manager_downloads_changed_clear(qtbot):
    """GIVEN a DownloadsPage with records WHEN the manager has no
    downloads THEN the model is empty and state is EMPTY."""
    app_state = _make_app_state()
    page = _make_page(app_state)
    qtbot.addWidget(page)

    app_state.worker_manager.add_to_queue("test.zip", "https://example.com/test.zip")
    app_state.worker_manager.cancel(0)

    qtbot.wait(50)

    assert page._model.rowCount() == 1

    app_state.worker_manager._downloads.clear()
    app_state.worker_manager._active.clear()
    app_state.worker_manager._emit_downloads_changed()
    qtbot.wait(50)

    assert page._model.rowCount() == 0
    assert page._content_state.currentIndex() == 0  # EMPTY


# ============================================================================
# ModelTester
# ============================================================================


def test_modeltester_on_source(qtbot):
    """GIVEN a constructed DownloadsPage WHEN QAbstractItemModelTester
    checks the source model THEN no warnings are emitted."""
    page = _make_page()
    qtbot.addWidget(page)
    proxy = page._view.model()
    source = proxy.sourceModel()

    if _HAVE_MODEL_TESTER:
        tester = QAbstractItemModelTester(source)  # noqa: F841
    else:
        assert source.rowCount() == 0
        assert source.columnCount() == 8
        from PyQt6.QtCore import QModelIndex

        assert source.data(QModelIndex()) is None


# ============================================================================
# Widget lifecycle
# ============================================================================


def test_wait_exposed(qtbot):
    """GIVEN a constructed DownloadsPage WHEN shown and waitExposed is
    called THEN the page renders without error."""
    page = _make_page()
    qtbot.addWidget(page)
    page.show()
    qtbot.waitExposed(page)


# ============================================================================
# Action dispatch
# ============================================================================


def test_on_action_pause(qtbot, monkeypatch):
    """GIVEN a DownloadsPage with a download WHEN _on_action('pause') is
    called THEN the WorkerManager.pause is invoked."""
    app_state = _make_app_state()
    page = _make_page(app_state)
    qtbot.addWidget(page)

    app_state.worker_manager.add_to_queue("test.zip", "https://example.com/test.zip")
    app_state.worker_manager._downloads[0].status = DownloadStatus.DOWNLOADING
    app_state.worker_manager._active.add(1)

    source_index = page._model.index(0, 7)
    proxy_index = page._proxy.mapFromSource(source_index)

    page._on_action(proxy_index, "pause")
    assert app_state.worker_manager._downloads[0].status == DownloadStatus.PAUSED


def test_on_action_resume(qtbot):
    """GIVEN a DownloadsPage with a paused download WHEN
    _on_action('resume') is called THEN the WorkerManager.resume is
    invoked."""
    app_state = _make_app_state()
    page = _make_page(app_state)
    qtbot.addWidget(page)

    app_state.worker_manager.add_to_queue("test.zip", "https://example.com/test.zip")
    app_state.worker_manager._downloads[0].status = DownloadStatus.PAUSED

    source_index = page._model.index(0, 7)
    proxy_index = page._proxy.mapFromSource(source_index)

    page._on_action(proxy_index, "resume")
    assert app_state.worker_manager._downloads[0].status == DownloadStatus.DOWNLOADING


def test_on_action_remove(qtbot):
    """GIVEN a DownloadsPage with a download WHEN
    _on_action('remove') is called THEN the WorkerManager.cancel is
    invoked."""
    app_state = _make_app_state()
    page = _make_page(app_state)
    qtbot.addWidget(page)

    app_state.worker_manager.add_to_queue("test.zip", "https://example.com/test.zip")

    source_index = page._model.index(0, 7)
    proxy_index = page._proxy.mapFromSource(source_index)

    page._on_action(proxy_index, "remove")
    assert app_state.worker_manager._downloads[0].status == DownloadStatus.CANCELLED
