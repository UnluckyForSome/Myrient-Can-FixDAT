"""
Activity list — compact event log widget.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.ui.icons import Icons
from minerva.ui.theme import ThemeTokens
from minerva.ui.density import Density

# Category → icon factory mapping (lazy — avoids calling QtAwesome at import time)
_CATEGORY_ICON_FACTORIES: dict[str, callable] = {
    "download": Icons.download,
    "check": Icons.check,
    "error": Icons.error,
    "skip": Icons.skip,
    "search": Icons.search,
    "activity": Icons.activity,
    "info": Icons.search,
}


class _ActivityItemWidget(QtWidgets.QWidget):
    """Custom widget rendered inside each QListWidgetItem."""

    def __init__(
        self,
        icon: QtGui.QIcon,
        message: str,
        timestamp: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        # Icon
        icon_lbl = QtWidgets.QLabel()
        icon_lbl.setFixedSize(18, 18)
        icon_lbl.setPixmap(icon.pixmap(18, 18))
        layout.addWidget(icon_lbl)

        # Message
        msg_lbl = QtWidgets.QLabel(message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setObjectName("activityMessage")
        layout.addWidget(msg_lbl, 1)

        # Timestamp
        ts_lbl = QtWidgets.QLabel(timestamp)
        ts_lbl.setObjectName("activityTimestamp")
        ts_lbl.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(ts_lbl)


class ActivityList(QtWidgets.QWidget):
    """Activity log widget — compact event list for the Downloads page.

    Uses a ``QListWidget`` with custom item widgets to show recent activity
    events with category-specific icons.

    Usage::

        activity = ActivityList(parent)
        activity.add_event("download", "Started downloading foo.zip", "14:32")
        activity.add_event("check", "Match verified", "14:33")
        activity.add_event("error", "Connection lost", "14:34")
    """

    def __init__(
        self,
        max_items: int = 100,
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMPACT,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._density = density
        self._max_items = max_items

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._list = QtWidgets.QListWidget()
        self._list.setObjectName("activityList")
        self._list.setAlternatingRowColors(True)
        self._list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection
        )
        self._list.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._list.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._list.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        layout.addWidget(self._list)

    # ── Public API ─────────────────────────────────────────────────────────────

    def add_event(self, category: str, message: str, timestamp: str) -> None:
        """Append an activity event with a category-specific icon.

        Args:
            category: One of ``download``, ``check``, ``error``, ``skip``,
                ``search``, ``activity``, ``info``.
            message: Event description text.
            timestamp: Human-readable time string (e.g. ``"14:32"``).
        """
        factory = _CATEGORY_ICON_FACTORIES.get(category, Icons.activity)
        icon = factory()

        item = QtWidgets.QListWidgetItem(self._list)
        widget = _ActivityItemWidget(icon, message, timestamp)
        item.setSizeHint(widget.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, widget)

        # Enforce max items
        while self._list.count() > self._max_items:
            old_item = self._list.takeItem(0)
            self._list.removeItemWidget(old_item)

        # Auto-scroll to latest
        self._list.scrollToBottom()

    def clear(self) -> None:
        """Remove all events."""
        self._list.clear()

    def count(self) -> int:
        """Return the current number of events."""
        return self._list.count()


