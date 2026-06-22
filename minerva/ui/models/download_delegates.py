"""Delegates used by the reference-quality Downloads dashboard."""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.domain.downloads import DownloadStatus
from minerva.ui.theme import ThemeTokens


class DownloadStatusDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = ThemeTokens()

    def paint(self, painter, option, index) -> None:
        style = option.widget.style() if option.widget else QtWidgets.QApplication.style()
        style.drawPrimitive(
            QtWidgets.QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )
        status = index.data(QtCore.Qt.ItemDataRole.UserRole)
        if not isinstance(status, DownloadStatus):
            status = DownloadStatus.QUEUED
        text, fg, bg = self._style(status)
        painter.save()
        font = QtGui.QFont(option.font)
        font.setBold(True)
        font.setPointSize(max(8, option.font.pointSize() - 1))
        painter.setFont(font)
        fm = QtGui.QFontMetrics(font)
        width = min(option.rect.width() - 12, fm.horizontalAdvance(text) + 22)
        rect = QtCore.QRect(
            option.rect.left() + 8,
            option.rect.center().y() - 11,
            width,
            22,
        )
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(bg))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QtGui.QColor(fg))
        painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def _style(self, status: DownloadStatus) -> tuple[str, str, str]:
        t = self._tokens
        return {
            DownloadStatus.QUEUED: ("Queued", t.warning, t.warning_surface),
            DownloadStatus.STARTING: ("Starting", t.accent, t.info_surface),
            DownloadStatus.DOWNLOADING: ("Downloading", t.accent, t.info_surface),
            DownloadStatus.PAUSED: ("Paused", t.text_muted, t.surface_raised),
            DownloadStatus.SEEDING: ("Seeding", t.success, t.success_surface),
            DownloadStatus.COMPLETED: ("Completed", t.purple, t.purple_surface),
            DownloadStatus.FAILED: ("Failed", t.error, t.error_surface),
            DownloadStatus.CANCELLED: ("Cancelled", t.text_muted, t.surface_raised),
        }[status]


class DownloadProgressDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, tokens: ThemeTokens = ThemeTokens(), parent=None) -> None:
        super().__init__(parent)
        self._tokens = tokens

    def paint(self, painter, option, index) -> None:
        style = option.widget.style() if option.widget else QtWidgets.QApplication.style()
        style.drawPrimitive(
            QtWidgets.QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )
        value = index.data(QtCore.Qt.ItemDataRole.UserRole)
        value = max(0.0, min(1.0, float(value or 0.0)))
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        text_rect = option.rect.adjusted(8, 2, -8, -18)
        painter.setPen(option.palette.text().color())
        painter.drawText(
            text_rect,
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            f"{value:.0%}",
        )
        track = QtCore.QRectF(
            option.rect.left() + 8,
            option.rect.bottom() - 13,
            option.rect.width() - 16,
            5,
        )
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(self._tokens.surface_raised))
        painter.drawRoundedRect(track, 2.5, 2.5)
        fill = QtCore.QRectF(track.left(), track.top(), track.width() * value, track.height())
        painter.setBrush(
            QtGui.QColor(self._tokens.success if value >= 1.0 else self._tokens.accent)
        )
        painter.drawRoundedRect(fill, 2.5, 2.5)
        painter.restore()
