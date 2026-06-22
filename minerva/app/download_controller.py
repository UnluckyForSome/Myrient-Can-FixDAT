"""Persistent selective-file download orchestration for qBittorrent."""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PyQt6 import QtCore

from minerva.app.app_state import AppState
from minerva.app.qbit_monitor import QbitMonitor
from minerva.domain.downloads import (
    DownloadFileSpec,
    DownloadRuntime,
    DownloadStatus,
    QueueRecord,
    TorrentInfo,
)
from minerva_qbit import QBittorrentClient, QBittorrentError
from minerva_state import MinervaState

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _TaskSignals(QtCore.QObject):
    succeeded = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()


class _FunctionTask(QtCore.QRunnable):
    """Run a callable in QThreadPool and marshal its result to Qt signals."""

    def __init__(self, fn: Callable[[], object]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _TaskSignals()

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            self.signals.succeeded.emit(self.fn())
        except Exception as exc:
            log.exception("Background download operation failed")
            self.signals.failed.emit(str(exc))
        finally:
            self.signals.finished.emit()


class DownloadController(QtCore.QObject):
    """Own the persistent queue, selective torrent priorities and telemetry."""

    queue_changed = QtCore.pyqtSignal()
    runtime_changed = QtCore.pyqtSignal(list)
    activity_event = QtCore.pyqtSignal(str, str)
    error = QtCore.pyqtSignal(str)

    _monitor_hashes_requested = QtCore.pyqtSignal(object)
    _monitor_stop_requested = QtCore.pyqtSignal()

    _ACTIVE_UPLOAD_STATES = {"uploading", "stalledUP", "forcedUP", "queuedUP"}
    _QBT_STATUS_MAP: dict[str, DownloadStatus] = {
        "error": DownloadStatus.FAILED,
        "missingFiles": DownloadStatus.FAILED,
        "pausedDL": DownloadStatus.PAUSED,
        "queuedDL": DownloadStatus.QUEUED,
        "downloading": DownloadStatus.DOWNLOADING,
        "stalledDL": DownloadStatus.DOWNLOADING,
        "forcedDL": DownloadStatus.DOWNLOADING,
        "metaDL": DownloadStatus.STARTING,
        "checkingDL": DownloadStatus.STARTING,
        "checkingUP": DownloadStatus.STARTING,
        "allocating": DownloadStatus.STARTING,
        "checkingResumeData": DownloadStatus.STARTING,
        "moving": DownloadStatus.STARTING,
        "pausedUP": DownloadStatus.COMPLETED,
    }

    def __init__(
        self,
        state: MinervaState,
        app_state: AppState,
        qbit_client: QBittorrentClient,
        seed_dir: str | Path = ".qbitseed",
        allow_copy_fallback: bool = True,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._app_state = app_state
        self._qbit_template = qbit_client
        self._seed_dir = Path(seed_dir).expanduser().resolve()
        self._allow_copy_fallback = allow_copy_fallback
        self._pool = QtCore.QThreadPool.globalInstance()
        self._tasks: set[_FunctionTask] = set()
        self._runtime: dict[str, DownloadRuntime] = {}
        self._spec_cache: dict[int, DownloadFileSpec] = {}
        self._submitting_torrents: set[str] = set()
        self._resubmit_torrents: set[str] = set()
        self._linking_records: set[str] = set()

        self._monitor: QbitMonitor | None = None
        self._monitor_thread: QtCore.QThread | None = None

        self.file_spec_resolver: Callable[[int], DownloadFileSpec | None] | None = None

        # Clear the spec cache when the index is rebuilt so we don't
        # serve stale file metadata (torrent path, qbit index, size)
        # from a previous index generation.
        self._app_state.index_state_changed.connect(self._on_index_changed)

    # ── Queue commands ──────────────────────────────────────────────────

    def add_to_queue(
        self,
        file_id: int,
        destination: str,
        report_entry_id: str | None = None,
    ) -> str:
        destination = str(Path(destination).expanduser())
        for existing in self._state.list_queue():
            if (
                existing.file_id == file_id
                and Path(existing.destination) == Path(destination)
                and existing.status not in {
                    DownloadStatus.CANCELLED.value,
                    DownloadStatus.FAILED.value,
                }
            ):
                return existing.id

        record_id = uuid.uuid4().hex
        now = _now_iso()
        record = QueueRecord(
            id=record_id,
            file_id=file_id,
            report_entry_id=report_entry_id,
            status=DownloadStatus.QUEUED.value,
            destination=destination,
            created_at=now,
            updated_at=now,
        )
        self._state.save_queue_record(record)
        self._state.add_event("download", f"Queued file_id={file_id} \u2192 {destination}")
        self._emit_changed()
        self._schedule_record_submission(record)
        return record_id

    def add_many_to_queue(
        self,
        items: Iterable[tuple[int, str, str | None]],
    ) -> list[str]:
        """Queue several files; same-torrent items are submitted as one job."""
        ids: list[str] = []
        touched_torrents: set[str] = set()
        for file_id, destination, report_entry_id in items:
            record_id = self.add_to_queue(file_id, destination, report_entry_id)
            ids.append(record_id)
            spec = self._resolve_spec(file_id)
            if spec is not None:
                touched_torrents.add(spec.torrent_name)
        for torrent_name in touched_torrents:
            self._schedule_torrent_submission(torrent_name)
        return ids

    def pause(self, record_id: str) -> None:
        record = self._get_record(record_id)
        if record is None:
            return
        if not record.qbit_hash:
            self._update_group_status([record], DownloadStatus.PAUSED)
            return
        group = self._records_for_hash(record.qbit_hash)
        self._run_qbit_task(
            lambda: self._logged_in_clone().pause(record.qbit_hash or ""),
            lambda _result: self._update_group_status(group, DownloadStatus.PAUSED),
            "Pause failed",
        )

    def resume(self, record_id: str) -> None:
        record = self._get_record(record_id)
        if record is None:
            return
        if not record.qbit_hash:
            self._state.update_queue_record(
                record.id, status=DownloadStatus.QUEUED.value, error=None,
            )
            self._emit_changed()
            self._schedule_record_submission(record)
            return
        group = self._records_for_hash(record.qbit_hash)
        self._run_qbit_task(
            lambda: self._logged_in_clone().resume(record.qbit_hash or ""),
            lambda _result: self._update_group_status(group, DownloadStatus.DOWNLOADING),
            "Resume failed",
        )

    def retry(self, record_id: str) -> None:
        record = self._get_record(record_id)
        if record is None:
            return
        self._state.update_queue_record(
            record.id,
            status=DownloadStatus.QUEUED.value,
            error=None,
            qbit_hash=None,
        )
        self._emit_changed()
        self._schedule_record_submission(record)

    def pause_all(self) -> None:
        for torrent_hash in {r.qbit_hash for r in self.get_active_records() if r.qbit_hash}:
            record = next(r for r in self.get_active_records() if r.qbit_hash == torrent_hash)
            self.pause(record.id)

    def resume_all(self) -> None:
        for record in self.get_queue():
            if record.status in {DownloadStatus.PAUSED.value, DownloadStatus.QUEUED.value}:
                self.resume(record.id)

    def remove(self, record_id: str, delete_files: bool = False) -> None:
        record = self._get_record(record_id)
        if record is None:
            return
        spec = self._resolve_spec(record.file_id)
        siblings = [
            r for r in self._state.list_queue()
            if r.id != record.id and r.qbit_hash and r.qbit_hash == record.qbit_hash
        ]

        if record.qbit_hash:
            torrent_hash = record.qbit_hash
            if siblings and spec is not None:
                self._run_qbit_task(
                    lambda: self._logged_in_clone().set_file_priority(
                        torrent_hash, [spec.qbit_file_index], 0,
                    ),
                    lambda _result: None,
                    "Could not deselect torrent file",
                )
            elif not siblings:
                self._run_qbit_task(
                    lambda: self._logged_in_clone().delete_torrent(
                        torrent_hash, delete_files=delete_files,
                    ),
                    lambda _result: None,
                    "Could not remove torrent",
                )

        if delete_files and record.destination:
            dest = Path(record.destination)
            if dest.is_file():
                try:
                    dest.unlink()
                except OSError as exc:
                    self.error.emit(f"Could not remove {dest}: {exc}")

        self._state.delete_queue_record(record.id)
        self._runtime.pop(record.id, None)
        self._state.add_event("download", f"Removed {record.id[:8]} from queue")
        self._sync_monitor_hashes()
        self._emit_changed()
        self._emit_runtime()

    def remove_many(self, record_ids: Iterable[str], delete_files: bool = False) -> None:
        for record_id in list(record_ids):
            self.remove(record_id, delete_files=delete_files)

    # ── Queries ──────────────────────────────────────────────────────────

    def get_queue(self) -> list[QueueRecord]:
        return self._state.list_queue()

    def get_runtime(self) -> list[DownloadRuntime]:
        return list(self._runtime.values())

    def get_runtime_for(self, record_id: str) -> DownloadRuntime | None:
        return self._runtime.get(record_id)

    def get_active_records(self) -> list[QueueRecord]:
        active = {
            DownloadStatus.QUEUED.value,
            DownloadStatus.STARTING.value,
            DownloadStatus.DOWNLOADING.value,
            DownloadStatus.PAUSED.value,
            DownloadStatus.SEEDING.value,
        }
        return [r for r in self._state.list_queue() if r.status in active]

    def has_active_downloads(self) -> bool:
        return any(
            r.status in {
                DownloadStatus.STARTING.value,
                DownloadStatus.DOWNLOADING.value,
                DownloadStatus.QUEUED.value,
            }
            for r in self._state.list_queue()
        )

    # ── Monitoring lifecycle ─────────────────────────────────────────────

    def start_monitoring(self) -> None:
        if self._monitor_thread is not None:
            self._sync_monitor_hashes()
            return
        thread = QtCore.QThread(self)
        monitor = QbitMonitor(self._qbit_template.clone())
        monitor.moveToThread(thread)
        thread.started.connect(monitor.start)
        monitor.snapshot_ready.connect(self._on_snapshot)
        monitor.connection_changed.connect(self._on_connection_changed)
        monitor.error.connect(self.error.emit)
        self._monitor_hashes_requested.connect(
            monitor.set_tracked_hashes,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )
        self._monitor_stop_requested.connect(
            monitor.stop,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )
        monitor.stopped.connect(thread.quit)
        thread.finished.connect(monitor.deleteLater)
        thread.start()
        self._monitor = monitor
        self._monitor_thread = thread
        self._sync_monitor_hashes()

    def stop_monitoring(self, timeout_ms: int = 5000) -> None:
        if self._monitor_thread is None:
            return
        if self._monitor is not None and self._monitor_thread.isRunning():
            QtCore.QMetaObject.invokeMethod(
                self._monitor,
                "stop",
                QtCore.Qt.ConnectionType.BlockingQueuedConnection,
            )
        self._monitor_thread.quit()
        if not self._monitor_thread.wait(timeout_ms):
            self._monitor_thread.terminate()
            self._monitor_thread.wait(1000)
        self._monitor_thread.deleteLater()
        self._monitor_thread = None
        self._monitor = None

    def reconcile(self) -> None:
        for record in self._state.list_queue():
            if record.status == DownloadStatus.QUEUED.value and not record.qbit_hash:
                self._schedule_record_submission(record)
        self._sync_monitor_hashes()

    # ── Snapshot reconciliation ──────────────────────────────────────────

    @QtCore.pyqtSlot(list)
    def _on_snapshot(self, torrents: list[TorrentInfo]) -> None:
        records_by_hash: dict[str, list[QueueRecord]] = defaultdict(list)
        for record in self._state.list_queue():
            if record.qbit_hash:
                records_by_hash[record.qbit_hash].append(record)

        changed = False
        total_speed = 0
        for ti in torrents:
            group = records_by_hash.get(ti.hash, [])
            total_speed += ti.dlspeed
            for record in group:
                spec = self._resolve_spec(record.file_id)
                file_snapshot = None
                if spec is not None:
                    file_snapshot = next(
                        (item for item in ti.files if item.index == spec.qbit_file_index),
                        None,
                    )
                file_progress = file_snapshot.progress if file_snapshot is not None else ti.progress
                self._runtime[record.id] = DownloadRuntime(
                    record_id=record.id,
                    qbit_hash=ti.hash,
                    torrent_name=ti.name,
                    progress=file_progress,
                    download_speed=ti.dlspeed,
                    upload_speed=ti.upspeed,
                    eta=ti.eta,
                    peers=ti.peers,
                    seeds=ti.seeds,
                    ratio=ti.ratio,
                    save_path=ti.save_path,
                    raw_state=ti.state,
                )
                new_status = self._map_qbit_state(ti.state, file_progress)
                if new_status in {DownloadStatus.COMPLETED, DownloadStatus.SEEDING}:
                    if record.status not in {
                        DownloadStatus.COMPLETED.value,
                        DownloadStatus.SEEDING.value,
                    }:
                        self._schedule_completed_file(record, ti, new_status)
                    elif record.status != new_status.value:
                        self._state.update_queue_record(record.id, status=new_status.value)
                        changed = True
                elif record.status != new_status.value:
                    self._state.update_queue_record(record.id, status=new_status.value)
                    changed = True

        self._emit_runtime()
        if total_speed:
            self.activity_event.emit("download-speed", str(total_speed))
        if changed:
            self._emit_changed()

    def _on_connection_changed(self, connected: bool) -> None:
        self._app_state.qbit_state = connected
        if connected:
            self.reconcile()

    # ── Selective torrent submission ─────────────────────────────────────

    def _schedule_record_submission(self, record: QueueRecord) -> None:
        spec = self._resolve_spec(record.file_id)
        if spec is None:
            self._state.update_queue_record(
                record.id,
                status=DownloadStatus.FAILED.value,
                error=f"Index file {record.file_id} no longer exists",
            )
            self._emit_changed()
            return
        self._schedule_torrent_submission(spec.torrent_name)

    def _schedule_torrent_submission(self, torrent_name: str) -> None:
        if torrent_name in self._submitting_torrents:
            self._resubmit_torrents.add(torrent_name)
            return
        self._submitting_torrents.add(torrent_name)
        QtCore.QTimer.singleShot(0, lambda name=torrent_name: self._submit_torrent_group(name))

    def _submit_torrent_group(self, torrent_name: str) -> None:
        group: list[tuple[QueueRecord, DownloadFileSpec]] = []
        for record in self._state.list_queue():
            if record.status == DownloadStatus.CANCELLED.value:
                continue
            spec = self._resolve_spec(record.file_id)
            if spec is not None and spec.torrent_name == torrent_name:
                group.append((record, spec))
        if not group:
            return
        torrent_path = group[0][1].torrent_path
        if not torrent_path.is_file():
            message = f"Torrent file not found: {torrent_path}"
            for record, _spec in group:
                self._state.update_queue_record(
                    record.id, status=DownloadStatus.FAILED.value, error=message,
                )
            self.error.emit(message)
            self._emit_changed()
            return

        existing_hash = next((r.qbit_hash for r, _ in group if r.qbit_hash), None)
        target_indices = sorted({spec.qbit_file_index for _record, spec in group})
        group_ids = [
            record.id for record, _spec in group
            if record.status in {
                DownloadStatus.QUEUED.value,
                DownloadStatus.STARTING.value,
                DownloadStatus.DOWNLOADING.value,
                DownloadStatus.PAUSED.value,
            }
        ]
        if not group_ids:
            return
        for record, _spec in group:
            if record.id in group_ids and record.status != DownloadStatus.PAUSED.value:
                self._state.update_queue_record(
                    record.id, status=DownloadStatus.STARTING.value, error=None,
                )
        self._emit_changed()
        self._seed_dir.mkdir(parents=True, exist_ok=True)

        def operation() -> dict[str, object]:
            client = self._logged_in_clone()
            torrent_hash = existing_hash or client.add_torrent_paused(
                str(torrent_path), str(self._seed_dir),
            )
            if not torrent_hash:
                raise QBittorrentError("qBittorrent accepted the torrent but no hash was found")
            files = client.get_files(torrent_hash)
            available = {int(item.get("index", -1)) for item in files}
            missing = [idx for idx in target_indices if idx not in available]
            if missing:
                raise QBittorrentError(
                    f"Torrent file indices not found: {', '.join(map(str, missing))}"
                )
            all_indices = sorted(idx for idx in available if idx >= 0)
            client.set_file_priority(torrent_hash, all_indices, 0)
            client.set_file_priority(torrent_hash, target_indices, 1)
            try:
                client.resume(torrent_hash)
            except Exception as exc:
                log.warning("Could not resume torrent (user may need to resume manually): %s", exc)
            return {"hash": torrent_hash, "record_ids": group_ids}

        def succeeded(result: object) -> None:
            payload = dict(result)
            torrent_hash = str(payload["hash"])
            for record_id in payload["record_ids"]:
                current = self._get_record(str(record_id))
                if current is None or current.status in {
                    DownloadStatus.CANCELLED.value,
                    DownloadStatus.COMPLETED.value,
                    DownloadStatus.SEEDING.value,
                    DownloadStatus.FAILED.value,
                }:
                    continue
                self._state.update_queue_record(
                    current.id,
                    status=DownloadStatus.DOWNLOADING.value,
                    qbit_hash=torrent_hash,
                    error=None,
                )
            self._state.add_event(
                "download",
                f"Started {len(group_ids)} selected file(s) from {torrent_name}",
            )
            self._sync_monitor_hashes()
            self._emit_changed()

        def failed(message: str) -> None:
            for record_id in group_ids:
                current = self._get_record(record_id)
                if current is not None and current.status == DownloadStatus.STARTING.value:
                    self._state.update_queue_record(
                        current.id,
                        status=DownloadStatus.FAILED.value,
                        error=message,
                    )
            self.error.emit(f"Could not start {torrent_name}: {message}")
            self._emit_changed()

        def finished() -> None:
            self._submitting_torrents.discard(torrent_name)
            if torrent_name in self._resubmit_torrents:
                self._resubmit_torrents.discard(torrent_name)
                self._schedule_torrent_submission(torrent_name)

        self._run_task(operation, succeeded, failed, finished)

    # ── Completion / exposure ────────────────────────────────────────────

    def _schedule_completed_file(
        self,
        record: QueueRecord,
        torrent: TorrentInfo,
        final_status: DownloadStatus,
    ) -> None:
        if record.id in self._linking_records:
            return
        spec = self._resolve_spec(record.file_id)
        if spec is None:
            self._state.update_queue_record(
                record.id,
                status=DownloadStatus.FAILED.value,
                error="Index metadata disappeared before completion",
            )
            self._emit_changed()
            return
        self._linking_records.add(record.id)

        def operation() -> Path:
            client = self._logged_in_clone()
            files = client.get_files(torrent.hash)
            remote = next(
                (item for item in files if int(item.get("index", -1)) == spec.qbit_file_index),
                None,
            )
            if remote is None:
                raise FileNotFoundError(
                    f"qBittorrent file index {spec.qbit_file_index} is missing"
                )
            remote_name = str(remote.get("name", ""))
            save_path = Path(torrent.save_path)
            candidates = [
                save_path / remote_name,
                save_path / torrent.name / spec.path_in_torrent,
                save_path / spec.path_in_torrent,
            ]
            source = next((p for p in candidates if p.is_file()), None)
            if source is None:
                for candidate in save_path.rglob(spec.basename):
                    if candidate.is_file() and candidate.stat().st_size == spec.size:
                        source = candidate
                        break
            if source is None:
                raise FileNotFoundError(
                    f"Downloaded file not found for {spec.path_in_torrent}"
                )
            actual_size = source.stat().st_size
            if spec.size > 0 and actual_size != spec.size:
                raise OSError(
                    f"Downloaded size mismatch: expected {spec.size}, got {actual_size}"
                )

            destination = Path(record.destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                try:
                    if destination.samefile(source):
                        return destination
                except OSError:
                    pass
                raise FileExistsError(
                    f"Destination already exists and is not the downloaded file: {destination}"
                )
            try:
                os.link(source, destination)
            except OSError:
                if not self._allow_copy_fallback:
                    raise
                shutil.copy2(source, destination)
            if spec.size > 0 and destination.stat().st_size != spec.size:
                destination.unlink(missing_ok=True)
                raise OSError("Destination verification failed after exposure")
            return destination

        def succeeded(result: object) -> None:
            destination = Path(result)
            self._state.update_queue_record(
                record.id,
                status=final_status.value,
                error=None,
            )
            self._state.add_event("hardlink", f"Ready: {destination}")
            self.activity_event.emit("check", f"Completed {destination.name}")
            self._emit_changed()

        def failed(message: str) -> None:
            self._state.update_queue_record(
                record.id,
                status=DownloadStatus.FAILED.value,
                error=message,
            )
            self._state.add_event("error", f"Exposure failed: {message}")
            self.error.emit(message)
            self._emit_changed()

        def finished() -> None:
            self._linking_records.discard(record.id)

        self._run_task(operation, succeeded, failed, finished)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _resolve_spec(self, file_id: int) -> DownloadFileSpec | None:
        if file_id in self._spec_cache:
            return self._spec_cache[file_id]
        if self.file_spec_resolver is None:
            return None
        spec = self.file_spec_resolver(file_id)
        if spec is not None:
            self._spec_cache[file_id] = spec
        return spec

    def _on_index_changed(self, _state: object) -> None:
        """Drop the spec cache when the index is rebuilt."""
        self._spec_cache.clear()

    def _logged_in_clone(self) -> QBittorrentClient:
        client = self._qbit_template.clone()
        client.login()
        return client

    def _records_for_hash(self, torrent_hash: str) -> list[QueueRecord]:
        return [r for r in self._state.list_queue() if r.qbit_hash == torrent_hash]

    def _get_record(self, record_id: str) -> QueueRecord | None:
        return next((r for r in self._state.list_queue() if r.id == record_id), None)

    def _update_group_status(
        self,
        records: Iterable[QueueRecord],
        status: DownloadStatus,
    ) -> None:
        changed = False
        for record in records:
            current = self._get_record(record.id)
            if current is not None:
                self._state.update_queue_record(current.id, status=status.value)
                changed = True
        if changed:
            self._emit_changed()

    def _sync_monitor_hashes(self) -> None:
        hashes = {
            r.qbit_hash for r in self.get_active_records()
            if r.qbit_hash
        }
        self._monitor_hashes_requested.emit(hashes)

    def _emit_changed(self) -> None:
        self.queue_changed.emit()
        self._app_state.queue_changed.emit()

    def _emit_runtime(self) -> None:
        self.runtime_changed.emit(self.get_runtime())

    @classmethod
    def _map_qbit_state(cls, raw_state: str, progress: float) -> DownloadStatus:
        if progress >= 1.0:
            if raw_state in cls._ACTIVE_UPLOAD_STATES:
                return DownloadStatus.SEEDING
            return DownloadStatus.COMPLETED
        return cls._QBT_STATUS_MAP.get(raw_state, DownloadStatus.DOWNLOADING)

    def _run_qbit_task(
        self,
        operation: Callable[[], object],
        succeeded: Callable[[object], None],
        error_prefix: str,
    ) -> None:
        self._run_task(
            operation,
            succeeded,
            lambda message: self.error.emit(f"{error_prefix}: {message}"),
        )

    def _run_task(
        self,
        operation: Callable[[], object],
        succeeded: Callable[[object], None],
        failed: Callable[[str], None],
        finished: Callable[[], None] | None = None,
    ) -> None:
        task = _FunctionTask(operation)
        self._tasks.add(task)
        task.signals.succeeded.connect(succeeded)
        task.signals.failed.connect(failed)

        def cleanup() -> None:
            if finished is not None:
                finished()
            self._tasks.discard(task)

        task.signals.finished.connect(cleanup)
        self._pool.start(task)
