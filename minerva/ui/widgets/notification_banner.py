"""
Notification banner — styled QFrame replacement for QToolTip.showText().

Replaces the transient tooltip approach in ``minerva.ui.notifications`` with a
proper widget that slides in from the top of the parent, supports multiple
stacked banners, auto-dismiss timers, and distinct styling per severity level.

Usage::

    from minerva.ui.widgets.notification_banner import NotificationBanner

    NotificationBanner.show_info(parent, "Search complete", "Found 42 results")
    NotificationBanner.show_success(parent, "Download done")
    NotificationBanner.show_warning(parent, "Disk space low", duration=8000)
    NotificationBanner.show_error(parent, "Connection failed",
                                   "Check your network", duration=0)
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.ui.icons import Icons
from minerva.ui.theme import ThemeTokens
from minerva.ui.density import Density

_NOTIFICATION_COLORS: dict[str, tuple[str, str]] = {
    "info": ("#2f5f9e", "#1a2f50"),
    "success": ("#66c38a", "#1a3a25"),
    "warning": ("#f0b75c", "#3a2e15"),
    "error": ("#ef7777", "#3a1a1a"),
}


class NotificationBanner(QtWidgets.QFrame):
    """Styled notification banner with icon, title, body, and close button.

    Types are driven by the ``kind`` parameter and map to distinct icon/colour
    combinations.  Banners auto-dismiss after ``duration`` ms (0 = no dismiss).
    Multiple banners on the same parent stack vertically.

    Signals:
        dismissed: emitted when the banner is closed (manually or by timer).
    """

    dismissed = QtCore.pyqtSignal()

    # ── Stack tracking ──────────────────────────────────────────────────────────
    _STACK: dict[int, list[NotificationBanner]] = {}

    # ── Classmethod conveniences ────────────────────────────────────────────────

    @classmethod
    def show_info(
        cls,
        parent: QtWidgets.QWidget,
        title: str,
        body: str = "",
        duration: int = 5000,
    ) -> NotificationBanner:
        """Show an informational banner."""
        return cls._create(parent, "info", title, body, duration)

    @classmethod
    def show_success(
        cls,
        parent: QtWidgets.QWidget,
        title: str,
        body: str = "",
        duration: int = 5000,
    ) -> NotificationBanner:
        """Show a success banner."""
        return cls._create(parent, "success", title, body, duration)

    @classmethod
    def show_warning(
        cls,
        parent: QtWidgets.QWidget,
        title: str,
        body: str = "",
        duration: int = 8000,
    ) -> NotificationBanner:
        """Show a warning banner."""
        return cls._create(parent, "warning", title, body, duration)

    @classmethod
    def show_error(
        cls,
        parent: QtWidgets.QWidget,
        title: str,
        body: str = "",
        duration: int = 0,
    ) -> NotificationBanner:
        """Show an error banner (no auto-dismiss by default)."""
        return cls._create(parent, "error", title, body, duration)

    @classmethod
    def _create(
        cls,
        parent: QtWidgets.QWidget,
        kind: str,
        title: str,
        body: str,
        duration: int,
    ) -> NotificationBanner:
        banner = cls(parent, kind, title, body, duration)
        banner.show()
        return banner

    # ── Instance ────────────────────────────────────────────────────────────────

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        kind: str = "info",
        title: str = "",
        body: str = "",
        duration: int = 5000,
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMPACT,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._density = density
        self._kind = kind
        self._duration = duration

        self.setObjectName(f"notificationBanner_{kind}")
        self._apply_background()
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        # ── Layout ─────────────────────────────────────────────────────────────
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)

        # Icon
        self._icon_label = QtWidgets.QLabel()
        self._icon_label.setFixedSize(20, 20)
        self._icon_label.setPixmap(self._icon_for_kind().pixmap(20, 20))
        row.addWidget(self._icon_label)

        # Text block
        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(2)

        self._title_label = QtWidgets.QLabel(title)
        self._title_label.setObjectName("notificationTitle")
        text_col.addWidget(self._title_label)

        if body:
            self._body_label = QtWidgets.QLabel(body)
            self._body_label.setObjectName("notificationBody")
            self._body_label.setWordWrap(True)
            text_col.addWidget(self._body_label)

        row.addLayout(text_col, 1)

        # Close button
        self._close_btn = QtWidgets.QPushButton()
        self._close_btn.setObjectName("notificationClose")
        self._close_btn.setIcon(Icons.error())  # reuse error icon as X
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setFlat(True)
        self._close_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self._on_close)
        row.addWidget(self._close_btn)

        # ── Auto-dismiss timer ─────────────────────────────────────────────────
        if duration > 0:
            self._timer = QtCore.QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self._on_close)
            self._timer.start(duration)

        # ── Slide-in animation ─────────────────────────────────────────────────
        self._slide_anim = QtCore.QPropertyAnimation(self, b"pos")
        self._slide_anim.setDuration(200)
        self._slide_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        # ── Fade-out animation ─────────────────────────────────────────────────
        self._fade_anim = QtCore.QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(250)
        self._fade_anim.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._on_fade_done)

    # ── Helpers ─────────────────────────────────────────────────────────────────

    def _icon_for_kind(self) -> QtGui.QIcon:
        kind_map = {
            "info": Icons.search,
            "success": Icons.check,
            "warning": Icons.skip,
            "error": Icons.error,
        }
        return kind_map.get(self._kind, Icons.search)()

    def _apply_background(self) -> None:
        """Set the banner background from the notification colour map."""
        fg, bg = _NOTIFICATION_COLORS.get(self._kind, ("#2f5f9e", "#1a2f50"))
        self.setStyleSheet(
            f"NotificationBanner {{ background: {bg}; border: 1px solid {fg};"
            f" border-radius: 6px; }}"
        )

    def _reposition(self) -> None:
        """Slide the banner in from above the parent's top edge."""
        parent = self.parent()
        if parent is None:
            return

        parent_id = id(parent)
        stack = NotificationBanner._STACK.setdefault(parent_id, [])
        if self not in stack:
            stack.append(self)

        index = stack.index(self)
        self.adjustSize()
        banner_height = self.height()
        gap = 8

        start_x = 12
        start_y = -banner_height - (index * (banner_height + gap))
        end_y = 12 + (index * (banner_height + gap))

        self.move(start_x, start_y)
        self.resize(parent.width() - 24, self.height())

        self._slide_anim.setStartValue(QtCore.QPoint(start_x, start_y))
        self._slide_anim.setEndValue(QtCore.QPoint(start_x, end_y))
        self._slide_anim.start()

    def _on_close(self) -> None:
        """Start the fade-out, then remove from stack."""
        if self._fade_anim.state() == QtCore.QAbstractAnimation.State.Running:
            return
        self._slide_anim.stop()
        if hasattr(self, "_timer") and self._timer.isActive():
            self._timer.stop()
        self._fade_anim.start()

    def _on_fade_done(self) -> None:
        """Remove banner from stack and hide."""
        parent_id = id(self.parent())
        stack = NotificationBanner._STACK.get(parent_id, [])
        if self in stack:
            stack.remove(self)
        self.hide()
        self.dismissed.emit()
        # Reposition remaining banners in the stack
        for banner in stack:
            banner._reposition()

    def show(self, text: str | None = None) -> None:
        """Show the banner and start the slide-in animation."""
        if text is not None:
            self._title_label.setText(text)
        super().show()
        self.raise_()
        self._reposition()

    def hide(self) -> None:
        """Immediately hide and clean up."""
        parent_id = id(self.parent())
        stack = NotificationBanner._STACK.get(parent_id, [])
        if self in stack:
            stack.remove(self)
        if hasattr(self, "_timer") and self._timer.isActive():
            self._timer.stop()
        self._slide_anim.stop()
        self._fade_anim.stop()
        super().hide()

    # ── Protocol methods ───────────────────────────────────────────────────────

    def apply_tokens(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens

    def apply_density(self, density: Density) -> None:
        self._density = density
