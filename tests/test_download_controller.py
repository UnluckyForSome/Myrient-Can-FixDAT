"""
Tests for DownloadController — queue commands, queries, snapshot
reconciliation, and qBittorrent state mapping.

Uses an in-memory-file MinervaState (tmp_path) and a mock QBittorrentClient.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt6 import QtCore

from minerva.app.app_state import AppState
from minerva.app.download_controller import DownloadController, _FunctionTask
from minerva.domain.downloads import (
    DownloadFileSpec,
    DownloadRuntime,
    DownloadStatus,
    QueueRecord,
    TorrentFileInfo,
    TorrentInfo,
)
from minerva_state import MinervaState


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def state(tmp_path):
    return MinervaState(tmp_path / "state.db")


@pytest.fixture
def app_state():
    return AppState()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.is_logged_in = True
    client.clone.return_value = client
    client.login.return_value = None
    return client


@pytest.fixture
def controller(state, app_state, mock_client, tmp_path, monkeypatch):
    c = DownloadController(
        state, app_state, mock_client, seed_dir=tmp_path / "seed",
    )
    # ponytail: prevent async torrent submission from flipping records to
    # FAILED; most tests only care about queue-state transitions.
    monkeypatch.setattr(c, "_schedule_record_submission", lambda record: None)
    return c


def _make_spec(file_id: int = 1, torrent_name: str = "test.torrent") -> DownloadFileSpec:
    return DownloadFileSpec(
        file_id=file_id,
        torrent_name=torrent_name,
        torrent_path=Path(f"/fake/{torrent_name}"),
        select_index=1,
        basename="rom.zip",
        path_in_torrent="rom.zip",
        size=1024,
        collection="Nintendo",
        system="NES",
    )


# ============================================================================
# _map_qbit_state — pure classmethod, all status mappings
# ============================================================================


class TestMapQbitState:
    @pytest.mark.parametrize("raw,expected", [
        ("error", DownloadStatus.FAILED),
        ("missingFiles", DownloadStatus.FAILED),
        ("pausedDL", DownloadStatus.PAUSED),
        ("queuedDL", DownloadStatus.QUEUED),
        ("downloading", DownloadStatus.DOWNLOADING),
        ("stalledDL", DownloadStatus.DOWNLOADING),
        ("forcedDL", DownloadStatus.DOWNLOADING),
        ("metaDL", DownloadStatus.STARTING),
        ("checkingDL", DownloadStatus.STARTING),
        ("checkingUP", DownloadStatus.STARTING),
        ("allocating", DownloadStatus.STARTING),
        ("checkingResumeData", DownloadStatus.STARTING),
        ("moving", DownloadStatus.STARTING),
        ("pausedUP", DownloadStatus.COMPLETED),
    ])
    def test_known_states(self, raw, expected):
        assert DownloadController._map_qbit_state(raw, 0.0) == expected

    def test_unknown_state_defaults_to_downloading(self):
        assert DownloadController._map_qbit_state("bogus", 0.0) == DownloadStatus.DOWNLOADING

    def test_complete_progress_non_upload(self):
        assert DownloadController._map_qbit_state("downloading", 1.0) == DownloadStatus.COMPLETED

    def test_complete_progress_upload_state_is_seeding(self):
        for raw in ("uploading", "stalledUP", "forcedUP", "queuedUP"):
            assert DownloadController._map_qbit_state(raw, 1.0) == DownloadStatus.SEEDING

    def test_complete_progress_pausedUP_is_completed(self):
        assert DownloadController._map_qbit_state("pausedUP", 1.0) == DownloadStatus.COMPLETED


# ============================================================================
# add_to_queue
# ============================================================================


class TestAddToQueue:
    def test_creates_queued_record(self, controller, state):

        rid = controller.add_to_queue(42, "/dest/rom.zip")
        records = state.list_queue()
        assert len(records) == 1
        assert records[0].id == rid
        assert records[0].file_id == 42
        assert records[0].status == DownloadStatus.QUEUED.value
        assert records[0].destination == "/dest/rom.zip"

    def test_dedup_returns_existing_id(self, controller, state):

        rid1 = controller.add_to_queue(1, "/dest/a.zip")
        rid2 = controller.add_to_queue(1, "/dest/a.zip")
        assert rid1 == rid2
        assert len(state.list_queue()) == 1

    def test_dedup_allows_after_cancelled(self, controller, state):

        rid1 = controller.add_to_queue(1, "/dest/a.zip")
        state.update_queue_record(rid1, status=DownloadStatus.CANCELLED.value)
        rid2 = controller.add_to_queue(1, "/dest/a.zip")
        assert rid1 != rid2
        assert len(state.list_queue()) == 2

    def test_dedup_allows_after_failed(self, controller, state):

        rid1 = controller.add_to_queue(1, "/dest/a.zip")
        state.update_queue_record(rid1, status=DownloadStatus.FAILED.value)
        rid2 = controller.add_to_queue(1, "/dest/a.zip")
        assert rid1 != rid2

    def test_different_destinations_create_separate_records(self, controller, state):

        controller.add_to_queue(1, "/dest/a.zip")
        controller.add_to_queue(1, "/dest/b.zip")
        assert len(state.list_queue()) == 2

    def test_emits_queue_changed(self, controller, qtbot):

        with qtbot.wait_signal(controller.queue_changed, timeout=1000):
            controller.add_to_queue(1, "/dest/a.zip")


# ============================================================================
# add_many_to_queue
# ============================================================================


class TestAddManyToQueue:
    def test_creates_multiple_records(self, controller, state):
        controller.file_spec_resolver = lambda fid: _make_spec(file_id=fid)
        ids = controller.add_many_to_queue([
            (1, "/dest/a.zip", None),
            (2, "/dest/b.zip", "entry-1"),
        ])
        assert len(ids) == 2
        assert len(state.list_queue()) == 2


# ============================================================================
# Queries
# ============================================================================


class TestQueries:
    def test_get_queue_empty(self, controller):
        assert controller.get_queue() == []

    def test_get_queue_returns_records(self, controller, state):

        controller.add_to_queue(1, "/dest/a.zip")
        assert len(controller.get_queue()) == 1

    def test_get_runtime_empty(self, controller):
        assert controller.get_runtime() == []

    def test_get_runtime_for_unknown(self, controller):
        assert controller.get_runtime_for("nope") is None

    def test_get_active_records_filters_completed(self, controller, state):

        rid = controller.add_to_queue(1, "/dest/a.zip")
        state.update_queue_record(rid, status=DownloadStatus.COMPLETED.value)
        assert len(controller.get_active_records()) == 0

    def test_get_active_records_includes_queued(self, controller):

        controller.add_to_queue(1, "/dest/a.zip")
        assert len(controller.get_active_records()) == 1

    def test_has_active_downloads_false_when_empty(self, controller):
        assert controller.has_active_downloads() is False

    def test_has_active_downloads_true_for_queued(self, controller):

        controller.add_to_queue(1, "/dest/a.zip")
        assert controller.has_active_downloads() is True

    def test_has_active_downloads_false_for_completed(self, controller, state):

        rid = controller.add_to_queue(1, "/dest/a.zip")
        state.update_queue_record(rid, status=DownloadStatus.COMPLETED.value)
        assert controller.has_active_downloads() is False


# ============================================================================
# pause / resume / retry — no qbit_hash path (pure state updates)
# ============================================================================


class TestPauseResumeRetry:
    def test_pause_no_hash_sets_paused(self, controller, state):

        rid = controller.add_to_queue(1, "/dest/a.zip")
        controller.pause(rid)
        assert state.list_queue()[0].status == DownloadStatus.PAUSED.value

    def test_pause_unknown_record_is_noop(self, controller):
        controller.pause("nonexistent")

    def test_resume_no_hash_sets_queued(self, controller, state):

        rid = controller.add_to_queue(1, "/dest/a.zip")
        controller.pause(rid)
        controller.resume(rid)
        assert state.list_queue()[0].status == DownloadStatus.QUEUED.value

    def test_resume_unknown_record_is_noop(self, controller):
        controller.resume("nonexistent")

    def test_retry_resets_to_queued(self, controller, state):

        rid = controller.add_to_queue(1, "/dest/a.zip")
        state.update_queue_record(rid, status=DownloadStatus.FAILED.value, error="boom")
        controller.retry(rid)
        rec = state.list_queue()[0]
        assert rec.status == DownloadStatus.QUEUED.value
        assert rec.error is None
        assert rec.qbit_hash is None

    def test_retry_unknown_record_is_noop(self, controller):
        controller.retry("nonexistent")


# ============================================================================
# remove
# ============================================================================


class TestRemove:
    def test_remove_deletes_record(self, controller, state):

        rid = controller.add_to_queue(1, "/dest/a.zip")
        controller.remove(rid)
        assert len(state.list_queue()) == 0

    def test_remove_unknown_is_noop(self, controller):
        controller.remove("nonexistent")

    def test_remove_cleans_runtime(self, controller, state):

        rid = controller.add_to_queue(1, "/dest/a.zip")
        controller._runtime[rid] = DownloadRuntime(
            record_id=rid, qbit_hash=None, torrent_name="t",
        )
        controller.remove(rid)
        assert rid not in controller._runtime

    def test_remove_with_delete_files_removes_destination(self, controller, state, tmp_path):

        dest = tmp_path / "out" / "rom.zip"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"data")
        rid = controller.add_to_queue(1, str(dest))
        controller.remove(rid, delete_files=True)
        assert not dest.exists()

    def test_remove_many(self, controller, state):

        r1 = controller.add_to_queue(1, "/dest/a.zip")
        r2 = controller.add_to_queue(2, "/dest/b.zip")
        controller.remove_many([r1, r2])
        assert len(state.list_queue()) == 0


# ============================================================================
# _resolve_spec — caching
# ============================================================================


class TestResolveSpec:
    def test_returns_none_without_resolver(self, controller):
        assert controller._resolve_spec(1) is None

    def test_caches_spec(self, controller):
        calls = []
        def resolver(fid):
            calls.append(fid)
            return _make_spec(file_id=fid)
        controller.file_spec_resolver = resolver
        s1 = controller._resolve_spec(1)
        s2 = controller._resolve_spec(1)
        assert s1 is s2
        assert len(calls) == 1

    def test_returns_none_when_resolver_returns_none(self, controller):

        assert controller._resolve_spec(1) is None


# ============================================================================
# _on_index_changed — clears spec cache
# ============================================================================


def test_on_index_changed_clears_spec_cache(controller):
    controller.file_spec_resolver = lambda fid: _make_spec(file_id=fid)
    controller._resolve_spec(1)
    assert 1 in controller._spec_cache
    controller._on_index_changed(None)
    assert len(controller._spec_cache) == 0


# ============================================================================
# _on_snapshot — reconciliation
# ============================================================================


class TestOnSnapshot:
    def test_empty_snapshots_keep_runtime(self, controller, state):
        """An empty snapshot does not delete existing runtime entries."""
        controller.file_spec_resolver = lambda fid: _make_spec(file_id=fid)
        rid = controller.add_to_queue(1, "/dest/a.zip")
        controller._runtime[rid] = DownloadRuntime(
            record_id=rid, qbit_hash="abc", torrent_name="t",
        )
        controller._on_snapshot([])
        assert len(controller.get_runtime()) == 1

    def test_updates_runtime_for_matching_hash(self, controller, state):
        controller.file_spec_resolver = lambda fid: _make_spec(file_id=fid)
        rid = controller.add_to_queue(1, "/dest/a.zip")
        state.update_queue_record(rid, qbit_hash="deadbeef")

        ti = TorrentInfo(
            hash="deadbeef", name="test_torrent", progress=0.5,
            state="downloading", dlspeed=100, upspeed=0, size=2048,
            completed=1024, ratio=0.5, eta=60, save_path="/seed",
            seeds=2, peers=5,
            files=(TorrentFileInfo(
                index=0, name="rom.zip", size=1024, progress=0.5, priority=1,
            ),),
        )
        controller._on_snapshot([ti])
        rt = controller.get_runtime_for(rid)
        assert rt is not None
        assert rt.qbit_hash == "deadbeef"
        assert rt.progress == 0.5
        assert rt.download_speed == 100

    def test_status_transition_to_downloading(self, controller, state):
        controller.file_spec_resolver = lambda fid: _make_spec(file_id=fid)
        rid = controller.add_to_queue(1, "/dest/a.zip")
        state.update_queue_record(rid, qbit_hash="h1")

        ti = TorrentInfo(
            hash="h1", name="t", progress=0.0, state="downloading",
            dlspeed=10, upspeed=0, size=100, completed=0, ratio=0.0,
            eta=10, save_path="/s", seeds=0, peers=1, files=(),
        )
        controller._on_snapshot([ti])
        assert state.list_queue()[0].status == DownloadStatus.DOWNLOADING.value

    def test_status_transition_to_seeding(self, controller, state):
        # Already completed; a subsequent snapshot showing an upload state
        # should flip to SEEDING via the status-update branch.
        controller.file_spec_resolver = lambda fid: _make_spec(file_id=fid)
        rid = controller.add_to_queue(1, "/dest/a.zip")
        state.update_queue_record(
            rid, qbit_hash="h1", status=DownloadStatus.COMPLETED.value,
        )

        ti = TorrentInfo(
            hash="h1", name="t", progress=1.0, state="uploading",
            dlspeed=0, upspeed=100, size=1024, completed=1024, ratio=1.0,
            eta=-1, save_path="/s", seeds=5, peers=0,
            files=(TorrentFileInfo(index=0, name="rom.zip", size=1024, progress=1.0, priority=1),),
        )
        controller._on_snapshot([ti])
        assert state.list_queue()[0].status == DownloadStatus.SEEDING.value


# ============================================================================
# _on_connection_changed
# ============================================================================


class TestOnConnectionChanged:
    def test_sets_qbit_state_true(self, controller, app_state):
        controller._on_connection_changed(True)
        assert app_state._qbit_state is True

    def test_sets_qbit_state_false(self, controller, app_state):
        controller._on_connection_changed(False)
        assert app_state._qbit_state is False


# ============================================================================
# _FunctionTask
# ============================================================================


class TestFunctionTask:
    def test_succeeded_signal(self, qtbot):
        task = _FunctionTask(lambda: 42)
        with qtbot.wait_signal(task.signals.succeeded, timeout=1000) as blocker:
            task.run()
        assert blocker.args == [42]

    def test_failed_signal(self, qtbot):
        task = _FunctionTask(lambda: (_ for _ in ()).throw(ValueError("boom")))
        with qtbot.wait_signal(task.signals.failed, timeout=1000) as blocker:
            task.run()
        assert "boom" in blocker.args[0]

    def test_finished_signal(self, qtbot):
        task = _FunctionTask(lambda: None)
        with qtbot.wait_signal(task.signals.finished, timeout=1000):
            task.run()


# ============================================================================
# Async paths made synchronous for coverage
# ============================================================================


@pytest.fixture
def sync_controller(controller, monkeypatch):
    """Run background tasks synchronously so _run_task paths execute in test."""
    def run_sync(operation, succeeded, failed, finished=None):
        task = _FunctionTask(operation)
        task.signals.succeeded.connect(succeeded)
        task.signals.failed.connect(lambda msg: failed(msg))

        def cleanup():
            if finished is not None:
                finished()

        task.signals.finished.connect(cleanup)
        task.run()

    monkeypatch.setattr(controller, "_run_task", run_sync)
    return controller


class TestSubmitTorrentGroup:
    def test_success_adds_hash_and_status(self, sync_controller, state, tmp_path):
        spec = _make_spec(file_id=1, torrent_name="test.torrent")
        sync_controller.file_spec_resolver = lambda fid: spec
        torrent_path = tmp_path / "test.torrent"
        torrent_path.write_text("torrent data")
        spec = DownloadFileSpec(
            file_id=1, torrent_name="test.torrent",
            torrent_path=torrent_path, select_index=1,
            basename="rom.zip", path_in_torrent="rom.zip", size=1024,
            collection="Nintendo", system="NES",
        )
        sync_controller.file_spec_resolver = lambda fid: spec

        client = sync_controller._qbit_template
        client.add_torrent_paused.return_value = "deadbeef"
        client.get_files.return_value = [
            {"index": 0, "name": "rom.zip", "size": 1024},
        ]

        rid = sync_controller.add_to_queue(1, "/dest/rom.zip")
        state.update_queue_record(rid, status=DownloadStatus.QUEUED.value)
        sync_controller._submit_torrent_group("test.torrent")

        rec = state.list_queue()[0]
        assert rec.status == DownloadStatus.DOWNLOADING.value
        assert rec.qbit_hash == "deadbeef"

    def test_missing_torrent_marks_records_failed(self, sync_controller, state):
        spec = _make_spec(file_id=1, torrent_name="missing.torrent")
        sync_controller.file_spec_resolver = lambda fid: spec
        rid = sync_controller.add_to_queue(1, "/dest/rom.zip")
        state.update_queue_record(rid, status=DownloadStatus.QUEUED.value)
        sync_controller._submit_torrent_group("missing.torrent")

        rec = state.list_queue()[0]
        assert rec.status == DownloadStatus.FAILED.value
        assert "Torrent file not found" in (rec.error or "")

    def test_cancelled_record_skipped(self, sync_controller, state):
        spec = _make_spec(file_id=1, torrent_name="test.torrent")
        spec = DownloadFileSpec(
            file_id=1, torrent_name="test.torrent",
            torrent_path=Path("/no/matter.torrent"), select_index=1,
            basename="rom.zip", path_in_torrent="rom.zip", size=1024,
            collection="Nintendo", system="NES",
        )
        sync_controller.file_spec_resolver = lambda fid: spec
        rid = sync_controller.add_to_queue(1, "/dest/rom.zip")
        state.update_queue_record(rid, status=DownloadStatus.CANCELLED.value)
        errors = []
        sync_controller.error.connect(errors.append)
        sync_controller._submit_torrent_group("test.torrent")
        assert errors == []

    def test_resubmit_queued_while_submitting(self, sync_controller, state, tmp_path):
        spec = DownloadFileSpec(
            file_id=1, torrent_name="test.torrent",
            torrent_path=tmp_path / "test.torrent", select_index=1,
            basename="rom.zip", path_in_torrent="rom.zip", size=1024,
            collection="Nintendo", system="NES",
        )
        (tmp_path / "test.torrent").write_text("data")
        sync_controller.file_spec_resolver = lambda fid: spec

        client = sync_controller._qbit_template
        client.add_torrent_paused.return_value = "deadbeef"
        client.get_files.return_value = [{"index": 0, "name": "rom.zip", "size": 1024}]

        rid = sync_controller.add_to_queue(1, "/dest/rom.zip")
        state.update_queue_record(rid, status=DownloadStatus.QUEUED.value)
        sync_controller._submitting_torrents.add("test.torrent")
        sync_controller._resubmit_torrents.add("test.torrent")
        sync_controller._submit_torrent_group("test.torrent")
        assert "test.torrent" not in sync_controller._resubmit_torrents

    def test_operation_no_hash_raises(self, sync_controller, state, tmp_path, qtbot):
        spec = DownloadFileSpec(
            file_id=1, torrent_name="test.torrent",
            torrent_path=tmp_path / "test.torrent", select_index=1,
            basename="rom.zip", path_in_torrent="rom.zip", size=1024,
            collection="Nintendo", system="NES",
        )
        (tmp_path / "test.torrent").write_text("data")
        sync_controller.file_spec_resolver = lambda fid: spec

        client = sync_controller._qbit_template
        client.add_torrent_paused.return_value = ""

        rid = sync_controller.add_to_queue(1, "/dest/rom.zip")
        state.update_queue_record(rid, status=DownloadStatus.QUEUED.value)
        sync_controller._submit_torrent_group("test.torrent")
        assert state.list_queue()[0].status == DownloadStatus.FAILED.value

    def test_operation_missing_indices_raises(self, sync_controller, state, tmp_path):
        spec = DownloadFileSpec(
            file_id=1, torrent_name="test.torrent",
            torrent_path=tmp_path / "test.torrent", select_index=1,
            basename="rom.zip", path_in_torrent="rom.zip", size=1024,
            collection="Nintendo", system="NES",
        )
        (tmp_path / "test.torrent").write_text("data")
        sync_controller.file_spec_resolver = lambda fid: spec

        client = sync_controller._qbit_template
        client.add_torrent_paused.return_value = "deadbeef"
        client.get_files.return_value = [{"index": 99, "name": "rom.zip", "size": 1024}]

        rid = sync_controller.add_to_queue(1, "/dest/rom.zip")
        state.update_queue_record(rid, status=DownloadStatus.QUEUED.value)
        sync_controller._submit_torrent_group("test.torrent")
        assert state.list_queue()[0].status == DownloadStatus.FAILED.value


class TestScheduleCompletedFile:
    def test_hardlink_success(self, sync_controller, state, tmp_path):
        source = tmp_path / "seed" / "rom.zip"
        source.parent.mkdir()
        source.write_bytes(b"x" * 1024)
        dest = tmp_path / "downloads" / "rom.zip"

        spec = DownloadFileSpec(
            file_id=1, torrent_name="test.torrent",
            torrent_path=Path("/tmp/test.torrent"), select_index=1,
            basename="rom.zip", path_in_torrent="rom.zip", size=1024,
            collection="Nintendo", system="NES",
        )
        sync_controller.file_spec_resolver = lambda fid: spec
        rid = sync_controller.add_to_queue(1, str(dest))
        state.update_queue_record(rid, qbit_hash="deadbeef", status=DownloadStatus.DOWNLOADING.value)

        client = sync_controller._qbit_template
        client.get_files.return_value = [{"index": 0, "name": "rom.zip", "size": 1024}]

        ti = TorrentInfo(
            hash="deadbeef", name="test_torrent", progress=1.0,
            state="pausedUP", dlspeed=0, upspeed=0, size=1024,
            completed=1024, ratio=0.0, eta=-1, save_path=str(tmp_path / "seed"),
            seeds=0, peers=0, files=(),
        )
        sync_controller._schedule_completed_file(
            state.list_queue()[0], ti, DownloadStatus.COMPLETED,
        )
        rec = state.list_queue()[0]
        assert rec.status == DownloadStatus.COMPLETED.value
        assert dest.exists()

    def test_copy_fallback(self, sync_controller, state, tmp_path, monkeypatch):
        source = tmp_path / "seed" / "rom.zip"
        source.parent.mkdir()
        source.write_bytes(b"x" * 1024)
        dest = tmp_path / "downloads" / "rom.zip"

        spec = DownloadFileSpec(
            file_id=1, torrent_name="test.torrent",
            torrent_path=Path("/tmp/test.torrent"), select_index=1,
            basename="rom.zip", path_in_torrent="rom.zip", size=1024,
            collection="Nintendo", system="NES",
        )
        sync_controller.file_spec_resolver = lambda fid: spec
        rid = sync_controller.add_to_queue(1, str(dest))
        state.update_queue_record(rid, qbit_hash="deadbeef", status=DownloadStatus.DOWNLOADING.value)

        def failing_link(*args, **kwargs):
            raise OSError("not supported")

        monkeypatch.setattr("os.link", failing_link)

        client = sync_controller._qbit_template
        client.get_files.return_value = [{"index": 0, "name": "rom.zip", "size": 1024}]
        ti = TorrentInfo(
            hash="deadbeef", name="test_torrent", progress=1.0,
            state="pausedUP", dlspeed=0, upspeed=0, size=1024,
            completed=1024, ratio=0.0, eta=-1, save_path=str(tmp_path / "seed"),
            seeds=0, peers=0, files=(),
        )
        sync_controller._schedule_completed_file(
            state.list_queue()[0], ti, DownloadStatus.COMPLETED,
        )
        assert dest.exists()

    def test_same_file_returns_destination(self, sync_controller, state, tmp_path):
        dest = tmp_path / "downloads" / "rom.zip"
        dest.parent.mkdir()
        dest.write_bytes(b"x" * 1024)
        source = dest

        spec = DownloadFileSpec(
            file_id=1, torrent_name="test.torrent",
            torrent_path=Path("/tmp/test.torrent"), select_index=1,
            basename="rom.zip", path_in_torrent="rom.zip", size=1024,
            collection="Nintendo", system="NES",
        )
        sync_controller.file_spec_resolver = lambda fid: spec
        rid = sync_controller.add_to_queue(1, str(dest))
        state.update_queue_record(rid, qbit_hash="deadbeef", status=DownloadStatus.DOWNLOADING.value)

        client = sync_controller._qbit_template
        client.get_files.return_value = [{"index": 0, "name": "rom.zip", "size": 1024}]
        ti = TorrentInfo(
            hash="deadbeef", name="test_torrent", progress=1.0,
            state="pausedUP", dlspeed=0, upspeed=0, size=1024,
            completed=1024, ratio=0.0, eta=-1, save_path=str(tmp_path / "downloads"),
            seeds=0, peers=0, files=(),
        )
        sync_controller._schedule_completed_file(
            state.list_queue()[0], ti, DownloadStatus.COMPLETED,
        )
        assert state.list_queue()[0].status == DownloadStatus.COMPLETED.value

    def test_missing_source_fails(self, sync_controller, state, tmp_path):
        dest = tmp_path / "downloads" / "rom.zip"
        spec = DownloadFileSpec(
            file_id=1, torrent_name="test.torrent",
            torrent_path=Path("/tmp/test.torrent"), select_index=1,
            basename="rom.zip", path_in_torrent="rom.zip", size=1024,
            collection="Nintendo", system="NES",
        )
        sync_controller.file_spec_resolver = lambda fid: spec
        rid = sync_controller.add_to_queue(1, str(dest))
        state.update_queue_record(rid, qbit_hash="deadbeef", status=DownloadStatus.DOWNLOADING.value)

        client = sync_controller._qbit_template
        client.get_files.return_value = [{"index": 0, "name": "rom.zip", "size": 1024}]
        ti = TorrentInfo(
            hash="deadbeef", name="test_torrent", progress=1.0,
            state="pausedUP", dlspeed=0, upspeed=0, size=1024,
            completed=1024, ratio=0.0, eta=-1, save_path=str(tmp_path / "seed"),
            seeds=0, peers=0, files=(),
        )
        sync_controller._schedule_completed_file(
            state.list_queue()[0], ti, DownloadStatus.COMPLETED,
        )
        assert state.list_queue()[0].status == DownloadStatus.FAILED.value

    def test_missing_spec_marks_failed(self, sync_controller, state):
        sync_controller.file_spec_resolver = lambda fid: None
        rid = sync_controller.add_to_queue(1, "/dest/rom.zip")
        state.update_queue_record(rid, qbit_hash="deadbeef", status=DownloadStatus.DOWNLOADING.value)
        ti = TorrentInfo(
            hash="deadbeef", name="t", progress=1.0, state="pausedUP",
            dlspeed=0, upspeed=0, size=100, completed=100, ratio=0.0, eta=-1,
            save_path="/seed", seeds=0, peers=0, files=(),
        )
        sync_controller._schedule_completed_file(
            state.list_queue()[0], ti, DownloadStatus.COMPLETED,
        )
        assert state.list_queue()[0].status == DownloadStatus.FAILED.value

    def test_already_linking_returns(self, sync_controller, state):
        spec = _make_spec(file_id=1)
        sync_controller.file_spec_resolver = lambda fid: spec
        rid = sync_controller.add_to_queue(1, "/dest/rom.zip")
        state.update_queue_record(rid, qbit_hash="deadbeef", status=DownloadStatus.DOWNLOADING.value)
        sync_controller._linking_records.add(rid)
        ti = TorrentInfo(
            hash="deadbeef", name="t", progress=1.0, state="pausedUP",
            dlspeed=0, upspeed=0, size=100, completed=100, ratio=0.0, eta=-1,
            save_path="/seed", seeds=0, peers=0, files=(),
        )
        sync_controller._schedule_completed_file(
            state.list_queue()[0], ti, DownloadStatus.COMPLETED,
        )


class TestQbitLifecycle:
    def test_pause_with_hash(self, sync_controller, state):
        spec = _make_spec(file_id=1)
        sync_controller.file_spec_resolver = lambda fid: spec
        rid = sync_controller.add_to_queue(1, "/dest/rom.zip")
        state.update_queue_record(rid, qbit_hash="deadbeef", status=DownloadStatus.DOWNLOADING.value)
        sync_controller.pause(rid)
        rec = state.list_queue()[0]
        assert rec.status == DownloadStatus.PAUSED.value
        sync_controller._qbit_template.pause.assert_called_once_with("deadbeef")

    def test_resume_with_hash(self, sync_controller, state):
        spec = _make_spec(file_id=1)
        sync_controller.file_spec_resolver = lambda fid: spec
        rid = sync_controller.add_to_queue(1, "/dest/rom.zip")
        state.update_queue_record(rid, qbit_hash="deadbeef", status=DownloadStatus.PAUSED.value)
        sync_controller.resume(rid)
        rec = state.list_queue()[0]
        assert rec.status == DownloadStatus.DOWNLOADING.value
        sync_controller._qbit_template.resume.assert_called_once_with("deadbeef")

    def test_remove_with_hash_deletes_torrent(self, sync_controller, state):
        spec = _make_spec(file_id=1)
        sync_controller.file_spec_resolver = lambda fid: spec
        rid = sync_controller.add_to_queue(1, "/dest/rom.zip")
        state.update_queue_record(rid, qbit_hash="deadbeef", status=DownloadStatus.PAUSED.value)
        sync_controller.remove(rid)
        client = sync_controller._qbit_template
        client.delete_torrent.assert_called_once_with("deadbeef", delete_files=False)
        assert len(state.list_queue()) == 0

    def test_remove_with_hash_and_sibling_deselects_file(self, sync_controller, state):
        spec = _make_spec(file_id=1)
        sync_controller.file_spec_resolver = lambda fid: spec
        rid1 = sync_controller.add_to_queue(1, "/dest/rom.zip")
        rid2 = sync_controller.add_to_queue(2, "/dest/rom2.zip")
        state.update_queue_record(rid1, qbit_hash="deadbeef", status=DownloadStatus.PAUSED.value)
        state.update_queue_record(rid2, qbit_hash="deadbeef", status=DownloadStatus.PAUSED.value)
        sync_controller.remove(rid1)
        client = sync_controller._qbit_template
        client.set_file_priority.assert_called_once_with("deadbeef", [0], 0)
        assert len(state.list_queue()) == 1

    def test_remove_delete_files(self, sync_controller, state, tmp_path):
        spec = _make_spec(file_id=1)
        sync_controller.file_spec_resolver = lambda fid: spec
        dest = tmp_path / "rom.zip"
        dest.write_bytes(b"data")
        rid = sync_controller.add_to_queue(1, str(dest))
        state.update_queue_record(rid, qbit_hash="deadbeef", status=DownloadStatus.PAUSED.value)
        sync_controller.remove(rid, delete_files=True)
        assert not dest.exists()

    def test_pause_all(self, sync_controller, state):
        spec = _make_spec(file_id=1)
        sync_controller.file_spec_resolver = lambda fid: spec
        rid = sync_controller.add_to_queue(1, "/dest/rom.zip")
        state.update_queue_record(rid, qbit_hash="deadbeef", status=DownloadStatus.DOWNLOADING.value)
        sync_controller.pause_all()
        assert state.list_queue()[0].status == DownloadStatus.PAUSED.value

    def test_resume_all(self, sync_controller, state):
        spec = _make_spec(file_id=1)
        sync_controller.file_spec_resolver = lambda fid: spec
        rid = sync_controller.add_to_queue(1, "/dest/rom.zip")
        state.update_queue_record(rid, qbit_hash="deadbeef", status=DownloadStatus.PAUSED.value)
        sync_controller.resume_all()
        assert state.list_queue()[0].status == DownloadStatus.DOWNLOADING.value

