"""
Pagination bar — page navigation with page-size selector.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from minerva.ui.theme import ThemeTokens
from minerva.ui.density import Density

_DEFAULT_PAGE_SIZES = [25, 50, 100, 250]


class PaginationBar(QtWidgets.QWidget):
    """Page navigation bar: Previous / Page X of Y / Next.

    Includes a page-size combo box and emits ``page_changed`` when the user
    changes the current page.

    Signals:
        page_changed(int): emitted with the new page number (0-indexed).
        page_size_changed(int): emitted when the user picks a different page
            size from the combo box.
    """

    page_changed = QtCore.pyqtSignal(int)
    page_size_changed = QtCore.pyqtSignal(int)

    def __init__(
        self,
        page_size: int = 50,
        page_sizes: list[int] | None = None,
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMPACT,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._density = density

        self._current_page: int = 0
        self._total_items: int = 0
        self._page_size: int = page_size
        self._page_sizes: list[int] = page_sizes or _DEFAULT_PAGE_SIZES

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addStretch(1)

        # ── Previous button ────────────────────────────────────────────────────
        self._prev_btn = QtWidgets.QPushButton("← Previous")
        self._prev_btn.setObjectName("subtleButton")
        self._prev_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._prev_btn.clicked.connect(self._go_previous)
        layout.addWidget(self._prev_btn)

        # ── Page indicator ─────────────────────────────────────────────────────
        self._page_label = QtWidgets.QLabel("Page 0 of 0")
        self._page_label.setObjectName("mutedLabel")
        layout.addWidget(self._page_label)

        # ── Next button ────────────────────────────────────────────────────────
        self._next_btn = QtWidgets.QPushButton("Next →")
        self._next_btn.setObjectName("subtleButton")
        self._next_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._next_btn.clicked.connect(self._go_next)
        layout.addWidget(self._next_btn)

        # ── Page size combo ────────────────────────────────────────────────────
        layout.addSpacing(12)
        size_label = QtWidgets.QLabel("Per page:")
        size_label.setObjectName("mutedLabel")
        layout.addWidget(size_label)

        self._size_combo = QtWidgets.QComboBox()
        self._size_combo.addItems([str(s) for s in self._page_sizes])
        self._size_combo.setCurrentText(str(page_size))
        self._size_combo.currentTextChanged.connect(self._on_page_size_changed)
        layout.addWidget(self._size_combo)

        self._update_controls()

    # ── Configuration ──────────────────────────────────────────────────────────

    def configure(self, total_items: int, current_page: int = 0) -> None:
        """Update the total item count and the current page (0-indexed)."""
        self._total_items = total_items
        self._current_page = current_page
        self._update_controls()

    def page_size(self) -> int:
        """Return the currently selected page size."""
        return int(self._size_combo.currentText())

    # ── Navigation ─────────────────────────────────────────────────────────────

    def _go_previous(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._update_controls()
            self.page_changed.emit(self._current_page)

    def _go_next(self) -> None:
        max_page = self._max_page()
        if self._current_page < max_page:
            self._current_page += 1
            self._update_controls()
            self.page_changed.emit(self._current_page)

    def _on_page_size_changed(self, _text: str) -> None:
        self._page_size = int(self._size_combo.currentText())
        self._current_page = 0
        self._update_controls()
        self.page_size_changed.emit(self._page_size)
        self.page_changed.emit(0)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _max_page(self) -> int:
        if self._page_size <= 0 or self._total_items <= 0:
            return 0
        return max(0, (self._total_items - 1) // self._page_size)

    def _update_controls(self) -> None:
        max_page = self._max_page()
        total_pages = max_page + 1 if self._total_items > 0 else 0

        self._page_label.setText(
            f"Page {self._current_page + 1} of {total_pages}"
            f"  ({self._total_items} items)"
        )
        self._prev_btn.setEnabled(self._current_page > 0)
        self._next_btn.setEnabled(self._current_page < max_page)


