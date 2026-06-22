"""
``DownloadWorker`` QThread for downloading Myrient ROM files.

Extracted from ``minerva_gui`` during the legacy cleanup (Phase 11).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from PyQt6 import QtCore

from minerva.app.legacy_data import SAVED_QUEUE_PATH


class DownloadWorker(QtCore.QThread):
    """Download files from Myrient with optional qBittorrent integration."""

    progress = QtCore.pyqtSignal(int, int, str)
    file_done = QtCore.pyqtSignal(int, int, str)
    log = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, files, output_dir: str, use_qbit: bool = False, parent=None):
        super().__init__(parent)
        self._files = files
        self._output = Path(output_dir)
        self._use_qbit = use_qbit
        self._stop = False
        self._qbit_client = None

    def stop(self):
        self._stop = True

    def run(self):
        total = len(self._files)
        success = 0

        # One-time qBittorrent login if needed
        if self._use_qbit:
            from minerva_qbit import (
                QBittorrentClient,
                QBittorrentError,
            )

            s = QtCore.QSettings("MinervaFixDAT", "MinervaGUI")
            url = s.value("qbit_url", "http://localhost:8080", str)
            user = s.value("qbit_user", "admin", str)
            pwd = s.value("qbit_pass", "adminadmin", str)
            self._qbit_client = QBittorrentClient(url, user, pwd)
            try:
                self._qbit_client.login()
            except QBittorrentError:
                self.log.emit(
                    "qBittorrent login failed — falling back to aria2c",
                )
                self._use_qbit = False

        # Filter already-existing files
        to_dl = []
        for r in self._files:
            target_dir = self._output / r["collection"] / (r["system"] or "unknown")
            target_path = target_dir / r["basename"]
            if target_path.exists() and target_path.stat().st_size == r["size"]:
                self.log.emit(f"Skipping existing: {r['basename']}")
                success += 1
                self.file_done.emit(success, total, r["basename"])
            else:
                to_dl.append(r)

        if not to_dl:
            self.progress.emit(total, total, f"Done — {success}/{total} already have")
            self.log.emit(f"All {success}/{total} files already exist")
            self.finished.emit()
            return

    def _save_queue(self):
        """Persist queue state for app restart."""
        import json

        data = json.dumps(
            [{"name": str(r["name"]), "collection": r["collection"]} for r in self._files],
            indent=2,
        )
        SAVED_QUEUE_PATH.write_text(data, encoding="utf-8")
