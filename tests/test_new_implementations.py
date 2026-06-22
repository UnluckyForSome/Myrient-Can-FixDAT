"""
Tests for recently wired implementations: activity timestamps,
library context menu, and CLI download.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PyQt6 import QtCore, QtWidgets

from minerva.app.app_state import AppState
from minerva.app.pages.downloads import DownloadsPage
from minerva.app.pages.library import LibraryPage

log = logging.getLogger(__name__)


# ============================================================================
# 1. DownloadsPage._on_activity_event
# ============================================================================


class TestDownloadsPageActivityEvent:
    """Verifies timestamps are generated for activity events."""

    def test_on_activity_event_adds_timestamp(self, qtbot):
        """GIVEN a DownloadsPage WHEN _on_activity_event is called THEN
        the activity_list receives a ``HH:MM:SS`` timestamp."""
        page = DownloadsPage(AppState())
        qtbot.addWidget(page)

        page._activity_list.add_event = MagicMock()
        page._on_activity_event("download", "Test message")

        args, _kwargs = page._activity_list.add_event.call_args
        _category, _message, timestamp = args
        # Sanity check: should be HH:MM:SS.
        assert len(timestamp) == 8
        assert timestamp.count(":") == 2

    def test_on_activity_event_uses_current_time(self, qtbot):
        """GIVEN the system clock WHEN the event fires THEN the
        recorded timestamp is the same HH:MM:SS as ``time.strftime``."""
        page = DownloadsPage(AppState())
        qtbot.addWidget(page)

        page._activity_list.add_event = MagicMock()
        expected = time.strftime("%H:%M:%S")
        page._on_activity_event("info", "hello")

        actual = page._activity_list.add_event.call_args[0][2]
        # Allow ±1 second drift across the call.
        assert actual == expected or abs(
            time.mktime(time.strptime(actual, "%H:%M:%S"))
            - time.mktime(time.strptime(expected, "%H:%M:%S"))
        ) <= 1


# ============================================================================
# 3. LibraryPage._on_context_menu
# ============================================================================


class TestLibraryPageContextMenu:
    """Tests that the context menu wiring does not crash."""

    def test_context_menu_shows_on_viewport(self, qtbot, monkeypatch):
        """GIVEN a LibraryPage WHEN the context menu is requested on an
        invalid (empty) index THEN the menu is built and ``exec`` is
        called once on the viewport-mapped global point."""
        monkeypatch.setattr(
            "minerva.app.pages.library.MinervaDB",
            lambda: MagicMock(),
        )
        page = LibraryPage(AppState())
        qtbot.addWidget(page)

        mock_menu = MagicMock()
        mock_menu.exec.return_value = None
        with patch(
            "minerva.app.pages.library.QtWidgets.QMenu",
            return_value=mock_menu,
        ):
            page._on_context_menu(QtCore.QPoint(0, 0))

        mock_menu.exec.assert_called_once()
        # The empty-area branch should have at least one action.
        assert mock_menu.addAction.called


# ============================================================================
# 4. minerva_cli.command_download
# ============================================================================


class TestCLIDownloadCommand:
    """Exercises the headless qBittorrent download flow."""

    def _make_spec(self, **overrides) -> MagicMock:
        spec = MagicMock(
            basename="test.zip",
            torrent_name="test_torrent",
            torrent_path=Path("/fake/test.torrent"),
            select_index=1,
        )
        for key, value in overrides.items():
            setattr(spec, key, value)
        return spec

    def test_command_download_no_spec_exits(self, monkeypatch):
        """GIVEN an unknown file_id WHEN command_download is called THEN
        it raises SystemExit."""
        from minerva_cli import command_download

        mock_db = MagicMock()
        mock_db.get_download_spec.return_value = None
        monkeypatch.setattr("minerva_cli.MinervaDB", lambda: mock_db)

        args = MagicMock()
        args.file_id = 999

        with pytest.raises(SystemExit):
            command_download(args)

    def test_command_download_connection_failure(self, monkeypatch):
        """GIVEN a valid spec but unreachable qBittorrent WHEN
        command_download is called THEN ``client.login`` propagates
        the ConnectionError."""
        from minerva_cli import command_download

        mock_db = MagicMock()
        mock_db.get_download_spec.return_value = self._make_spec()
        monkeypatch.setattr("minerva_cli.MinervaDB", lambda: mock_db)

        mock_client = MagicMock()
        mock_client.login.side_effect = ConnectionError("Refused")
        monkeypatch.setattr(
            "minerva_cli.QBittorrentClient", lambda *a: mock_client
        )

        monkeypatch.setenv("MINERVA_QBIT_URL", "http://localhost:8080")
        monkeypatch.setenv("MINERVA_QBIT_USER", "admin")
        monkeypatch.setenv("MINERVA_QBIT_PASS", "adminadmin")

        args = MagicMock()
        args.file_id = 1
        args.dest = "/tmp/downloads"

        with pytest.raises(ConnectionError):
            command_download(args)

    def test_command_download_success(self, monkeypatch, capsys):
        """GIVEN a valid spec and a connected qBittorrent WHEN
        command_download is called THEN the torrent is added paused,
        the file priorities are set, and the torrent is resumed."""
        from minerva_cli import command_download

        mock_db = MagicMock()
        mock_db.get_download_spec.return_value = self._make_spec()
        monkeypatch.setattr("minerva_cli.MinervaDB", lambda: mock_db)

        mock_client = MagicMock()
        mock_client.login.return_value = None
        mock_client.add_torrent_paused.return_value = "deadbeef"
        mock_client.get_files.return_value = [
            {"index": 0, "name": "test.zip", "size": 1000},
            {"index": 1, "name": "extra.rom", "size": 500},
        ]
        monkeypatch.setattr(
            "minerva_cli.QBittorrentClient", lambda *a: mock_client
        )

        monkeypatch.setenv("MINERVA_QBIT_URL", "http://localhost:8080")
        monkeypatch.setenv("MINERVA_QBIT_USER", "admin")
        monkeypatch.setenv("MINERVA_QBIT_PASS", "adminadmin")

        args = MagicMock()
        args.file_id = 1
        args.dest = "/tmp/downloads"

        command_download(args)

        mock_client.add_torrent_paused.assert_called_once()
        # Two priority adjustments: first zero everything, then enable
        # the target file at index ``select_index - 1``.
        assert mock_client.set_file_priority.call_count == 2
        mock_client.resume.assert_called_once_with("deadbeef")

        captured = capsys.readouterr()
        assert "test.zip" in captured.out
        assert "deadbeef" in captured.out
