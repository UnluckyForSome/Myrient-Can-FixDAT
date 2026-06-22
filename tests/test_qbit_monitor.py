"""Tests for QbitMonitor — hash tracking, polling, connection state."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6 import QtCore

from minerva.app.qbit_monitor import QbitMonitor
from minerva.domain.downloads import TorrentFileInfo, TorrentInfo
from minerva_qbit import QBittorrentError


@pytest.fixture
def mock_client():
    c = MagicMock()
    c.is_logged_in = True
    return c


@pytest.fixture
def monitor(mock_client):
    return QbitMonitor(mock_client)


class TestSetTrackedHashes:
    def test_empty_set(self, monitor):
        monitor.set_tracked_hashes(set())
        assert monitor.tracked_hashes == frozenset()

    def test_adds_hashes(self, monitor):
        monitor.set_tracked_hashes({"abc", "def"})
        assert monitor.tracked_hashes == frozenset({"abc", "def"})

    def test_filters_none_and_empty(self, monitor):
        monitor.set_tracked_hashes({"abc", "", None})
        assert monitor.tracked_hashes == frozenset({"abc"})

    def test_replaces_previous(self, monitor):
        monitor.set_tracked_hashes({"abc"})
        monitor.set_tracked_hashes({"def"})
        assert monitor.tracked_hashes == frozenset({"def"})


class TestStartStop:
    def test_start_creates_timer(self, monitor):
        monitor.start()
        assert monitor._timer is not None
        assert monitor._timer.isActive()

    def test_start_is_idempotent(self, monitor):
        monitor.start()
        timer1 = monitor._timer
        monitor.start()
        assert monitor._timer is timer1

    def test_stop_emits_stopped(self, qtbot, monitor):
        monitor.start()
        with qtbot.wait_signal(monitor.stopped, timeout=1000):
            monitor.stop()
        assert not monitor._timer.isActive()

    def test_stop_without_start_emits_stopped(self, qtbot, monitor):
        with qtbot.wait_signal(monitor.stopped, timeout=1000):
            monitor.stop()


class TestConnectionState:
    def test_default_disconnected(self, monitor):
        assert monitor.is_connected is False

    def test_set_connected_true(self, qtbot, monitor):
        with qtbot.wait_signal(monitor.connection_changed, timeout=1000) as blocker:
            monitor._set_connected(True)
        assert blocker.args == [True]
        assert monitor.is_connected is True

    def test_set_connected_false(self, qtbot, monitor):
        monitor._set_connected(True)
        with qtbot.wait_signal(monitor.connection_changed, timeout=1000) as blocker:
            monitor._set_connected(False)
        assert blocker.args == [False]
        assert monitor.is_connected is False

    def test_same_state_no_signal(self, qtbot, monitor):
        monitor._set_connected(True)
        emitted = []
        monitor.connection_changed.connect(lambda v: emitted.append(v))
        monitor._set_connected(True)
        assert emitted == []


class TestPoll:
    def test_no_tracked_hashes_is_noop(self, monitor, mock_client):
        monitor._poll()
        mock_client.list_torrents.assert_not_called()

    def test_poll_emits_snapshot(self, qtbot, monitor, mock_client):
        monitor.set_tracked_hashes({"h1"})
        mock_client.list_torrents.return_value = [
            {"hash": "h1", "name": "torrent1", "progress": 0.5,
             "state": "downloading", "dlspeed": 100, "upspeed": 0,
             "size": 1024, "completed": 512, "ratio": 0.5, "eta": 60,
             "save_path": "/seed", "num_seeds": 2, "num_leechs": 5},
        ]
        mock_client.get_files.return_value = [
            {"index": 0, "name": "rom.zip", "size": 1024, "progress": 0.5, "priority": 1},
        ]
        with qtbot.wait_signal(monitor.snapshot_ready, timeout=2000) as blocker:
            monitor._poll()
        snapshots = blocker.args[0]
        assert len(snapshots) == 1
        ti = snapshots[0]
        assert ti.hash == "h1"
        assert ti.name == "torrent1"
        assert ti.progress == 0.5
        assert len(ti.files) == 1
        assert ti.files[0].name == "rom.zip"

    def test_poll_handles_qbit_error(self, qtbot, monitor, mock_client):
        monitor.set_tracked_hashes({"h1"})
        mock_client.is_logged_in = True
        mock_client.list_torrents.side_effect = QBittorrentError("offline")
        with qtbot.wait_signal(monitor.error, timeout=2000) as blocker:
            monitor._poll()
        assert "offline" in blocker.args[0]
        assert monitor.is_connected is False

    def test_poll_skips_empty_hash(self, qtbot, monitor, mock_client):
        monitor.set_tracked_hashes({"h1"})
        mock_client.list_torrents.return_value = [
            {"hash": "", "name": "bad"},
            {"hash": "h1", "name": "good", "progress": 0.0,
             "state": "downloading", "dlspeed": 0, "upspeed": 0,
             "size": 0, "completed": 0, "ratio": 0.0, "eta": -1,
             "save_path": "", "num_seeds": 0, "num_leechs": 0},
        ]
        mock_client.get_files.return_value = []
        with qtbot.wait_signal(monitor.snapshot_ready, timeout=2000) as blocker:
            monitor._poll()
        assert len(blocker.args[0]) == 1
        assert blocker.args[0][0].hash == "h1"

    def test_poll_logs_in_if_not_logged_in(self, monitor, mock_client):
        monitor.set_tracked_hashes({"h1"})
        mock_client.is_logged_in = False
        mock_client.list_torrents.return_value = []
        monitor._poll()
        mock_client.login.assert_called_once()

    def test_poll_get_files_error_yields_empty_files(self, qtbot, monitor, mock_client):
        monitor.set_tracked_hashes({"h1"})
        mock_client.list_torrents.return_value = [
            {"hash": "h1", "name": "t", "progress": 0.0,
             "state": "downloading", "dlspeed": 0, "upspeed": 0,
             "size": 0, "completed": 0, "ratio": 0.0, "eta": -1,
             "save_path": "", "num_seeds": 0, "num_leechs": 0},
        ]
        mock_client.get_files.side_effect = QBittorrentError("nope")
        with qtbot.wait_signal(monitor.snapshot_ready, timeout=2000) as blocker:
            monitor._poll()
        ti = blocker.args[0][0]
        assert ti.files == ()

    def test_poll_no_results_no_signal(self, monitor, mock_client):
        monitor.set_tracked_hashes({"h1"})
        mock_client.list_torrents.return_value = []
        emitted = []
        monitor.snapshot_ready.connect(lambda data: emitted.append(data))
        monitor._poll()
        assert emitted == []
        assert monitor.is_connected is True
