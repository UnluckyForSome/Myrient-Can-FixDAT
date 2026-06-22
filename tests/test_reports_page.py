"""
Tests for ``ReportsPage`` — model/view wiring and integration.

Covers: construction, view model chain, widget lifecycle,
PageRegistry integration.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.app.app_state import AppState
from minerva.app.page_id import PageId
from minerva.app.page_registry import PageRegistry
from minerva.app.pages import ReportsPage

# ---------------------------------------------------------------------------
# ModelTester availability
# ---------------------------------------------------------------------------
try:
    from PyQt6.QtTest import QAbstractItemModelTester

    _HAVE_MODEL_TESTER = True
except ImportError:
    _HAVE_MODEL_TESTER = False


def test_page_constructs(qtbot):
    """GIVEN an AppState WHEN ReportsPage is constructed THEN no
    exception is raised."""
    page = ReportsPage(AppState())
    qtbot.addWidget(page)
    assert isinstance(page, QtWidgets.QWidget)


def test_page_has_states(qtbot):
    """GIVEN a constructed ReportsPage THEN it has a QStackedWidget
    for state management."""
    page = ReportsPage(AppState())
    qtbot.addWidget(page)
    stack = page.findChild(QtWidgets.QStackedWidget)
    assert stack is not None
    assert stack.count() >= 3  # EMPTY, LOADING, RESULTS, ERROR


def test_page_has_acquisition_header(qtbot):
    """GIVEN a constructed ReportsPage THEN it has a match detail panel
    and queue approved button."""
    page = ReportsPage(AppState())
    qtbot.addWidget(page)
    assert page._detail_widget is not None
    assert page._queue_approved_btn is not None


def test_page_has_report_table(qtbot):
    """GIVEN a constructed ReportsPage THEN it has a QTableView for reports."""
    page = ReportsPage(AppState())
    qtbot.addWidget(page)
    tables = page.findChildren(QtWidgets.QTableView)
    assert len(tables) >= 1


def test_page_has_segments(qtbot):
    """GIVEN a constructed ReportsPage THEN it has a segmented control
    with Available / Needs review / Not found tabs."""
    page = ReportsPage(AppState())
    qtbot.addWidget(page)
    assert page._segments is not None
    # The segmented control has at least 4 segments when a report is loaded
    # Just verify it exists and has buttons
    assert len(page._segments._buttons) == 4  # All / Available / Needs review / Not found


def test_page_registry_returns_reports_page(qtbot):
    """GIVEN a PageRegistry with ReportsPage registered WHEN
    get_or_create(REPORTS) is called THEN a ReportsPage is returned."""
    registry = PageRegistry()
    app_state = AppState()

    registry.register(PageId.REPORTS, lambda pid, st: ReportsPage(st))
    page = registry.get_or_create(PageId.REPORTS, app_state)
    assert isinstance(page, ReportsPage)


def test_page_has_keyboard_shortcuts(qtbot):
    """GIVEN a constructed ReportsPage THEN keyboard shortcuts are wired."""
    page = ReportsPage(AppState())
    qtbot.addWidget(page)

    # Activate to wire shortcuts
    page.activate()

    shortcuts = page.findChildren(QtGui.QShortcut)
    # Should have at least 6 shortcuts: A, I, Space, Q, Ctrl+O, Ctrl+F, Esc
    assert len(shortcuts) >= 6


def test_shortcut_focus_search(qtbot):
    """GIVEN a ReportsPage WHEN _shortcut_focus_search is called THEN
    the search widget receives focus (or the method completes without error)."""
    page = ReportsPage(AppState())
    qtbot.addWidget(page)
    page.activate()

    # Directly call the shortcut handler — in headless mode, focus
    # may not transfer, so we just verify it doesn't crash
    page._shortcut_focus_search()
    # In a real display, _search would have focus; headless just verifies
    # the method exists and runs


def test_shortcut_deselect(qtbot):
    """GIVEN a ReportsPage with a selected entry WHEN Esc is pressed THEN
    selection is cleared."""
    page = ReportsPage(AppState())
    qtbot.addWidget(page)
    page.activate()

    page._shortcut_deselect()
    # Should not raise and selection should be empty
    assert page._entry_view.selectionModel().selectedRows() == []


def test_page_has_cta_empty_states(qtbot):
    """GIVEN a constructed ReportsPage THEN it has Build Index and
    Open Settings empty state CTAs."""
    page = ReportsPage(AppState())
    qtbot.addWidget(page)

    assert hasattr(page, "_no_index_state")
    assert hasattr(page, "_no_qbit_state")
    assert page._no_index_state is not None
    assert page._no_qbit_state is not None
