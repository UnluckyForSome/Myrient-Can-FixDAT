"""
Tag flow — flow layout of toggleable filter chips.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets
from superqt import QFlowLayout

from minerva.ui.widgets.filter_chip import FilterChip
from minerva.ui.theme import ThemeTokens
from minerva.ui.density import Density


class TagFlow(QtWidgets.QWidget):
    """Flow layout of tag/filter chips using superqt's ``QFlowLayout``.

    Each tag is represented by a ``FilterChip`` toggle button.  The flow
    layout automatically wraps chips to the next row when they exceed the
    widget width.

    Signals:
        tag_toggled(str, bool): emitted with (tag_text, checked_state) when
            a chip is toggled.
    """

    tag_toggled = QtCore.pyqtSignal(str, bool)

    def __init__(
        self,
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMPACT,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._density = density

        self._flow = QFlowLayout(self)
        self._flow.setContentsMargins(0, 0, 0, 0)
        self._flow.setSpacing(6)

        self._chips: list[FilterChip] = []
        self._chip_map: dict[str, FilterChip] = {}

    # ── Data ───────────────────────────────────────────────────────────────────

    def set_tags(self, tags: list[str], selected: set[str] | None = None) -> None:
        """Replace all tags and optionally set which are selected.

        Preserves the check state of any tag that already exists and remains
        in the new list.
        """
        selected_set: set[str] = selected or set()

        # Remove existing chips that are no longer in the list
        new_tags_set = set(tags)
        for chip in list(self._chips):
            if chip.text() not in new_tags_set:
                self._remove_chip(chip)

        # Add or update chips for the new tag list
        existing = {chip.text(): chip for chip in self._chips}
        for tag in tags:
            if tag in existing:
                chip = existing[tag]
                checked = tag in selected_set
                if chip.isChecked() != checked:
                    chip.setChecked(checked)
            else:
                chip = FilterChip(
                    text=tag,
                    checked=tag in selected_set,
                    tokens=self._tokens,
                    density=self._density,
                    parent=self,
                )
                chip.toggled.connect(self._on_chip_toggled)
                self._flow.addWidget(chip)
                self._chips.append(chip)
                self._chip_map[tag] = chip

    # ── Selection helpers ──────────────────────────────────────────────────────

    def selected_tags(self) -> set[str]:
        """Return the set of currently selected tag texts."""
        return {chip.text() for chip in self._chips if chip.isChecked()}

    def select_all(self) -> None:
        """Check every chip."""
        for chip in self._chips:
            if not chip.isChecked():
                chip.setChecked(True)

    def clear_selection(self) -> None:
        """Uncheck every chip."""
        for chip in self._chips:
            if chip.isChecked():
                chip.setChecked(False)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _remove_chip(self, chip: FilterChip) -> None:
        self._flow.removeWidget(chip)
        self._chips.remove(chip)
        self._chip_map.pop(chip.text(), None)
        chip.deleteLater()

    def _on_chip_toggled(self, checked: bool) -> None:
        chip = self.sender()
        if isinstance(chip, FilterChip):
            self.tag_toggled.emit(chip.text(), checked)

    # ── Protocol methods ───────────────────────────────────────────────────────

    def apply_tokens(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens

    def apply_density(self, density: Density) -> None:
        self._density = density
