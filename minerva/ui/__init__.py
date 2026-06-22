"""
Minerva design system — shared UI primitives.

Package layout (under minerva/):

    minerva/ui/
        __init__.py
        theme.py         # ThemeTokens, build_stylesheet, apply_theme
        density.py       # Density enum, DENSITY_SETTINGS_KEY
        icons.py         # Icons factory (QtAwesome wrapper)
        notifications.py # NotificationService (InfoBar/MessageBox)
        widgets/         # Shared widget library
"""

from minerva.ui.theme import ThemeTokens, build_stylesheet, apply_theme
from minerva.ui.density import Density, DENSITY_SETTINGS_KEY
from minerva.ui.icons import Icons

__all__ = [
    "ThemeTokens",
    "build_stylesheet",
    "apply_theme",
    "Density",
    "DENSITY_SETTINGS_KEY",
    "Icons",
]
