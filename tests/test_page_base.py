"""
Tests for PageBase — no-op defaults don't raise.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui

from minerva.app.app_state import AppState
from minerva.app.pages.base import BasePage as PageBase


def test_handle_drop_noop(qtbot):
    """GIVEN a PageBase instance WHEN handle_drop is called THEN no
    exception is raised (no-op default)."""
    state = AppState()
    page = PageBase(state)
    qtbot.add_widget(page)

    # Create a dummy drop event — we just verify method exists and runs
    event = QtGui.QDropEvent(
        QtCore.QPointF(0, 0),
        QtCore.Qt.DropAction.CopyAction,
        QtCore.QMimeData(),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    page.handle_drop(event)  # must not raise


def test_prepare_close_noop(qtbot):
    """GIVEN a PageBase instance WHEN prepare_close is called THEN no
    exception is raised (no-op default)."""
    state = AppState()
    page = PageBase(state)
    qtbot.add_widget(page)

    page.prepare_close()  # must not raise


def test_app_state_property(qtbot):
    """GIVEN a PageBase with an AppState WHEN accessing app_state THEN
    the same instance is returned."""
    state = AppState()
    page = PageBase(state)
    qtbot.add_widget(page)

    assert page.app_state is state


def test_can_subclass(qtbot):
    """GIVEN a subclass of PageBase WHEN instantiated THEN it works
    as a normal QWidget."""
    state = AppState()

    class TestPage(PageBase):
        def handle_drop(self, event):
            self._dropped = True

    page = TestPage(state)
    qtbot.add_widget(page)
    assert isinstance(page, PageBase)
