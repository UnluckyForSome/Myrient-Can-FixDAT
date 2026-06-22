"""Typed records and columns for the Downloads dashboard."""

from __future__ import annotations

from dataclasses import dataclass

from minerva.domain.downloads import DownloadStatus
from minerva.ui.models.record_model import ColumnSpec, RecordListModel


@dataclass
class DownloadRecord:
    id: int
    queue_id: str
    filename: str
    url: str
    status: DownloadStatus
    file_id: int | None = None
    progress: float = 0.0
    speed: float = 0.0
    upload_speed: float = 0.0
    eta_seconds: float = 0.0
    destination: str = ""
    torrent_name: str = ""
    qbit_hash: str | None = None
    save_path: str = ""
    collection: str = ""
    system: str = ""
    error_message: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    peers: int = 0
    seeds: int = 0
    ratio: float = 0.0
    haystack: str = ""


def format_speed(bytes_per_sec: float) -> str:
    if bytes_per_sec <= 0:
        return "0 B/s"
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    value = float(bytes_per_sec)
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    return f"{value:.1f} {units[index]}" if index else f"{int(value)} {units[index]}"


def format_eta(seconds: float) -> str:
    if seconds <= 0 or seconds >= 8_640_000:
        return "\u2014"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _status_icon(record: DownloadRecord) -> str:
    icons = {
        DownloadStatus.QUEUED: "fa5s.hourglass-half",
        DownloadStatus.STARTING: "fa5s.hourglass-half",
        DownloadStatus.DOWNLOADING: "fa5s.download",
        DownloadStatus.PAUSED: "fa5s.pause",
        DownloadStatus.SEEDING: "fa5s.seedling",
        DownloadStatus.COMPLETED: "fa5s.check",
        DownloadStatus.FAILED: "fa5s.exclamation-triangle",
        DownloadStatus.CANCELLED: "fa5s.times",
    }
    return icons.get(record.status, "fa5s.question")


def _speed_display(record: DownloadRecord) -> str:
    if record.status != DownloadStatus.DOWNLOADING:
        return ""
    return format_speed(record.speed)


_DOWNLOAD_COLUMNS: list[ColumnSpec[DownloadRecord]] = [
    ColumnSpec("", lambda r: _status_icon(r)),
    ColumnSpec("File", lambda r: r.torrent_name or r.filename),
    ColumnSpec("Progress", lambda r: r.progress, format_fn=lambda v: f"{v:.0%}"),
    ColumnSpec("Speed", lambda r: _speed_display(r)),
    ColumnSpec("ETA", lambda r: format_eta(r.eta_seconds)),
    ColumnSpec("Seeds", lambda r: r.seeds, format_fn=lambda v: str(v)),
    ColumnSpec("Ratio", lambda r: r.ratio, format_fn=lambda v: f"{v:.2f}"),
    ColumnSpec("Actions", lambda r: r.status),
]


class DownloadRecordListModel(RecordListModel[DownloadRecord]):
    def record_at(self, row: int) -> DownloadRecord | None:
        return self._records[row] if 0 <= row < len(self._records) else None


# Backward-compatible alias
DownloadTableModel = DownloadRecordListModel
