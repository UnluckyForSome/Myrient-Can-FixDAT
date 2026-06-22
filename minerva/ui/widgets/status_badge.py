"""Compact semantic status badge used in inspectors and dense dashboards."""

from __future__ import annotations

from enum import Enum, auto

from PyQt6 import QtCore, QtWidgets

from minerva.ui.density import Density
from minerva.ui.theme import ThemeTokens


class BadgeKind(Enum):
    NEUTRAL = auto()
    INFO = auto()
    SUCCESS = auto()
    WARNING = auto()
    ERROR = auto()
    PURPLE = auto()


class StatusBadge(QtWidgets.QLabel):
    """Small pill-shaped status label with a semantic foreground/background."""

    def __init__(
        self,
        text: str = "",
        kind: BadgeKind = BadgeKind.NEUTRAL,
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMPACT,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._density = density
        self._kind = kind
        self.setObjectName("statusBadge")
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Maximum,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.setText(text)
        self._apply_style()

    def _colour_for_kind(self, kind: BadgeKind) -> tuple[str, str, str]:
        return {
            BadgeKind.NEUTRAL: (self._tokens.text_muted, self._tokens.surface_raised, self._tokens.border),
            BadgeKind.INFO: (self._tokens.accent, self._tokens.info_surface, self._tokens.info_border),
            BadgeKind.SUCCESS: (self._tokens.success, self._tokens.success_surface, self._tokens.success_border),
            BadgeKind.WARNING: (self._tokens.warning, self._tokens.warning_surface, self._tokens.warning_border),
            BadgeKind.ERROR: (self._tokens.error, self._tokens.error_surface, self._tokens.error_border),
            BadgeKind.PURPLE: (self._tokens.purple, self._tokens.purple_surface, self._tokens.purple_border),
        }[kind]

    def _apply_style(self) -> None:
        fg, bg, border = self._colour_for_kind(self._kind)
        vertical = 3 if self._density is not Density.SPACIOUS else 4
        horizontal = 9 if self._density is Density.COMPACT else 10
        self.setStyleSheet(
            "QLabel#statusBadge {"
            f" color: {fg}; background: {bg}; border: 1px solid {border};"
            f" padding: {vertical}px {horizontal}px; border-radius: 10px;"
            " font-size: 11px; font-weight: 600;"
            "}"
        )

    def set_text(self, text: str) -> None:
        self.setText(text)

    def set_kind(self, kind: BadgeKind) -> None:
        self._kind = kind
        self._apply_style()

    def apply_tokens(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens
        self._apply_style()

    def apply_density(self, density: Density) -> None:
        self._density = density
        self._apply_style()
