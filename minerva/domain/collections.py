"""Domain types for collection and index diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class CollectionStatus(Enum):
    INDEXED = "indexed"
    PARTIAL = "partial"
    MISSING = "missing"


@dataclass(frozen=True)
class IndexOverview:
    collections: int
    systems: int
    files: int
    database_size: int
    last_build: datetime | None


@dataclass(frozen=True)
class CollectionSummary:
    name: str
    systems: int
    files: int
    status: CollectionStatus


@dataclass(frozen=True)
class SystemSummary:
    collection: str
    system: str
    files: int
    last_update: datetime | None
    source_present: bool
    expected_files: int | None

    @property
    def coverage(self) -> float | None:
        if not self.expected_files:
            return None
        return min(1.0, self.files / self.expected_files)


@dataclass(frozen=True)
class ReferenceDat:
    """A user-imported DAT used as an expected-count reference."""

    id: str
    path: str
    name: str
    collection: str | None
    system: str | None
    entry_count: int
    imported_at: str
