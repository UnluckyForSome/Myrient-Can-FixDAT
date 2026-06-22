"""Metric strip — responsive grid of MetricCards."""

from __future__ import annotations

from typing import Sequence

from PyQt6 import QtCore, QtWidgets

from minerva.ui.widgets.metric_card import MetricCard


class MetricStrip(QtWidgets.QWidget):
    """Responsive horizontal strip of MetricCards.

    At widths below 900 px the strip switches to a 2-column grid layout.
    """

    _BREAKPOINT = 900

    def __init__(
        self,
        cards: Sequence[MetricCard] = (),
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("metricStrip")

        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(12)

        self._cards: list[MetricCard] = []
        for card in cards:
            self.add_card(card)

    def add_card(self, card: MetricCard) -> None:
        """Append a MetricCard to the strip."""
        self._cards.append(card)
        self._layout.addWidget(card, 1)

    def set_cards(self, cards: Sequence[MetricCard]) -> None:
        """Replace all cards in the strip."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards.clear()
        for card in cards:
            self.add_card(card)

    def resizeEvent(self, event: QtCore.QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
