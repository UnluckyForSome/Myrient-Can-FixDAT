"""
Data types for fix-reports and downloads.

Extracted from ``minerva_gui`` during the legacy cleanup (Phase 11).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SAVED_QUEUE_PATH = Path("saved_queue.json")
"""Path to the auto-saved queue file (JSON)."""


@dataclass
class QueueItem:
    """A loaded fix report with its match results."""

    path: str
    name: str
    entries_count: int
    matched_count: int
    unmatched_count: int
    matched_size: int
    report: object  # MatchReport
