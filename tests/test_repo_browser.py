"""Tests for RepoDialog — verify CRC, navigate, no-WebEngine fallback."""

from __future__ import annotations

import binascii
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PyQt6 import QtCore, QtWidgets

from minerva.ui.widgets import repo_browser
from minerva.ui.widgets.repo_browser import RepoDialog


@pytest.fixture
def dialog(qtbot, monkeypatch, tmp_path):
    """RepoDialog in no-WebEngine mode with WebEngine widgets attached for testing."""
    monkeypatch.setattr(repo_browser, "_HAS_WEBENGINE", False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    d = RepoDialog()
    # Attach the widgets that the WebEngine branch would have created.
    d._status = QtWidgets.QLabel()
    d._url_bar = QtWidgets.QLineEdit()
    d._view = MagicMock()
    d._pending_crc = None
    qtbot.addWidget(d)
    return d


class TestNoWebEngineFallback:
    def test_shows_install_hint(self, qtbot, monkeypatch, tmp_path):
        monkeypatch.setattr(repo_browser, "_HAS_WEBENGINE", False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        d = RepoDialog()
        qtbot.addWidget(d)
        labels = d.findChildren(QtWidgets.QLabel)
        texts = [l.text() for l in labels]
        assert any("QtWebEngine" in t for t in texts)

    def test_has_close_button(self, qtbot, monkeypatch, tmp_path):
        monkeypatch.setattr(repo_browser, "_HAS_WEBENGINE", False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        d = RepoDialog()
        qtbot.addWidget(d)
        btn = d.findChild(QtWidgets.QPushButton)
        assert btn is not None
        assert btn.text() == "Close"

    def test_close_rejects(self, qtbot, monkeypatch, tmp_path):
        monkeypatch.setattr(repo_browser, "_HAS_WEBENGINE", False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        d = RepoDialog()
        qtbot.addWidget(d)
        btn = d.findChild(QtWidgets.QPushButton)
        with qtbot.wait_signal(d.rejected, timeout=1000):
            qtbot.mouseClick(btn, QtCore.Qt.MouseButton.LeftButton)


class TestVerifyCrc:
    def test_no_pending_crc_is_noop(self, dialog):
        dialog._pending_crc = None
        dialog._verify_crc("file.zip", "/nonexistent")

    def test_matching_crc_shows_verified(self, dialog, tmp_path):
        data = b"hello world"
        path = tmp_path / "rom.zip"
        path.write_bytes(data)
        expected = f"{binascii.crc32(data) & 0xFFFFFFFF:08X}"
        dialog._pending_crc = expected
        dialog._verify_crc("rom.zip", str(path))
        assert "verified" in dialog._status.text()

    def test_mismatching_crc_shows_mismatch(self, dialog, tmp_path):
        path = tmp_path / "rom.zip"
        path.write_bytes(b"hello world")
        dialog._pending_crc = "00000000"
        dialog._verify_crc("rom.zip", str(path))
        assert "MISMATCH" in dialog._status.text()

    def test_hex_prefix_stripped(self, dialog, tmp_path):
        data = b"test"
        path = tmp_path / "rom.zip"
        path.write_bytes(data)
        expected = f"{binascii.crc32(data) & 0xFFFFFFFF:08X}"
        dialog._pending_crc = f"0X{expected}"
        dialog._verify_crc("rom.zip", str(path))
        assert "verified" in dialog._status.text()

    def test_missing_file_silent(self, dialog):
        dialog._pending_crc = "DEADBEEF"
        dialog._verify_crc("rom.zip", "/nonexistent/path")


class TestNavigate:
    def test_empty_url_is_noop(self, dialog):
        dialog._url_bar.setText("")
        dialog._navigate()
        dialog._view.setUrl.assert_not_called()

    def test_adds_https_prefix(self, dialog):
        dialog._url_bar.setText("example.com")
        dialog._navigate()
        dialog._view.setUrl.assert_called_once()
        url = dialog._view.setUrl.call_args[0][0]
        assert url.toString().startswith("https://")

    def test_preserves_http(self, dialog):
        dialog._url_bar.setText("http://example.com")
        dialog._navigate()
        url = dialog._view.setUrl.call_args[0][0]
        assert url.toString().startswith("http://")


class TestOnUrlChanged:
    def test_updates_url_bar(self, dialog):
        url = QtCore.QUrl("https://example.com/page")
        dialog._on_url_changed(url)
        assert dialog._url_bar.text() == "https://example.com/page"


class TestOnProgress:
    def test_below_100_shows_loading(self, dialog):
        dialog._on_progress(50)
        assert "50%" in dialog._status.text()


class TestOnPageLoaded:
    def test_failed_load(self, dialog):
        dialog._on_page_loaded(False)
        assert "failed" in dialog._status.text().lower()
