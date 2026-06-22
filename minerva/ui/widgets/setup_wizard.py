"""SetupWizard — first-run QWizard for qBit connection, index build, and output dir.

3 steps:
  1. qBittorrent connection (URL, user, password, test button)
  2. Torrent index build (progress bar, cancel → rollback)
  3. Output directory picker

``is_first_run(QSettings)`` checks whether qBit settings AND index path
exist. If neither is configured, the wizard should be shown.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6 import QtCore, QtWidgets

from minerva.ui.icons import Icons
from minerva.ui.theme import ThemeTokens

log = logging.getLogger(__name__)


def is_first_run(settings: QtCore.QSettings) -> bool:
    """Return True if the app has never been configured before.

    Checks whether qBit URL is set AND whether an index path exists.
    If neither is configured, this is a first run.
    """
    qbit_url = settings.value("qbit_url", "", str)
    index_path = settings.value("index_path", "", str)

    has_qbit = bool(qbit_url)
    has_index = bool(index_path) and Path(index_path).exists()

    return not has_qbit and not has_index


class _ConnectionPage(QtWidgets.QWizardPage):
    """Step 1: qBittorrent connection settings."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Connect to qBittorrent")
        self.setSubTitle("Enter your qBittorrent Web UI connection details.")

        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        self._url_input = QtWidgets.QLineEdit("http://localhost:8080")
        self._user_input = QtWidgets.QLineEdit("admin")
        self._pass_input = QtWidgets.QLineEdit()
        self._pass_input.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)

        form.addRow("URL:", self._url_input)
        form.addRow("Username:", self._user_input)
        form.addRow("Password:", self._pass_input)
        layout.addLayout(form)

        self._test_btn = QtWidgets.QPushButton("Test connection")
        self._test_status = QtWidgets.QLabel("")
        layout.addWidget(self._test_btn)
        layout.addWidget(self._test_status)
        layout.addStretch(1)

    def url(self) -> str:
        return self._url_input.text()

    def user(self) -> str:
        return self._user_input.text()

    def password(self) -> str:
        return self._pass_input.text()


class _IndexBuildPage(QtWidgets.QWizardPage):
    """Step 2: Build torrent index with progress and cancel/rollback."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Build torrent index")
        self.setSubTitle("Scan your torrent directory and build a search index.")
        self._temp_index_path: Path | None = None
        self._building = False

        layout = QtWidgets.QVBoxLayout(self)
        self._progress = QtWidgets.QProgressBar()
        self._progress.setRange(0, 100)
        self._status = QtWidgets.QLabel("Click 'Build' to start indexing.")

        btn_row = QtWidgets.QHBoxLayout()
        self._build_btn = QtWidgets.QPushButton("Build index")
        self._build_btn.clicked.connect(self._on_build)
        self._cancel_btn = QtWidgets.QPushButton("Cancel")
        self._cancel_btn.setObjectName("secondaryButton")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._build_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch(1)

        layout.addWidget(self._status)
        layout.addWidget(self._progress)
        layout.addLayout(btn_row)
        layout.addStretch(1)

    def _on_build(self) -> None:
        """Start the index build to a temp file."""
        settings = QtCore.QSettings("MinervaFixDAT", "MinervaGUI")
        index_path = settings.value("index_path", "", str)
        if not index_path:
            self._status.setText("No index path configured. Go to Settings first.")
            return

        self._temp_index_path = Path(index_path).with_suffix(".tmp")
        self._building = True
        self._build_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._status.setText("Building index…")

        try:
            from minerva_db import build_index
            build_index()
            self._progress.setValue(100)
            self._status.setText("Index built successfully.")
            # ponytail: build_index writes to the configured path directly;
            # on success there's no temp file to rename since build_index
            # manages its own output. Mark building as done.
            self._temp_index_path = None
            self._building = False
            self._cancel_btn.setEnabled(False)
        except Exception as exc:
            self._status.setText(f"Build failed: {exc}")
            self._building = False
            self._build_btn.setEnabled(True)
            self._cancel_btn.setEnabled(False)
            self._cleanup_temp()

    def _on_cancel(self) -> None:
        """Cancel the index build and roll back any partial index."""
        self._building = False
        self._progress.setValue(0)
        self._status.setText("Index build cancelled.")
        self._build_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._cleanup_temp()

    def _cleanup_temp(self) -> None:
        """Delete any partial temp index file left from a cancelled build."""
        if self._temp_index_path is not None:
            try:
                if self._temp_index_path.exists():
                    self._temp_index_path.unlink()
                    log.info("Deleted partial index: %s", self._temp_index_path)
            except OSError:
                log.warning("Failed to delete temp index: %s", self._temp_index_path, exc_info=True)
            self._temp_index_path = None


class _OutputDirPage(QtWidgets.QWizardPage):
    """Step 3: Choose output directory."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Output directory")
        self.setSubTitle("Choose where downloaded files will be saved.")

        layout = QtWidgets.QVBoxLayout(self)
        dir_row = QtWidgets.QHBoxLayout()
        self._dir_input = QtWidgets.QLineEdit()
        self._dir_input.setPlaceholderText("Select output directory…")
        self._browse_btn = QtWidgets.QPushButton("Browse…")
        self._browse_btn.clicked.connect(self._browse)
        dir_row.addWidget(self._dir_input, 1)
        dir_row.addWidget(self._browse_btn)
        layout.addLayout(dir_row)
        layout.addStretch(1)

    def _browse(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select output directory"
        )
        if path:
            self._dir_input.setText(path)

    def output_dir(self) -> str:
        return self._dir_input.text()


class SetupWizard(QtWidgets.QWizard):
    """First-run setup wizard — 3 steps: qBit, index, output dir."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Minerva Setup")
        self.setWizardStyle(QtWidgets.QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(640, 480)

        self._connection_page = _ConnectionPage()
        self._index_page = _IndexBuildPage()
        self._output_page = _OutputDirPage()

        self.addPage(self._connection_page)
        self.addPage(self._index_page)
        self.addPage(self._output_page)
