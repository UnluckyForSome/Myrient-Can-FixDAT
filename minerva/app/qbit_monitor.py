"""Thread-affine qBittorrent polling worker."""

from __future__ import annotations

import logging
from collections.abc import Collection

from PyQt6 import QtCore

from minerva.domain.downloads import TorrentFileInfo, TorrentInfo
from minerva_qbit import QBittorrentClient, QBittorrentError

log = logging.getLogger(__name__)


class QbitMonitor(QtCore.QObject):
    """Poll all tracked torrent hashes in one qBittorrent API request."""

    snapshot_ready = QtCore.pyqtSignal(list)  # list[TorrentInfo]
    connection_changed = QtCore.pyqtSignal(object)  # bool
    error = QtCore.pyqtSignal(str)
    stopped = QtCore.pyqtSignal()

    _DEFAULT_INTERVAL_MS = 1000

    def __init__(
        self,
        client: QBittorrentClient,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._tracked_hashes: set[str] = set()
        self._connected = False
        self._timer: QtCore.QTimer | None = None

    @QtCore.pyqtSlot(object)
    def set_tracked_hashes(self, hashes: Collection[str]) -> None:
        self._tracked_hashes = {h for h in hashes if h}
        log.debug("Tracking %d torrent hash(es)", len(self._tracked_hashes))

    @QtCore.pyqtSlot()
    def start(self) -> None:
        """Create and start the timer in the worker's owning thread."""
        if self._timer is None:
            self._timer = QtCore.QTimer(self)
            self._timer.setInterval(self._DEFAULT_INTERVAL_MS)
            self._timer.timeout.connect(self._poll)
        if not self._timer.isActive():
            self._timer.start()
            log.info("QbitMonitor started (interval=%dms)", self._timer.interval())

    @QtCore.pyqtSlot()
    def stop(self) -> None:
        if self._timer is not None and self._timer.isActive():
            self._timer.stop()
        self.stopped.emit()
        log.info("QbitMonitor stopped")

    @QtCore.pyqtSlot()
    def _poll(self) -> None:
        if not self._tracked_hashes:
            return

        try:
            if not self._client.is_logged_in:
                self._client.login()
            raw_items = self._client.list_torrents(sorted(self._tracked_hashes))
        except QBittorrentError as exc:
            self._set_connected(False)
            self.error.emit(str(exc))
            return

        self._set_connected(True)
        results: list[TorrentInfo] = []
        for raw in raw_items:
            torrent_hash = raw.get("hash", "")
            if not torrent_hash:
                continue
            try:
                raw_files = self._client.get_files(torrent_hash)
            except QBittorrentError:
                raw_files = []
            files = tuple(
                TorrentFileInfo(
                    index=int(item.get("index", -1)),
                    name=str(item.get("name", "")),
                    size=int(item.get("size", 0)),
                    progress=float(item.get("progress", 0.0)),
                    priority=int(item.get("priority", 0)),
                )
                for item in raw_files
                if int(item.get("index", -1)) >= 0
            )
            results.append(TorrentInfo(
                hash=torrent_hash,
                name=raw.get("name", ""),
                progress=float(raw.get("progress", 0.0)),
                state=raw.get("state", ""),
                dlspeed=int(raw.get("dlspeed", 0)),
                upspeed=int(raw.get("upspeed", 0)),
                size=int(raw.get("total_size", raw.get("size", 0))),
                completed=int(raw.get("completed", 0)),
                ratio=float(raw.get("ratio", 0.0)),
                eta=int(raw.get("eta", -1)),
                save_path=raw.get("save_path", ""),
                category=raw.get("category", ""),
                seeds=int(raw.get("num_seeds", 0)),
                peers=int(raw.get("num_leechs", 0)),
                files=files,
            ))
        if results:
            self.snapshot_ready.emit(results)

    def _set_connected(self, connected: bool) -> None:
        if self._connected == connected:
            return
        self._connected = connected
        self.connection_changed.emit(connected)

    @property
    def tracked_hashes(self) -> frozenset[str]:
        return frozenset(self._tracked_hashes)

    @property
    def is_connected(self) -> bool:
        return self._connected
