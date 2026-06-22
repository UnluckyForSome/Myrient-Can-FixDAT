"""
Display, size, checkbox, progress-bar, and action-button delegates.

*   ``DisplayDelegate`` — ``QStyledItemDelegate`` that renders ``displayText``
    via ``str()``.
*   ``SizeDelegate`` — formats integer byte values as human-readable binary
    sizes (B / KB / MB / GB / TB / PB).  Negative values display as ``-``.
    Matches legacy ``format_bytes`` in ``minerva_gui.py:3884`` (Decision 10).
*   ``CheckboxDelegate`` — click-to-toggle checkbox column.  ``editorEvent``
    detects ``MouseButtonRelease`` inside the indicator rect and commits the
    new ``CheckState`` via ``model.setData()`` + ``commitData.emit()``
    (Decision 9).
*   ``ProgressDelegate`` — paints a native progress bar from a 0.0–1.0 float
    stored in ``UserRole`` (Decision 3).
*   ``ActionDelegate`` — draws unicode action buttons (▶/⏸/✕) per download
    status, emits ``action_triggered(index, action)`` on click (Decision 4).
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QApplication, QStyle, QStyledItemDelegate


class DisplayDelegate(QStyledItemDelegate):
    """Simple display delegate — converts values via ``str()``.

    Apply as the default delegate for the entire view, or per-column::

        view.setItemDelegate(DisplayDelegate(view))
    """

    def displayText(self, value: object, locale: QtCore.QLocale) -> str:
        """Return ``str(value)`` (format_fn dispatch is handled by model)."""
        return str(value)


class SizeDelegate(DisplayDelegate):
    """Formats integer byte values as binary (1024-based) size strings.

    Examples
    --------
    * ``displayText(0, locale)`` → ``"0 B"``
    * ``displayText(1024, locale)`` → ``"1.0 KB"``
    * ``displayText(-1, locale)`` → ``"-"``
    """

    _UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]

    def displayText(self, value: object, locale: QtCore.QLocale) -> str:
        """Format byte count as a human-readable binary size string."""
        # Accept both int and str values (str from model format_fn, int raw)
        if isinstance(value, str):
            try:
                value = int(value)
            except ValueError:
                return value

        if not isinstance(value, int):
            return str(value)

        if value < 0:
            return "-"

        v = float(value)
        unit_idx = 0
        while v >= 1024 and unit_idx < len(self._UNITS) - 1:
            v /= 1024.0
            unit_idx += 1

        if unit_idx == 0:
            return f"{int(v)} {self._UNITS[unit_idx]}"
        return f"{v:.1f} {self._UNITS[unit_idx]}"


class CheckboxDelegate(QStyledItemDelegate):
    """Click-to-toggle checkbox delegate.

    Usage
    -----
    Apply per-column::

        view.setItemDelegateForColumn(5, CheckboxDelegate(view))

    The column must return ``Qt.CheckState.Unchecked`` or
    ``Qt.CheckState.Checked`` from ``data(index, CheckStateRole)``
    and include ``ItemFlag.ItemIsUserCheckable`` in its flags so
    the view paints the checkbox indicator.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Dummy editor widget for commitData emission
        self._dummy_editor = QtWidgets.QWidget()

    def editorEvent(
        self,
        event: QtCore.QEvent,
        model: QtCore.QAbstractItemModel,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> bool:
        """Handle mouse clicks on the checkbox indicator.

        Returns ``True`` if the event was consumed (checkbox toggled).
        """
        if event.type() != QEvent.Type.MouseButtonRelease:
            return super().editorEvent(event, model, option, index)

        # Determine checkbox indicator rect
        style = option.widget.style() if option.widget else QApplication.style()
        check_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator,
            option,
            option.widget,
        )

        mouse_pos = event.position().toPoint()
        if not check_rect.contains(mouse_pos):
            return super().editorEvent(event, model, option, index)

        # Toggle checkbox state
        current = model.data(index, Qt.ItemDataRole.CheckStateRole)
        new_state = (
            Qt.CheckState.Unchecked
            if current == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )
        model.setData(index, new_state, Qt.ItemDataRole.CheckStateRole)
        self.commitData.emit(self._dummy_editor)
        return True


# ── ProgressDelegate ───────────────────────────────────────────────────────────


class ProgressDelegate(QStyledItemDelegate):
    """Draws a native progress bar from a 0.0–1.0 float in ``UserRole``.

    Usage::

        view.setItemDelegateForColumn(2, ProgressDelegate(view))

    The source model column must return a ``float`` in ``[0.0, 1.0]``
    from ``data(index, UserRole)``.
    """

    _BAR_HEIGHT = 24

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        """Paint a ``QStyleOptionProgressBar`` using the value from
        ``index.data(UserRole)``."""
        progress = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(progress, (int, float)):
            progress = 0.0

        # Clamp to 0..1
        progress = max(0.0, min(1.0, float(progress)))

        # Build progress-bar option
        opt = QtWidgets.QStyleOptionProgressBar()
        opt.rect = option.rect
        opt.minimum = 0
        opt.maximum = 100
        opt.progress = int(progress * 100)
        opt.textVisible = True
        opt.text = f"{int(progress * 100)}%"

        # Draw the bar using the application style
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ProgressBar, opt, painter, option.widget)

    def sizeHint(
        self,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> QtCore.QSize:
        """Return a fixed bar height for consistent row sizing."""
        return QtCore.QSize(100, self._BAR_HEIGHT)


# ── ActionDelegate ─────────────────────────────────────────────────────────────


class ActionDelegate(QStyledItemDelegate):
    """Draws unicode action buttons (▶/⏸/✕) per download status.

    Emits ``action_triggered(index, action)`` when a button region is
    clicked.

    Usage::

        delegate = ActionDelegate(view)
        delegate.action_triggered.connect(self._on_action)
        view.setItemDelegateForColumn(5, delegate)
    """

    action_triggered = QtCore.pyqtSignal(QtCore.QModelIndex, str)

    _BUTTON_WIDTH = 28

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        """Draw action buttons based on the download status.

        Button layout (3 equal rects in the cell):
            QUEUED / PAUSED   →  [▶]  [—]  [✕]
            DOWNLOADING       →  [—]  [⏸]  [✕]
            COMPLETED/FAILED/CANCELLED → [—]  [—]  [✕]
        """
        from minerva.domain.downloads import DownloadStatus

        status = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(status, DownloadStatus):
            status = DownloadStatus.QUEUED

        # Determine which button labels to show
        if status in (DownloadStatus.QUEUED, DownloadStatus.PAUSED):
            labels = ["\u25b6", "", "\u2715"]  # ▶  , (blank), ✕
        elif status == DownloadStatus.DOWNLOADING:
            labels = ["", "\u23f8", "\u2715"]  # (blank), ⏸, ✕
        else:
            # COMPLETED, FAILED, CANCELLED
            labels = ["", "", "\u2715"]  # (blank), (blank), ✕

        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        cell_rect = option.rect
        btn_w = self._BUTTON_WIDTH
        spacing = 4
        start_x = cell_rect.x() + spacing
        y = cell_rect.y()
        h = cell_rect.height()

        font = painter.font()
        font.setPointSize(11)
        painter.setFont(font)
        painter.setPen(option.palette.buttonText().color())

        for i, label in enumerate(labels):
            if not label:
                continue
            x = start_x + i * (btn_w + spacing)
            btn_rect = QtCore.QRect(x, y, btn_w, h)
            # Draw a subtle button background
            painter.fillRect(btn_rect, option.palette.button())
            # Draw the character centered
            painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, label)

        painter.restore()

    def editorEvent(
        self,
        event: QtCore.QEvent,
        model: QtCore.QAbstractItemModel,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> bool:
        """Handle mouse clicks — map the click position to a button and
        emit ``action_triggered``."""
        from minerva.domain.downloads import DownloadStatus

        if event.type() != QEvent.Type.MouseButtonRelease:
            return super().editorEvent(event, model, option, index)

        status = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(status, DownloadStatus):
            return super().editorEvent(event, model, option, index)

        mouse_pos = event.position().toPoint()
        cell_rect = option.rect
        btn_w = self._BUTTON_WIDTH
        spacing = 4
        start_x = cell_rect.x() + spacing

        # Determine which buttons are visible
        if status in (DownloadStatus.QUEUED, DownloadStatus.PAUSED):
            buttons: list[tuple[str, str]] = [
                ("resume", "\u25b6"),
                ("", ""),
                ("remove", "\u2715"),
            ]
        elif status == DownloadStatus.DOWNLOADING:
            buttons = [
                ("", ""),
                ("pause", "\u23f8"),
                ("remove", "\u2715"),
            ]
        else:
            buttons = [
                ("", ""),
                ("", ""),
                ("remove", "\u2715"),
            ]

        for i, (action, _label) in enumerate(buttons):
            if not action:
                continue
            x = start_x + i * (btn_w + spacing)
            btn_rect = QtCore.QRect(x, cell_rect.y(), btn_w, cell_rect.height())
            if btn_rect.contains(mouse_pos):
                self.action_triggered.emit(index, action)
                return True

        return super().editorEvent(event, model, option, index)

    def sizeHint(
        self,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> QtCore.QSize:
        """Return a fixed width for the action column."""
        return QtCore.QSize(100, 24)


class TagPillDelegate(QStyledItemDelegate):
    """Paint a compact set of tag pills from an iterable in ``UserRole``."""

    def paint(self, painter, option, index) -> None:
        values = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(values, (tuple, list, set)):
            return super().paint(painter, option, index)

        painter.save()
        base = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(base, index)
        base.text = ""
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, base, painter, option.widget)

        x = option.rect.left() + 7
        y = option.rect.center().y() - 10
        available = option.rect.right() - 7
        font = painter.font()
        font.setPointSize(max(8, font.pointSize() - 1))
        painter.setFont(font)
        palette = option.palette

        shown = 0
        items = [str(value).title() for value in values if value]
        for text in items:
            width = painter.fontMetrics().horizontalAdvance(text) + 16
            if x + width > available:
                break
            rect = QtCore.QRect(x, y, width, 20)
            painter.setPen(palette.mid().color())
            painter.setBrush(palette.alternateBase())
            painter.drawRoundedRect(rect, 9, 9)
            painter.setPen(palette.text().color())
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            x += width + 5
            shown += 1

        remaining = len(items) - shown
        if remaining > 0 and x < available:
            text = f"+{remaining}"
            width = painter.fontMetrics().horizontalAdvance(text) + 12
            rect = QtCore.QRect(x, y, min(width, max(0, available - x)), 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.button())
            painter.drawRoundedRect(rect, 9, 9)
            painter.setPen(palette.placeholderText().color())
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option, index):
        return QtCore.QSize(180, 40)
