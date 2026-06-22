"""
Page registry — lazy construction and caching of pages keyed by PageId.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PyQt6 import QtCore, QtWidgets

from minerva.app.app_state import AppState
from minerva.app.page_id import PageId


# A factory takes (page_id, app_state) and returns a QWidget.
PageFactory = Callable[[PageId, AppState], QtWidgets.QWidget]


class PageRegistry(QtCore.QObject):
    """Maps ``PageId`` → factory, caches constructed pages.

    Usage::

        registry = PageRegistry()
        registry.register(PageId.REPORTS, make_reports_page)

        page = registry.get_or_create(PageId.REPORTS, app_state)
        stack.setCurrentWidget(page)
    """

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._factories: dict[PageId, PageFactory] = {}
        self._cache: dict[PageId, QtWidgets.QWidget] = {}

    def register(self, page_id: PageId, factory: PageFactory) -> None:
        """Register a factory for *page_id*.

        Raises ``KeyError`` if the id is already registered.
        """
        if page_id in self._factories:
            raise KeyError(f"Page {page_id!r} is already registered")
        self._factories[page_id] = factory

    def get_or_create(
        self,
        page_id: PageId,
        app_state: AppState,
    ) -> QtWidgets.QWidget:
        """Return the cached page for *page_id*, constructing on first call.

        The factory is invoked with ``(page_id, app_state)``.  The
        resulting widget is added to the registry's internal cache
        and returned.
        """
        cached = self._cache.get(page_id)
        if cached is not None:
            return cached

        factory = self._factories.get(page_id)
        if factory is None:
            raise KeyError(f"No factory registered for {page_id!r}")

        page = factory(page_id, app_state)
        self._cache[page_id] = page
        return page

    def iter_constructed(self) -> Iterable[QtWidgets.QWidget]:
        """Yield all pages that have been constructed so far."""
        return iter(self._cache.values())
