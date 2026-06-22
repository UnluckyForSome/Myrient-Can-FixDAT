"""
Busy overlay — floating progress indicator over a target widget.

Replaces the earlier hourglass-emoji approach with a custom QPainter-based
spinner and an optional cancel button.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.ui.theme import ThemeTokens
from minerva.ui.density import Density


class _SpinnerWidget(QtWidgets.QWidget):
    """A small rotating arc painted with QPainter.

    Animates via a QTimer that increments the rotation angle and triggers
    a repaint every 50 ms.
    """

    def __init__(
        self,
        size: int = 32,
        colour: str = "#2f5f9e",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._angle: int = 0
        self._size = size
        self._colour = colour

        self.setFixedSize(size, size)

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._rotate)
        self._timer.setInterval(50)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def set_colour(self, colour: str) -> None:
        self._colour = colour

    # ── Animation ──────────────────────────────────────────────────────────────

    def _rotate(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    # ── Paint ──────────────────────────────────────────────────────────────────

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        pen = QtGui.QPen(QtGui.QColor(self._colour))
        pen.setWidth(3)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        margin = 4
        rect = QtCore.QRectF(margin, margin, self._size - 2 * margin,
                             self._size - 2 * margin)

        # Draw an arc that sweeps 270° and rotates each frame
        start_angle = self._angle * 16  # Qt uses 1/16 of a degree
        span_angle = 270 * 16
        painter.drawArc(rect, start_angle, span_angle)

        painter.end()


class BusyOverlay(QtWidgets.QFrame):
    """Semi-transparent overlay with a spinner and optional cancel button.

    Place it over a target widget to indicate ongoing activity::

        overlay = BusyOverlay(parent_widget, "Loading…", cancellable=True)
        overlay.cancel_requested.connect(self._on_cancel)
        overlay.show()

        # ... after work completes
        overlay.hide()

    Signals:
        cancel_requested: emitted when the user clicks the cancel button.
    """

    cancel_requested = QtCore.pyqtSignal()

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        text: str = "Loading…",
        cancellable: bool = False,
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMPACT,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._density = density

        self.setObjectName("busyBanner")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(density.card_padding, density.card_padding,
                                   density.card_padding, density.card_padding)
        layout.setSpacing(12)

        # ── Spinner ────────────────────────────────────────────────────────────
        self._spinner = _SpinnerWidget(size=32, colour=tokens.accent)
        layout.addWidget(self._spinner, 0, QtCore.Qt.AlignmentFlag.AlignCenter)

        # ── Message ────────────────────────────────────────────────────────────
        self._message_label = QtWidgets.QLabel(text)
        self._message_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._message_label.setObjectName("sectionHint")
        self._message_label.setWordWrap(True)
        layout.addWidget(self._message_label)

        # ── Cancel button ──────────────────────────────────────────────────────
        self._cancel_btn: QtWidgets.QPushButton | None = None
        if cancellable:
            self._cancel_btn = QtWidgets.QPushButton("Cancel")
            self._cancel_btn.setObjectName("subtleButton")
            self._cancel_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            self._cancel_btn.clicked.connect(self._on_cancel)
            btn_row = QtWidgets.QHBoxLayout()
            btn_row.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            btn_row.addWidget(self._cancel_btn)
            layout.addLayout(btn_row)

        self.hide()

    # ── Public API ─────────────────────────────────────────────────────────────

    def show(self, text: str | None = None) -> None:
        """Show the overlay with an optional text update."""
        if text is not None:
            self._message_label.setText(text)
        self._spinner.start()
        super().show()
        self.raise_()

    def hide(self) -> None:
        """Hide the overlay and stop the spinner."""
        self._spinner.stop()
        super().hide()

    def set_text(self, text: str) -> None:
        """Update the message text while visible."""
        self._message_label.setText(text)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _on_cancel(self) -> None:
        self.cancel_requested.emit()

    # ── Protocol methods ───────────────────────────────────────────────────────

    def apply_tokens(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens
        self._spinner.set_colour(tokens.accent)

    def apply_density(self, density: Density) -> None:
        self._density = density
        layout = self.layout()
        if layout:
            layout.setContentsMargins(
                density.card_padding, density.card_padding,
                density.card_padding, density.card_padding
            )
