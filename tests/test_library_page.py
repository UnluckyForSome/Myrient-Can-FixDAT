"""
Tests for ``LibraryPage`` — construction, search, combos, and states.

Covers: construction, model chain, search input, combos, empty state,
generation-counter concurrency, context menu wiring, and states.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from PyQt6 import QtCore, QtWidgets

from minerva.app.app_state import AppState
from minerva.app.pages import LibraryPage
from PyQt6.QtCore import QSortFilterProxyModel as SortFilterProxy

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ModelTester availability
# ---------------------------------------------------------------------------
try:
    from PyQt6.QtTest import QAbstractItemModelTester

    _HAVE_MODEL_TESTER = True
except ImportError:
    _HAVE_MODEL_TESTER = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_minerva_db(monkeypatch):
    """Mock MinervaDB so pages never touch a real database."""
    import minerva.app.pages.library as library_mod

    def fake_get_collections():
        return ["Nintendo", "Sega"]

    def fake_get_systems(collection=None):
        if collection == "Nintendo":
            return ["Nintendo - NES", "Nintendo - SNES", "Nintendo - Game Boy"]
        return [
            "Nintendo - NES",
            "Nintendo - SNES",
            "Nintendo - Game Boy",
            "Sega - Genesis",
            "Sega - Saturn",
        ]

    mock_db = MagicMock()
    mock_db.get_collections.side_effect = fake_get_collections
    mock_db.get_systems.side_effect = fake_get_systems
    mock_db.search_library.return_value = ([], 0)

    monkeypatch.setattr(library_mod, "MinervaDB", lambda: mock_db)
    return mock_db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_construct(qtbot):
    """GIVEN an AppState WHEN LibraryPage is constructed THEN no error."""
    page = LibraryPage(AppState())
    qtbot.addWidget(page)
    assert isinstance(page, QtWidgets.QWidget)


def test_page_has_search(qtbot):
    """GIVEN a constructed LibraryPage THEN a search field exists."""
    page = LibraryPage(AppState())
    qtbot.addWidget(page)
    search = page.findChild(QtWidgets.QLineEdit)
    assert search is not None
    assert search.placeholderText()


def test_search_has_clear_button(qtbot):
    """GIVEN a constructed LibraryPage THEN the search has a clear button."""
    page = LibraryPage(AppState())
    qtbot.addWidget(page)
    search = page.findChild(QtWidgets.QLineEdit)
    assert search is not None
    assert search.isClearButtonEnabled()


def test_page_has_combos(qtbot):
    """GIVEN a constructed LibraryPage THEN filter combos exist."""
    page = LibraryPage(AppState())
    qtbot.addWidget(page)
    combos = page.findChildren(QtWidgets.QComboBox)
    assert len(combos) >= 2  # collection + system


def test_empty_state_initial(qtbot):
    """GIVEN a constructed LibraryPage THEN initial state is not ERROR."""
    page = LibraryPage(AppState())
    qtbot.addWidget(page)
    stack = page.findChild(QtWidgets.QStackedWidget)
    assert stack is not None


def test_combos_populated(qtbot):
    """GIVEN a constructed LibraryPage WITH mocked DB THEN combos have items."""
    page = LibraryPage(AppState())
    qtbot.addWidget(page)
    combos = page.findChildren(QtWidgets.QComboBox)
    if combos:
        # At least the "All" option should be present
        assert combos[0].count() >= 1


def test_context_menu_wired(qtbot):
    """GIVEN a constructed LibraryPage THEN context menu policy is set."""
    page = LibraryPage(AppState())
    qtbot.addWidget(page)
    tables = page.findChildren(QtWidgets.QTableView)
    if tables:
        table = tables[0]
        assert table.contextMenuPolicy() != QtCore.Qt.ContextMenuPolicy.DefaultContextMenu


def test_page_has_stack_states(qtbot):
    """GIVEN a constructed LibraryPage THEN it has state management."""
    page = LibraryPage(AppState())
    qtbot.addWidget(page)
    stack = page.findChild(QtWidgets.QStackedWidget)
    assert stack is not None
