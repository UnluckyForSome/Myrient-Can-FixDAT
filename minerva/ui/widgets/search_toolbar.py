"""
Search toolbar — search input with optional collection/system filter combos.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets
from superqt import QSearchableComboBox

from minerva.ui.icons import Icons
from minerva.ui.theme import ThemeTokens
from minerva.ui.density import Density


class SearchToolbar(QtWidgets.QWidget):
    """Search toolbar with search input and optional ``superqt``-style combos.

    Provides a search input field, optional collection and system filter combo
    boxes, and emits signals when the search text changes or a filter is
    selected.

    Signals:
        search_triggered(str): emitted when the user presses Enter or the
            search button.
        filter_changed(str, str): emitted with (filter_name, value) when a
            filter combo changes.
    """

    search_triggered = QtCore.pyqtSignal(str)
    filter_changed = QtCore.pyqtSignal(str, str)

    def __init__(
        self,
        show_collection_filter: bool = True,
        show_system_filter: bool = True,
        placeholder: str = "Search…",
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMPACT,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._density = density
        self.setObjectName("searchToolbar")

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ── Search input ───────────────────────────────────────────────────────
        self._search_input = QtWidgets.QLineEdit()
        self._search_input.setObjectName("librarySearchInput")
        self._search_input.setPlaceholderText(placeholder)
        self._search_input.setClearButtonEnabled(True)
        self._search_input.addAction(
            Icons.search(), QtWidgets.QLineEdit.ActionPosition.LeadingPosition
        )
        self._search_input.returnPressed.connect(self._on_search)
        layout.addWidget(self._search_input, 1)

        # ── Collection filter ──────────────────────────────────────────────────
        self._collection_combo: QtWidgets.QComboBox | None = None
        if show_collection_filter:
            self._collection_combo = QSearchableComboBox()
            self._collection_combo.setObjectName("libraryFilterCombo")
            self._collection_combo.setMinimumWidth(140)
            self._collection_combo.addItem("All Collections", "")
            self._collection_combo.currentIndexChanged.connect(
                lambda: self._on_filter_changed("collection")
            )
            layout.addWidget(self._collection_combo)

        # ── System filter ──────────────────────────────────────────────────────
        self._system_combo: QtWidgets.QComboBox | None = None
        if show_system_filter:
            self._system_combo = QSearchableComboBox()
            self._system_combo.setObjectName("libraryFilterCombo")
            self._system_combo.setMinimumWidth(140)
            self._system_combo.addItem("All Systems", "")
            self._system_combo.currentIndexChanged.connect(
                lambda: self._on_filter_changed("system")
            )
            layout.addWidget(self._system_combo)

    # ── Data population ────────────────────────────────────────────────────────

    def set_collections(self, collections: list[str]) -> None:
        """Replace the collection combo items."""
        if self._collection_combo is not None:
            current = self._collection_combo.currentText()
            self._collection_combo.blockSignals(True)
            self._collection_combo.clear()
            self._collection_combo.addItem("All Collections", "")
            for c in collections:
                self._collection_combo.addItem(c, c)
            idx = self._collection_combo.findText(current)
            if idx >= 0:
                self._collection_combo.setCurrentIndex(idx)
            self._collection_combo.blockSignals(False)

    def set_systems(self, systems: list[str]) -> None:
        """Replace the system combo items."""
        if self._system_combo is not None:
            current = self._system_combo.currentText()
            self._system_combo.blockSignals(True)
            self._system_combo.clear()
            self._system_combo.addItem("All Systems", "")
            for s in systems:
                self._system_combo.addItem(s, s)
            idx = self._system_combo.findText(current)
            if idx >= 0:
                self._system_combo.setCurrentIndex(idx)
            self._system_combo.blockSignals(False)

    # ── Accessors ──────────────────────────────────────────────────────────────

    def search_text(self) -> str:
        """Return the current search text."""
        return self._search_input.text()

    def set_search_text(self, text: str) -> None:
        """Set the search input text without triggering a search."""
        self._search_input.setText(text)

    def collection(self) -> str:
        """Return the selected collection value (empty string = all)."""
        if self._collection_combo is not None:
            return self._collection_combo.currentData() or ""
        return ""

    def system(self) -> str:
        """Return the selected system value (empty string = all)."""
        if self._system_combo is not None:
            return self._system_combo.currentData() or ""
        return ""

    def set_collection(self, value: str) -> None:
        """Set the collection combo to a specific value."""
        if self._collection_combo is not None:
            idx = self._collection_combo.findData(value)
            if idx >= 0:
                self._collection_combo.setCurrentIndex(idx)

    def set_system(self, value: str) -> None:
        """Set the system combo to a specific value."""
        if self._system_combo is not None:
            idx = self._system_combo.findData(value)
            if idx >= 0:
                self._system_combo.setCurrentIndex(idx)

    def clear(self) -> None:
        """Reset search text, collection, and system to defaults."""
        self.set_search_text("")
        if self._collection_combo is not None:
            self._collection_combo.setCurrentIndex(0)
        if self._system_combo is not None:
            self._system_combo.setCurrentIndex(0)

    # ── Internal handlers ──────────────────────────────────────────────────────

    def _on_search(self) -> None:
        self.search_triggered.emit(self._search_input.text())

    def _on_filter_changed(self, filter_name: str) -> None:
        value = ""
        if filter_name == "collection" and self._collection_combo is not None:
            value = self._collection_combo.currentData() or ""
        elif filter_name == "system" and self._system_combo is not None:
            value = self._system_combo.currentData() or ""
        self.filter_changed.emit(filter_name, value)


