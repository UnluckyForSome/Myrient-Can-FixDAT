"""
Domain types for the indexed DAT library.

Used by the Library and Collections pages to represent indexed entries,
search requests, and faceted-search summaries.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LibraryItem:
    """A single indexed entry from the torrent-backed library."""

    id: int
    stem: str
    basename: str
    collection: str
    system: str
    size: int
    source_torrent: str
    source_index: int
    path_in_torrent: str
    tags: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()


@dataclass(frozen=True)
class FacetCount:
    """One value/count pair in a faceted search result."""

    value: str
    count: int


@dataclass(frozen=True)
class LibraryFacets:
    """Facet counts calculated for a :class:`LibraryQuery`."""

    total: int
    regions: tuple[FacetCount, ...] = ()
    categories: tuple[FacetCount, ...] = ()
    tags: tuple[FacetCount, ...] = ()


@dataclass(frozen=True)
class LibraryQuery:
    """Parameters for querying the indexed library.

    ``selected_only`` is interpreted by the UI because the selection is an
    application-session concept rather than index data.  ``categories`` are
    normalised to ``game``, ``homebrew``, ``demo`` and ``tool``.
    """

    text: str = ""
    collection: str = ""
    system: str = ""
    tags: frozenset[str] = frozenset()
    regions: frozenset[str] = frozenset()
    categories: frozenset[str] = frozenset()
    selected_only: bool = False
    file_ids: tuple[int, ...] = ()
    offset: int = 0
    limit: int = 50
    sort_field: str = "stem"
    descending: bool = False
