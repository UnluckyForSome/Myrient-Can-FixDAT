"""
Page identifier enum for the Minerva app shell.
"""

from __future__ import annotations

from enum import Enum


class PageId(Enum):
    """Canonical page identifiers.

    Each member's ``value`` doubles as the ``QSettings`` key for
    ``current_tab`` persistence.
    """

    REPORTS = "reports"
    LIBRARY = "library"
    SETTINGS = "settings"
