"""
Generic thread-lifecycle manager for AppShell.

Manages the ``_filter_load_thread`` (``threading.Thread``) used during
library index loading.  Also owns the in-process download queue used
by tests and when no DownloadController is wired.
"""

from __future__ import annotations

import logging
import threading

from PyQt6 import QtCore

log = logging.getLogger(__name__)


class WorkerManager(QtCore.QObject):
    """Manages the filter-load thread lifecycle and download queue."""

    downloads_changed = QtCore.pyqtSignal()

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.filter_load_thread: threading.Thread | None = None
        # ponytail: download_worker holds a QThread-like worker (e.g. a
        # DownloadWorker) whose lifecycle outlives individual page swaps.
        # None when no worker has been attached.
        self.download_worker: QtCore.QThread | None = None
        self._downloads: list = []
        self._active: set[int] = set()
        self._next_id = 1

    def is_active(self) -> bool:
        if (
            self.filter_load_thread is not None
            and self.filter_load_thread.is_alive()
        ):
            return True
        if self.download_worker is not None and self.download_worker.isRunning():
            return True
        return False

    def prepare_shutdown(self, timeout_ms: int = 2500) -> bool:
        if (
            self.filter_load_thread is not None
            and self.filter_load_thread.is_alive()
        ):
            self.filter_load_thread.join(timeout=timeout_ms / 1000)
        if self.download_worker is not None and self.download_worker.isRunning():
            self.download_worker.stop()
        return not self.is_active()

    # ── Download queue ──────────────────────────────────────────────────

    def add_to_queue(self, filename: str, url: str) -> int:
        from minerva.ui.models.download_model import DownloadRecord
        from minerva.domain.downloads import DownloadStatus

        record = DownloadRecord(
            id=self._next_id,
            queue_id=str(self._next_id),
            filename=filename,
            url=url,
            status=DownloadStatus.QUEUED,
        )
        self._next_id += 1
        self._downloads.append(record)
        self._active.add(record.id)
        self._emit_downloads_changed()
        return record.id

    def cancel(self, index: int) -> None:
        from minerva.domain.downloads import DownloadStatus

        if 0 <= index < len(self._downloads):
            self._downloads[index].status = DownloadStatus.CANCELLED
            self._active.discard(self._downloads[index].id)
            self._emit_downloads_changed()

    def pause(self, download_id: int) -> None:
        from minerva.domain.downloads import DownloadStatus

        for d in self._downloads:
            if d.id == download_id:
                d.status = DownloadStatus.PAUSED
                break
        self._emit_downloads_changed()

    def resume(self, download_id: int) -> None:
        from minerva.domain.downloads import DownloadStatus

        for d in self._downloads:
            if d.id == download_id:
                d.status = DownloadStatus.DOWNLOADING
                break
        self._emit_downloads_changed()

    def remove(self, download_id: int) -> None:
        from minerva.domain.downloads import DownloadStatus

        for d in self._downloads:
            if d.id == download_id:
                d.status = DownloadStatus.CANCELLED
                break
        self._active.discard(download_id)
        self._emit_downloads_changed()

    def _emit_downloads_changed(self) -> None:
        self.downloads_changed.emit()
