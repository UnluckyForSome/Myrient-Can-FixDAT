"""Semantic theme tokens and stylesheet builder for Minerva."""

from __future__ import annotations

from dataclasses import dataclass, replace

from minerva.ui.density import Density
from minerva.ui.qss.loader import load_qss


@dataclass(frozen=True)
class ThemeTokens:
    # Core surfaces
    background: str = "#101722"
    surface: str = "#172230"
    surface_raised: str = "#1d2a38"
    border: str = "#2b3a4a"

    # Typography
    text: str = "#eef3f8"
    text_muted: str = "#94a3b8"
    disabled_text: str = "#59687a"
    scrollbar: str = "#3a4a5d"

    # Semantic accents
    accent: str = "#3b82f6"
    accent_hover: str = "#4b8cf7"
    success: str = "#57c785"
    warning: str = "#f0ad4e"
    error: str = "#ef6b73"
    purple: str = "#a855f7"

    # Semantic surfaces (pill backgrounds)
    success_surface: str = "#153126"
    success_border: str = "#285f45"
    warning_surface: str = "#352817"
    warning_border: str = "#6e5125"
    error_surface: str = "#351d25"
    error_border: str = "#71343f"
    info_surface: str = "#162d49"
    info_border: str = "#28527f"
    purple_surface: str = "#2a1d3c"
    purple_border: str = "#543477"

    # Semantic surface aliases (fg/bg/border naming) — required by
    # StatusBadge, MetricCard, Banner, Pill semantics.
    success_fg: str = "#57c785"
    success_bg: str = "#153126"
    warning_fg: str = "#f0ad4e"
    warning_bg: str = "#352817"
    error_fg: str = "#ef6b73"
    error_bg: str = "#351d25"
    info_fg: str = "#3b82f6"
    info_bg: str = "#162d49"
    purple_fg: str = "#a855f7"
    purple_bg: str = "#2a1d3c"

    @classmethod
    def for_accent(cls, name: str) -> "ThemeTokens":
        accents = {
            "blue": "#3b82f6",
            "purple": "#8b5cf6",
            "green": "#22c55e",
        }
        return cls(accent=accents.get(name, accents["blue"]))

    def to_dict(self) -> dict[str, str]:
        return {
            "background": self.background,
            "surface": self.surface,
            "surface_raised": self.surface_raised,
            "border": self.border,
            "text": self.text,
            "text_muted": self.text_muted,
            "disabled_text": self.disabled_text,
            "scrollbar": self.scrollbar,
            "accent": self.accent,
            "accent_hover": self.accent_hover,
            "success": self.success,
            "warning": self.warning,
            "error": self.error,
            "purple": self.purple,
            "success_surface": self.success_surface,
            "success_border": self.success_border,
            "warning_surface": self.warning_surface,
            "warning_border": self.warning_border,
            "error_surface": self.error_surface,
            "error_border": self.error_border,
            "info_surface": self.info_surface,
            "info_border": self.info_border,
            "purple_surface": self.purple_surface,
            "purple_border": self.purple_border,
            # New semantic aliases
            "success_fg": self.success_fg,
            "success_bg": self.success_bg,
            "warning_fg": self.warning_fg,
            "warning_bg": self.warning_bg,
            "error_fg": self.error_fg,
            "error_bg": self.error_bg,
            "info_fg": self.info_fg,
            "info_bg": self.info_bg,
            "purple_fg": self.purple_fg,
            "purple_bg": self.purple_bg,
        }


def _load_qss_template() -> str:
    """Load the full QSS cascade via the ordered loader."""
    return load_qss()


def build_stylesheet(tokens: ThemeTokens, density: Density) -> str:
    qss = _load_qss_template()
    for name, value in tokens.to_dict().items():
        qss = qss.replace(f"{{{{token.{name}}}}}", value)
    for name, value in {
        "row_height": density.row_height,
        "control_height": density.control_height,
        "nav_height": density.nav_height,
        "card_padding": density.card_padding,
        "page_spacing": density.page_spacing,
    }.items():
        qss = qss.replace(f"{{{{density.{name}}}}}", str(value))
    return qss


def apply_theme(qapp, tokens: ThemeTokens | None = None, density: Density | None = None) -> None:
    qapp.setStyleSheet(build_stylesheet(tokens or ThemeTokens(), density or Density.COMPACT))
