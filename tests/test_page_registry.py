"""
Tests for PageRegistry — factory invocation and caching.
"""

from __future__ import annotations

from unittest.mock import Mock

from PyQt6 import QtWidgets

from minerva.app.app_state import AppState
from minerva.app.page_id import PageId
from minerva.app.page_registry import PageRegistry


def test_get_or_create_invokes_factory_on_first_call(qtbot):
    """GIVEN a registered factory WHEN get_or_create is called the
    first time THEN the factory is invoked exactly once."""
    registry = PageRegistry()
    app_state = AppState()
    factory = Mock(return_value=QtWidgets.QWidget())

    registry.register(PageId.REPORTS, factory)
    page = registry.get_or_create(PageId.REPORTS, app_state)

    assert factory.call_count == 1
    assert page is factory.return_value


def test_get_or_create_returns_cached_on_second_call(qtbot):
    """GIVEN a page has been constructed once WHEN get_or_create is
    called again THEN the factory is NOT invoked and the same
    instance is returned."""
    registry = PageRegistry()
    app_state = AppState()
    factory = Mock(return_value=QtWidgets.QWidget())

    registry.register(PageId.REPORTS, factory)
    first = registry.get_or_create(PageId.REPORTS, app_state)
    second = registry.get_or_create(PageId.REPORTS, app_state)

    assert factory.call_count == 1
    assert first is second


def test_factory_receives_page_id_and_app_state(qtbot):
    """GIVEN a registered factory WHEN invoked THEN it receives
    (page_id, app_state)."""
    registry = PageRegistry()
    app_state = AppState()
    factory = Mock(return_value=QtWidgets.QWidget())

    registry.register(PageId.LIBRARY, factory)
    registry.get_or_create(PageId.LIBRARY, app_state)

    factory.assert_called_once_with(PageId.LIBRARY, app_state)


def test_get_or_create_raises_on_unregistered(qtbot):
    """GIVEN a PageRegistry with no factory for a PageId WHEN
    get_or_create is called THEN KeyError is raised."""
    registry = PageRegistry()
    app_state = AppState()

    import pytest
    with pytest.raises(KeyError, match="No factory registered"):
        registry.get_or_create(PageId.SETTINGS, app_state)


def test_register_raises_on_duplicate(qtbot):
    """GIVEN a PageRegistry with an existing registration WHEN
    register is called again with the same PageId THEN KeyError."""
    registry = PageRegistry()
    factory = Mock(return_value=QtWidgets.QWidget())

    registry.register(PageId.SETTINGS, factory)
    import pytest
    with pytest.raises(KeyError, match="already registered"):
        registry.register(PageId.SETTINGS, factory)


def test_iter_constructed_yields_only_cached(qtbot):
    """GIVEN a PageRegistry with multiple registrations WHEN some
    pages have been constructed THEN iter_constructed yields only
    those pages."""
    registry = PageRegistry()
    app_state = AppState()

    def make_factory():
        return Mock(return_value=QtWidgets.QWidget())

    registry.register(PageId.REPORTS, make_factory())
    registry.register(PageId.LIBRARY, make_factory())
    registry.register(PageId.SETTINGS, make_factory())

    # Construct only REPORTS and SETTINGS
    r = registry.get_or_create(PageId.REPORTS, app_state)
    s = registry.get_or_create(PageId.SETTINGS, app_state)

    constructed = list(registry.iter_constructed())
    assert len(constructed) == 2
    assert r in constructed
    assert s in constructed
