"""CDRomance / RetroGameTalk search dialog using the WordPress REST API."""

from __future__ import annotations

import json
from urllib.parse import quote
from urllib.request import Request, urlopen

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.ui.icons import Icons


class RepoSearchDialog(QtWidgets.QDialog):
    """Search retrogametalk.com/repo via the WordPress REST API.

    Shows results inline.  Selecting one opens the page in the system
    browser (or embedded ``RepoDialog`` if QtWebEngine is available).
    """

    def __init__(
        self,
        game_name: str,
        platform_slug: str | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Search CDRomance / RetroGameTalk")
        self.setObjectName("repoSearchDialog")
        self.resize(620, 480)
        self.setMinimumSize(420, 320)
        self._results: list[dict] = []

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        heading = QtWidgets.QLabel(f"Search results for: {game_name}")
        heading.setObjectName("sectionTitle")
        root.addWidget(heading)

        self._list = QtWidgets.QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.itemDoubleClicked.connect(self._on_open)
        root.addWidget(self._list, 1)

        self._status = QtWidgets.QLabel("Searching\u2026")
        self._status.setObjectName("mutedLabel")
        root.addWidget(self._status)

        btn_row = QtWidgets.QHBoxLayout()
        self._open_btn = QtWidgets.QPushButton(Icons.external(), "Open in browser")
        self._open_btn.setObjectName("primaryButton")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._on_open)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.setObjectName("subtleButton")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._open_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        self._search(game_name, platform_slug)

    def _search(self, game_name: str, platform_slug: str | None) -> None:
        base = "https://retrogametalk.com/repo/wp-json/wp/v2/search"
        url = f"{base}?search={quote(game_name)}&per_page=12"
        self._list.clear()
        try:
            req = Request(url, headers={"User-Agent": "MinervaFixDAT/1.0"})
            with urlopen(req, timeout=10) as resp:
                data: list[dict] = json.loads(resp.read().decode())
        except Exception as exc:
            self._status.setText(f"Search failed: {exc}")
            return

        if not data:
            self._status.setText("No results found. Try a different search term.")
            return

        # Filter by platform slug if provided
        if platform_slug:
            filtered = [
                r for r in data
                if f"/{platform_slug}/" in r.get("url", "")
            ]
            if filtered:
                data = filtered

        self._results = data
        for entry in data:
            title = entry.get("title", "Unknown")
            url_str = entry.get("url", "")
            # Extract platform from URL: /repo/{platform}/{slug}/
            parts = url_str.rstrip("/").split("/")
            platform = parts[-2] if len(parts) >= 2 else ""
            slug = parts[-1] if parts else ""
            text = f"{title}"
            subtitle = f"  [{platform}]  {slug}" if platform else ""
            item = QtWidgets.QListWidgetItem(f"{text}{subtitle}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, url_str)
            item.setToolTip(url_str)
            self._list.addItem(item)

        self._status.setText(f"{len(data)} result(s)")
        self._list.setCurrentRow(0)
        self._open_btn.setEnabled(True)

    def _on_open(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        url = item.data(QtCore.Qt.ItemDataRole.UserRole) or ""
        if not url:
            return

        # Try embedded RepoDialog first, fall back to system browser
        try:
            from minerva.ui.widgets.repo_browser import _HAS_WEBENGINE, RepoDialog  # noqa: F811
            if _HAS_WEBENGINE:
                from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F811
                dialog = RepoDialog(url, self)
                dialog.exec()
                return
        except ImportError:
            pass

        QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
