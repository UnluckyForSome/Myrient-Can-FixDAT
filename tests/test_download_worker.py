"""Tests for DownloadWorker — existing-file skip and queue save."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from minerva.app import download_worker as download_worker_module
from minerva.app.download_worker import DownloadWorker


def _make_file(tmp_path, name="rom.zip", collection="Nintendo", system="NES", size=100):
    target_dir = tmp_path / collection / (system or "unknown")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / name
    target_path.write_bytes(b"x" * size)
    return {
        "name": name,
        "basename": name,
        "collection": collection,
        "system": system,
        "size": size,
    }


class TestRunAllFilesExist:
    def test_runs_without_crash(self, tmp_path):
        f = _make_file(tmp_path, size=100)
        worker = DownloadWorker([f], str(tmp_path), use_qbit=False)
        worker.run()
        assert True

    def test_emits_progress(self, qtbot, tmp_path):
        f = _make_file(tmp_path, size=50)
        worker = DownloadWorker([f], str(tmp_path), use_qbit=False)

        progress_calls = []
        worker.progress.connect(lambda *a: progress_calls.append(a))
        worker.run()
        assert any(str(c[2]).startswith("Done") for c in progress_calls)

    def test_emits_file_done(self, qtbot, tmp_path):
        f = _make_file(tmp_path, size=50)
        worker = DownloadWorker([f], str(tmp_path), use_qbit=False)

        done_calls = []
        worker.file_done.connect(lambda *a: done_calls.append(a))
        worker.run()
        assert len(done_calls) == 1
        assert done_calls[0][2] == "rom.zip"

    def test_emits_finished(self, qtbot, tmp_path):
        f = _make_file(tmp_path, size=50)
        worker = DownloadWorker([f], str(tmp_path), use_qbit=False)
        with qtbot.wait_signal(worker.finished, timeout=2000):
            worker.run()


class TestRunPartialExisting:
    def test_nonexistent_file_kept_in_queue(self, tmp_path):
        existing = _make_file(tmp_path, name="have.zip", size=100)
        missing = {
            "name": "missing.zip", "basename": "missing.zip",
            "collection": "Nintendo", "system": "NES", "size": 200,
        }
        worker = DownloadWorker([existing, missing], str(tmp_path), use_qbit=False)
        worker.run()
        assert len(worker._files) == 2


class TestStop:
    def test_stop_sets_flag(self):
        worker = DownloadWorker([], "/tmp", use_qbit=False)
        assert worker._stop is False
        worker.stop()
        assert worker._stop is True


class TestSaveQueue:
    def test_writes_json_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            download_worker_module,
            "SAVED_QUEUE_PATH",
            tmp_path / "queue.json",
        )
        worker = DownloadWorker(
            [{"name": "rom.zip", "collection": "Nintendo"}],
            str(tmp_path),
        )
        worker._save_queue()
        data = json.loads((tmp_path / "queue.json").read_text())
        assert len(data) == 1
        assert data[0]["name"] == "rom.zip"
