"""Embedded web browser for CDRomance using QtWebEngine (optional).

QtWebEngine must be installed separately (``pip install PyQt6-WebEngine``).
If missing, ``RepoDialog`` shows an informative message instead of crashing.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6 import QtCore, QtWidgets


# Check availability at module level for callers to test
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView as _QWEV  # noqa: F401
    _HAS_WEBENGINE = True
except ImportError:
    _HAS_WEBENGINE = False


class RepoDialog(QtWidgets.QDialog):
    """Embedded browser for CDRomance — requires QtWebEngine.

    If QtWebEngine is not installed, the dialog shows an informational
    message and a ``pip install`` hint.
    """

    download_completed = QtCore.pyqtSignal(str, str)  # filename, path

    def __init__(
        self,
        url: str = "https://cdromance.org",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("CDRomance")
        self.setObjectName("repoDialog")
        self.resize(640, 320)
        self.setMinimumSize(480, 240)

        root = QtWidgets.QVBoxLayout(self)

        if not _HAS_WEBENGINE:
            root.setContentsMargins(24, 24, 24, 24)
            icon = QtWidgets.QLabel("\u26a0")
            icon.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            icon.setStyleSheet("font-size: 48px;")
            root.addWidget(icon)
            msg = QtWidgets.QLabel(
                "The embedded browser requires QtWebEngine.\n\n"
                "Install it with:\n"
                "  pip install PyQt6-WebEngine\n\n"
                "Then restart the app."
            )
            msg.setWordWrap(True)
            msg.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            msg.setObjectName("mutedLabel")
            root.addWidget(msg, 1)
            close_btn = QtWidgets.QPushButton("Close")
            close_btn.setObjectName("primaryButton")
            close_btn.clicked.connect(self.reject)
            root.addWidget(close_btn, 0, QtCore.Qt.AlignmentFlag.AlignCenter)
            return

        self._pending_crc: str | None = None
        from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest  # noqa: F811

        self._QWebEngineDownloadRequest = QWebEngineDownloadRequest

        self.resize(1024, 720)
        self.setMinimumSize(720, 480)

        self._settings = QtCore.QSettings("MinervaFixDAT", "MinervaGUI")
        self._output_dir = Path(
            self._settings.value("output_dir", "downloads", str)
        )

        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        nav = QtWidgets.QHBoxLayout()
        nav.setContentsMargins(8, 8, 8, 8)
        nav.setSpacing(6)

        self._back = QtWidgets.QPushButton("\u25c0")
        self._back.setObjectName("subtleButton")
        self._back.setFixedWidth(36)
        nav.addWidget(self._back)

        self._forward = QtWidgets.QPushButton("\u25b6")
        self._forward.setObjectName("subtleButton")
        self._forward.setFixedWidth(36)
        nav.addWidget(self._forward)

        self._url_bar = QtWidgets.QLineEdit()
        self._url_bar.setPlaceholderText(url)
        nav.addWidget(self._url_bar, 1)

        self._go = QtWidgets.QPushButton("Go")
        self._go.setObjectName("primaryButton")
        nav.addWidget(self._go)

        root.addLayout(nav)

        self._view = _QWEV()
        self._view.setUrl(QtCore.QUrl(url))
        root.addWidget(self._view)

        self._status = QtWidgets.QLabel()
        self._status.setObjectName("mutedLabel")
        self._status.setContentsMargins(8, 4, 8, 4)
        root.addWidget(self._status)

        self._back.clicked.connect(self._view.back)
        self._forward.clicked.connect(self._view.forward)
        self._go.clicked.connect(self._navigate)
        self._url_bar.returnPressed.connect(self._navigate)
        self._view.urlChanged.connect(self._on_url_changed)
        self._view.loadFinished.connect(self._on_page_loaded)
        self._view.loadProgress.connect(self._on_progress)

        profile = self._view.page().profile()
        profile.downloadRequested.connect(self._on_download_requested)

        self._view.setUrl(QtCore.QUrl(url))

    def _navigate(self) -> None:
        raw = self._url_bar.text().strip()
        if not raw:
            return
        if not raw.startswith("http://") and not raw.startswith("https://"):
            raw = "https://" + raw
        self._view.setUrl(QtCore.QUrl(raw))

    def _on_url_changed(self, url: QtCore.QUrl) -> None:
        self._url_bar.setText(url.toString())

    def _on_progress(self, progress: int) -> None:
        if progress < 100:
            self._status.setText(f"Loading\u2026 {progress}%")

    def _on_page_loaded(self, ok: bool) -> None:
        if not ok:
            self._status.setText("Page load failed")
            return
        self._status.setText("Done")
        self._view.page().runJavaScript(
            """
            (function() {
                for (const th of document.querySelectorAll('th')) {
                    if (th.textContent.trim() === 'CRC-32') {
                        const td = th.nextElementSibling;
                        if (td) return td.textContent.trim();
                    }
                }
                return null;
            })()
            """,
            self._on_crc_found,
        )

    def _on_crc_found(self, crc: str | None) -> None:
        if crc:
            self._pending_crc = crc
            self._status.setText(f"CRC-32: {crc}  \u2014 verified after download")

    def _on_download_requested(self, download) -> None:
        from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest  # noqa: F811

        suggested = Path(download.suggestedFileName())
        dest = self._output_dir / suggested.name
        download.setDownloadDirectory(str(self._output_dir))
        download.setDownloadFileName(suggested.name)
        self._status.setText(f"Downloading {suggested.name} \u2026")

        def _on_finished() -> None:
            completed = QWebEngineDownloadRequest.DownloadState.DownloadCompleted
            if download.state() == completed:
                self._status.setText(f"Downloaded: {suggested.name}")
                self._verify_crc(suggested.name, str(dest))
                self.download_completed.emit(suggested.name, str(dest))
            else:
                self._status.setText(f"Download failed: {suggested.name}")

        download.isFinishedChanged.connect(_on_finished)
        download.accept()

    def _verify_crc(self, filename: str, path: str) -> None:
        if not self._pending_crc:
            return
        try:
            import binascii
            computed = f"{binascii.crc32(Path(path).read_bytes()) & 0xFFFFFFFF:08X}"
            expected = self._pending_crc.upper().replace("0X", "")
            match = computed == expected
            status = "verified" if match else "CRC MISMATCH"
            self._status.setText(f"{filename}  \u2014 {status} (CRC-32: {computed})")
        except Exception:
            pass
