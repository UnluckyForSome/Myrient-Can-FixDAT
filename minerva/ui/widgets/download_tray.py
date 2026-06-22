"""DownloadTray — persistent collapsible widget at the bottom of the shell.

Collapsed state shows a summary bar with download count, aggregate speed,
and a qBittorrent connection-status dot. Expanded state reveals per-file
progress via an embedded content widget (DownloadTrayContent).
"""

from __future__ import annotations

import logging

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.app.app_state import AppState
from minerva.ui.icons import Icons
from minerva.ui.theme import ThemeTokens

log = logging.getLogger(__name__)


def _format_speed(bytes_per_sec: int) -> str:
    """Format a byte-per-second value as a human-readable speed string."""
    if bytes_per_sec <= 0:
        return "0 B/s"
    units = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"]
    value = float(bytes_per_sec)
    for unit in units:
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB/s"


class DownloadTray(QtWidgets.QWidget):
    """Collapsible download tray — collapsed bar + expanded content.

    Parameters
    ----------
    app_state : AppState
        Signal bus — ``queue_changed`` triggers auto-expand,
        ``qbit_state_changed`` updates the dot colour.
    """

    collapsed_height = 32
    expanded_height = 240
    auto_expand_ms = 3000

    def __init__(
        self,
        app_state: AppState,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._expanded = False
        self._qbit_connected: bool | None = None
        self._prev_qbit_connected: bool | None = None
        self._content_widget: QtWidgets.QWidget | None = None
        self._auto_timer = QtCore.QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self.collapse)

        self.setObjectName("downloadTray")
        self.setFixedHeight(self.collapsed_height)

        # ── Layout ─────────────────────────────────────────────────────
        self._root = QtWidgets.QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)

        # ── Collapsed bar ──────────────────────────────────────────────
        self._bar = QtWidgets.QWidget()
        self._bar.setObjectName("trayBar")
        self._bar.setFixedHeight(self.collapsed_height)
        bar_layout = QtWidgets.QHBoxLayout(self._bar)
        bar_layout.setContentsMargins(12, 0, 12, 0)
        bar_layout.setSpacing(8)

        # Connection status dot
        self._dot = QtWidgets.QLabel("●")
        self._dot.setObjectName("qbitDot")
        self._dot.setFixedWidth(16)
        self._update_dot_style()
        bar_layout.addWidget(self._dot)

        self._count_label = QtWidgets.QLabel("No downloads")
        self._count_label.setObjectName("trayCount")
        bar_layout.addWidget(self._count_label, 1)

        # Aggregate speed label
        self._speed_label = QtWidgets.QLabel("")
        self._speed_label.setObjectName("traySpeed")
        bar_layout.addWidget(self._speed_label)

        self._toggle_btn = QtWidgets.QPushButton("▲")
        self._toggle_btn.setObjectName("trayToggleBtn")
        self._toggle_btn.setFixedSize(24, 24)
        self._toggle_btn.setFlat(True)
        self._toggle_btn.clicked.connect(self.toggle)
        bar_layout.addWidget(self._toggle_btn)

        self._root.addWidget(self._bar)

        # ── Expanded content area ──────────────────────────────────────
        self._content_area = QtWidgets.QWidget()
        self._content_area.setObjectName("trayContent")
        self._content_layout = QtWidgets.QVBoxLayout(self._content_area)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_area.setVisible(False)
        self._root.addWidget(self._content_area)

        # ── Signal wiring ──────────────────────────────────────────────
        self._app_state.queue_changed.connect(self._on_queue_changed)
        self._app_state.qbit_state_changed.connect(self._on_qbit_state_changed)
        if hasattr(self._app_state, "runtime_changed"):
            self._app_state.runtime_changed.connect(self._on_runtime_changed)
        if hasattr(self._app_state, "activity_event"):
            self._app_state.activity_event.connect(self._on_activity_event)

        # Initial qbit state
        self._qbit_connected = bool(self._app_state.qbit_state) if self._app_state.qbit_state is not None else None
        self._prev_qbit_connected = self._qbit_connected
        self._update_dot_style()

    # ── Public API ──────────────────────────────────────────────────────

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    @property
    def qbit_connected(self) -> bool:
        return self._qbit_connected

    @property
    def content_widget(self) -> QtWidgets.QWidget | None:
        return self._content_widget

    def expand(self) -> None:
        """Expand the tray to show download progress."""
        self._expanded = True
        self._auto_timer.stop()
        self.setFixedHeight(self.expanded_height)
        self._content_area.setVisible(True)
        self._toggle_btn.setText("▼")
        self._apply_bar_style()

    def collapse(self) -> None:
        """Collapse the tray to just the summary bar."""
        self._expanded = False
        self._auto_timer.stop()
        self.setFixedHeight(self.collapsed_height)
        self._content_area.setVisible(False)
        self._toggle_btn.setText("▲")
        self._apply_bar_style()

    def toggle(self) -> None:
        """Toggle between expanded and collapsed states."""
        if self._expanded:
            self.collapse()
        else:
            self.expand()

    def auto_expand(self) -> None:
        """Expand the tray and start auto-collapse timer."""
        self.expand()
        self._auto_timer.start(self.auto_expand_ms)

    def set_content(self, widget: QtWidgets.QWidget) -> None:
        """Set the widget displayed in the expanded content area."""
        if self._content_widget is not None:
            self._content_layout.removeWidget(self._content_widget)
        self._content_widget = widget
        self._content_layout.addWidget(widget)

    # ── Signal handlers ─────────────────────────────────────────────────

    def _on_queue_changed(self) -> None:
        """Auto-expand when new items are queued."""
        self.auto_expand()

    def _on_qbit_state_changed(self, state: object) -> None:
        """Update the connection dot when qbit state changes. Show toast on disconnect."""
        self._prev_qbit_connected = self._qbit_connected
        if state is None:
            self._qbit_connected = None
        else:
            self._qbit_connected = bool(state)
        self._update_dot_style()

        # WARNING-7: Show toast on disconnect transition
        if self._prev_qbit_connected is True and self._qbit_connected is not True:
            from minerva.ui.widgets.notification_banner import NotificationBanner
            NotificationBanner.show_warning(
                self, "qBittorrent connection lost",
                "Check your qBittorrent settings or network connection.",
                duration=8000,
            )

    def _on_runtime_changed(self, runtimes: list) -> None:
        """Update aggregate speed label from runtime telemetry."""
        total_speed = 0
        for rt in runtimes:
            total_speed += getattr(rt, "download_speed", 0)
        self._speed_label.setText(_format_speed(total_speed))

    def _on_activity_event(self, event_type: str, detail: str) -> None:
        """Handle activity events from the download controller."""
        if event_type == "check":
            # WARNING-6: Download complete toast
            from minerva.ui.widgets.notification_banner import NotificationBanner
            NotificationBanner.show_success(
                self, "Download complete", f"✓ {detail}",
                duration=5000,
            )

    # ── Styling ─────────────────────────────────────────────────────────

    def _update_dot_style(self) -> None:
        if self._qbit_connected is None:
            color = "#888888"  # gray = unknown
        elif self._qbit_connected:
            color = "#66c38a"  # green = connected
        else:
            color = "#ef7777"  # red = disconnected
        self._dot.setStyleSheet(
            f"color: {color}; font-size: 14px; border: none;"
        )

    def _apply_bar_style(self) -> None:
        self._bar.setStyleSheet(
            "QWidget#trayBar { background-color: #1a1d23; border-top: 1px solid #2a2d33; }"
        )
        self._count_label.setStyleSheet(
            "color: #e8eaf0; font-size: 12px; border: none;"
        )
