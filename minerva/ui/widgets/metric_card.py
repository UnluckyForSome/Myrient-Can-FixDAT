"""Restrained KPI card with semantic icon and value colour."""

from __future__ import annotations

from enum import Enum, auto

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.ui.density import Density
from minerva.ui.theme import ThemeTokens


class MetricKind(Enum):
    NEUTRAL = auto()
    SUCCESS = auto()
    WARNING = auto()
    ERROR = auto()
    INFO = auto()
    PURPLE = auto()


class MetricCard(QtWidgets.QFrame):
    """Dashboard KPI card that keeps semantic colour subordinate to the value."""

    def __init__(
        self,
        label: str,
        value: str = "",
        kind: MetricKind = MetricKind.NEUTRAL,
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMPACT,
        parent: QtWidgets.QWidget | None = None,
        *,
        icon: QtGui.QIcon | None = None,
        subtitle: str = "",
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._density = density
        self._kind = kind
        self._icon = icon

        self.setObjectName("metricCard")

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QtWidgets.QVBoxLayout()
        body.setContentsMargins(
            density.card_padding,
            max(10, density.card_padding - 2),
            density.card_padding,
            max(10, density.card_padding - 2),
        )
        body.setSpacing(4)
        root.addLayout(body, 1)

        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(9)

        self._icon_container = QtWidgets.QFrame()
        self._icon_container.setObjectName("metricIconContainer")
        self._icon_container.setFixedSize(34, 34)
        icon_layout = QtWidgets.QVBoxLayout(self._icon_container)
        icon_layout.setContentsMargins(7, 7, 7, 7)
        self.icon_widget = QtWidgets.QLabel()
        self.icon_widget.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.icon_widget.setScaledContents(True)
        icon_layout.addWidget(self.icon_widget)
        self._icon_container.setVisible(icon is not None)
        top.addWidget(self._icon_container)

        self.label_widget = QtWidgets.QLabel(label)
        self.label_widget.setObjectName("metricTitle")
        top.addWidget(self.label_widget, 1)
        body.addLayout(top)

        self.value_widget = QtWidgets.QLabel(value)
        self.value_widget.setObjectName("metricValue")
        body.addWidget(self.value_widget)

        self.subtitle_widget = QtWidgets.QLabel(subtitle)
        self.subtitle_widget.setObjectName("metricSubtitle")
        self.subtitle_widget.setVisible(bool(subtitle))
        body.addWidget(self.subtitle_widget)

        self._apply_semantic_style()

    def _colour(self) -> tuple[str, str]:
        colour = {
            MetricKind.NEUTRAL: self._tokens.text_muted,
            MetricKind.SUCCESS: self._tokens.success,
            MetricKind.WARNING: self._tokens.warning,
            MetricKind.ERROR: self._tokens.error,
            MetricKind.INFO: self._tokens.accent,
            MetricKind.PURPLE: self._tokens.purple,
        }[self._kind]
        soft = {
            MetricKind.NEUTRAL: self._tokens.surface_raised,
            MetricKind.SUCCESS: self._tokens.success_surface,
            MetricKind.WARNING: self._tokens.warning_surface,
            MetricKind.ERROR: self._tokens.error_surface,
            MetricKind.INFO: self._tokens.info_surface,
            MetricKind.PURPLE: self._tokens.purple_surface,
        }[self._kind]
        return colour, soft

    def _apply_semantic_style(self) -> None:
        colour, soft = self._colour()
        self._icon_container.setStyleSheet(
            "QFrame#metricIconContainer {"
            f" background: {soft}; border: 1px solid {colour}; border-radius: 8px;"
            "}"
        )
        if self._icon is not None:
            self.icon_widget.setPixmap(self._icon.pixmap(20, 20))

    def set_value(self, text: str) -> None:
        self.value_widget.setText(text)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_widget.setText(text)
        self.subtitle_widget.setVisible(bool(text))

    def set_icon(self, icon: QtGui.QIcon | None) -> None:
        self._icon = icon
        self._icon_container.setVisible(icon is not None)
        self._apply_semantic_style()

    def set_kind(self, kind: MetricKind) -> None:
        self._kind = kind
        self._apply_semantic_style()

    def apply_tokens(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens
        self._apply_semantic_style()

    def apply_density(self, density: Density) -> None:
        self._density = density
