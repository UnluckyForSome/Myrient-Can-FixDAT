"""Compact summary strip for the Library dashboard."""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from minerva.ui.icons import Icons


class _SummaryStat(QtWidgets.QWidget):
    def __init__(self, label: str, icon, parent=None) -> None:
        super().__init__(parent)
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        icon_label = QtWidgets.QLabel()
        icon_label.setObjectName("librarySummaryIcon")
        icon_label.setFixedSize(24, 24)
        icon_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        icon_label.setPixmap(icon.pixmap(14, 14))
        root.addWidget(icon_label)

        text = QtWidgets.QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        self.value = QtWidgets.QLabel("\u2014")
        self.value.setObjectName("librarySummaryValue")
        text.addWidget(self.value)
        caption = QtWidgets.QLabel(label)
        caption.setObjectName("librarySummaryLabel")
        text.addWidget(caption)
        root.addLayout(text)

    def set_value(self, value: str) -> None:
        self.value.setText(value)


class LibrarySummaryBar(QtWidgets.QFrame):
    """Four restrained summary values shown above the Library workspace."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("librarySummaryBar")
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(14, 9, 14, 9)
        root.setSpacing(18)

        self._results = _SummaryStat("Results", Icons.library())
        self._visible = _SummaryStat("Visible range", Icons.search())
        self._selected = _SummaryStat("Selected", Icons.check())
        self._query = _SummaryStat("Query time", Icons.activity())

        for stat in (self._results, self._visible, self._selected, self._query):
            root.addWidget(stat)
            if stat is not self._query:
                separator = QtWidgets.QFrame()
                separator.setObjectName("summarySeparator")
                separator.setFixedWidth(1)
                root.addWidget(separator)
        root.addStretch(1)

    def set_results(self, total: int, page: int, page_size: int, elapsed_ms: float) -> None:
        start = page * page_size + 1 if total else 0
        end = min(total, (page + 1) * page_size)
        self._results.set_value(f"{total:,}")
        self._visible.set_value(f"{start:,}\u2013{end:,}" if total else "0")
        self._query.set_value(f"{elapsed_ms:.0f} ms")

    def set_selected(self, count: int) -> None:
        self._selected.set_value(f"{count:,}")
