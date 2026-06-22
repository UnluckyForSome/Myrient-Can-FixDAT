"""
Density modes for the Minerva design system.

Provides a ``Density`` enum with three levels — COMPACT, COMFORTABLE, SPACIOUS —
each carrying pre-computed pixel values for layout primitives.

``DENSITY_SETTINGS_KEY`` is the QSettings key used to persist the user's choice.
"""

from __future__ import annotations

from enum import Enum


DENSITY_SETTINGS_KEY = "ui/density"


class Density(Enum):
    """UI density affecting row heights, control sizes, and spacing."""

    COMPACT = "compact"
    COMFORTABLE = "comfortable"
    SPACIOUS = "spacious"

    @property
    def row_height(self) -> int:
        return {Density.COMPACT: 28, Density.COMFORTABLE: 36, Density.SPACIOUS: 44}[
            self
        ]

    @property
    def control_height(self) -> int:
        return {Density.COMPACT: 32, Density.COMFORTABLE: 38, Density.SPACIOUS: 44}[
            self
        ]

    @property
    def nav_height(self) -> int:
        return {Density.COMPACT: 36, Density.COMFORTABLE: 44, Density.SPACIOUS: 52}[
            self
        ]

    @property
    def card_padding(self) -> int:
        return {Density.COMPACT: 12, Density.COMFORTABLE: 16, Density.SPACIOUS: 20}[
            self
        ]

    @property
    def page_spacing(self) -> int:
        return {Density.COMPACT: 12, Density.COMFORTABLE: 18, Density.SPACIOUS: 24}[
            self
        ]
