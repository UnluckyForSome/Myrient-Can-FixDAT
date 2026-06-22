"""Rolling download/upload throughput chart used by the Downloads dashboard."""

from __future__ import annotations

import time
from collections import deque

import pyqtgraph as pg
from PyQt6 import QtWidgets

from minerva.ui.theme import ThemeTokens

_WINDOW_SECS = 600
_MAX_POINTS = 600


class SpeedChart(QtWidgets.QFrame):
    """Ten-minute throughput chart with live current and peak values."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("throughputPanel")
        self._tokens = ThemeTokens()
        self._timestamps: deque[float] = deque(maxlen=_MAX_POINTS)
        self._download: deque[float] = deque(maxlen=_MAX_POINTS)
        self._upload: deque[float] = deque(maxlen=_MAX_POINTS)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Download speed")
        title.setObjectName("panelTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._current = QtWidgets.QLabel("Current  0 B/s")
        self._current.setObjectName("chartCurrent")
        header.addWidget(self._current)
        self._peak = QtWidgets.QLabel("Peak  0 B/s")
        self._peak.setObjectName("chartPeak")
        header.addWidget(self._peak)
        root.addLayout(header)

        self._plot = pg.PlotWidget(background=self._tokens.surface)
        self._plot.setMinimumHeight(190)
        self._plot.setLabel("left", "MB/s")
        self._plot.getAxis("bottom").setTicks([])
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.showGrid(x=True, y=True, alpha=0.12)
        self._plot.setXRange(-_WINDOW_SECS, 0)
        self._plot.enableAutoRange(axis="x", enable=False)
        self._plot.enableAutoRange(axis="y")
        self._download_curve = self._plot.plot(
            pen=pg.mkPen(self._tokens.accent, width=2)
        )
        self._upload_curve = self._plot.plot(
            pen=pg.mkPen(self._tokens.success, width=1.2)
        )
        root.addWidget(self._plot)

    @staticmethod
    def _format_speed(value: float) -> str:
        units = ["B/s", "KB/s", "MB/s", "GB/s"]
        value = max(0.0, float(value))
        index = 0
        while value >= 1024 and index < len(units) - 1:
            value /= 1024
            index += 1
        return f"{value:.1f} {units[index]}" if index else f"{int(value)} {units[index]}"

    def add_data_point(self, download_speed: float, upload_speed: float = 0.0) -> None:
        self._timestamps.append(time.monotonic())
        self._download.append(download_speed / (1024 * 1024))
        self._upload.append(upload_speed / (1024 * 1024))
        self._current.setText(f"Current  {self._format_speed(download_speed)}")
        peak = max(self._download, default=0.0) * 1024 * 1024
        self._peak.setText(f"Peak  {self._format_speed(peak)}")
        self._redraw()

    def clear(self) -> None:
        self._timestamps.clear()
        self._download.clear()
        self._upload.clear()
        self._download_curve.clear()
        self._upload_curve.clear()
        self._current.setText("Current  0 B/s")
        self._peak.setText("Peak  0 B/s")

    def _redraw(self) -> None:
        if not self._timestamps:
            return
        now = time.monotonic()
        x = [stamp - now for stamp in self._timestamps]
        self._download_curve.setData(x, list(self._download))
        self._upload_curve.setData(x, list(self._upload))

    def apply_tokens(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens
        self._plot.setBackground(tokens.surface)
        self._download_curve.setPen(pg.mkPen(tokens.accent, width=2))
        self._upload_curve.setPen(pg.mkPen(tokens.success, width=1.2))
