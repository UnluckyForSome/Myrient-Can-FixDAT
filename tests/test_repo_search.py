"""Tests for RepoSearchDialog — search parsing, result display, open."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.ui.widgets import repo_search
from minerva.ui.widgets.repo_search import RepoSearchDialog


def _mock_icon():
    return QtGui.QIcon()


def _mock_response(data):
    resp = MagicMock()
    resp.read.return_value = json.dumps(data).encode()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=resp)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


class TestSearchSuccess:
    def test_displays_results(self, qtbot, monkeypatch):
        data = [
            {"title": "Super Mario Bros", "url": "https://example.com/repo/nes/smb/"},
            {"title": "Zelda", "url": "https://example.com/repo/nes/zelda/"},
        ]
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.urlopen",
            lambda *a, **kw: _mock_response(data),
        )
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.Icons.external",
            _mock_icon,
        )
        d = RepoSearchDialog("mario")
        qtbot.addWidget(d)
        assert d._list.count() == 2
        assert d._open_btn.isEnabled()
        assert "2 result" in d._status.text()

    def test_filters_by_platform_slug(self, qtbot, monkeypatch):
        data = [
            {"title": "SMB", "url": "https://example.com/repo/nes/smb/"},
            {"title": "Sonic", "url": "https://example.com/repo/genesis/sonic/"},
        ]
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.urlopen",
            lambda *a, **kw: _mock_response(data),
        )
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.Icons.external",
            _mock_icon,
        )
        d = RepoSearchDialog("sonic", platform_slug="genesis")
        qtbot.addWidget(d)
        assert d._list.count() == 1
        assert "Sonic" in d._list.item(0).text()


class TestSearchFailure:
    def test_search_error_shows_status(self, qtbot, monkeypatch):
        def raise_err(*a, **kw):
            raise ConnectionError("DNS failure")
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.urlopen", raise_err,
        )
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.Icons.external",
            _mock_icon,
        )
        d = RepoSearchDialog("mario")
        qtbot.addWidget(d)
        assert "Search failed" in d._status.text()

    def test_no_results(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.urlopen",
            lambda *a, **kw: _mock_response([]),
        )
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.Icons.external",
            _mock_icon,
        )
        d = RepoSearchDialog("nonexistent")
        qtbot.addWidget(d)
        assert "No results" in d._status.text()


class TestOnOpen:
    def test_no_current_item_is_noop(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.urlopen",
            lambda *a, **kw: _mock_response([]),
        )
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.Icons.external",
            _mock_icon,
        )
        d = RepoSearchDialog("test")
        qtbot.addWidget(d)
        d._list.setCurrentRow(-1)
        d._on_open()

    def test_opens_url_in_browser(self, qtbot, monkeypatch):
        data = [{"title": "SMB", "url": "https://example.com/repo/nes/smb/"}]
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.urlopen",
            lambda *a, **kw: _mock_response(data),
        )
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.Icons.external",
            _mock_icon,
        )
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_browser._HAS_WEBENGINE", False,
        )
        d = RepoSearchDialog("mario")
        qtbot.addWidget(d)

        with patch("minerva.ui.widgets.repo_search.QtGui.QDesktopServices.openUrl") as mock_open:
            d._on_open()
            mock_open.assert_called_once()


class TestConstruction:
    def test_sets_title(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.urlopen",
            lambda *a, **kw: _mock_response([]),
        )
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.Icons.external",
            _mock_icon,
        )
        d = RepoSearchDialog("mario")
        qtbot.addWidget(d)
        assert "Search CDRomance" in d.windowTitle()

    def test_has_close_button(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.urlopen",
            lambda *a, **kw: _mock_response([]),
        )
        monkeypatch.setattr(
            "minerva.ui.widgets.repo_search.Icons.external",
            _mock_icon,
        )
        d = RepoSearchDialog("mario")
        qtbot.addWidget(d)
        close_btn = d.findChild(QtWidgets.QPushButton, "subtleButton")
        assert close_btn is not None
