"""
Acquisition Planner — produce a concrete plan from a report + constraints.

The planner does NOT mutate state — it only computes.  It produces an
``AcquisitionPlan`` with per-volume estimates, selected files, and deferred
files.  The caller (``ReportAcquisitionService.queue_plan``) consumes the
plan to atomically enqueue the selected files.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from minerva.domain.downloads import DownloadStatus
from minerva.domain.reports import (
    AcquisitionConstraints,
    AcquisitionPlan,
    DeferredFile,
    PlannedFile,
    ResolutionState,
    SelectionStrategy,
    VolumeEstimate,
)
from minerva_state import MinervaState
from minerva.services.report_acquisition import _romm_destination

log = logging.getLogger(__name__)

_ACTIVE_STATUSES = frozenset({
    DownloadStatus.QUEUED.value,
    DownloadStatus.STARTING.value,
    DownloadStatus.DOWNLOADING.value,
    DownloadStatus.PAUSED.value,
})

__all__: list[str] = [
    "SelectionStrategy",
    "AcquisitionConstraints",
    "PlannedFile",
    "DeferredFile",
    "VolumeEstimate",
    "AcquisitionPlan",
    "AcquisitionPlanner",
]


class AcquisitionPlanner:
    """Produce a concrete ``AcquisitionPlan`` from a report + constraints.

    Pure computation — does NOT mutate state.  The caller consumes the
    plan via ``queue_plan`` on ``ReportAcquisitionService``.
    """

    def __init__(
        self,
        *,
        state: MinervaState,
        settings: dict[str, Any] | None = None,
        db: "MinervaDB | None" = None,
    ) -> None:
        self._state = state
        self._settings = settings or {}
        self._db = db

    # ── Public API ──────────────────────────────────────────────────────────

    def build_plan(
        self,
        report_id: str,
        constraints: AcquisitionConstraints,
    ) -> AcquisitionPlan:
        """Build a full acquisition plan for *report_id*.

        The plan includes:
        - Volume estimates for seed and output filesystems
        - Selected files (fits within constraints + budget)
        - Deferred files (excluded for a known reason)
        """
        seed_dir, output_dir = self._resolve_dirs()
        seed_vol, output_vol = self._probe_volume(seed_dir, output_dir)
        same_fs = self._same_filesystem(seed_dir, output_dir)
        hardlink_ok = self._test_hardlink(seed_dir, output_dir)
        committed = self._committed_bytes(seed_dir, output_dir)

        entries = self._state.get_entries(report_id)
        candidates = self._collect_candidates(entries, constraints)

        # Sort by strategy
        candidates = self._sort_candidates(candidates, constraints.strategy)

        selected: list[PlannedFile] = []
        deferred: list[DeferredFile] = []

        # Compute budgets per filesystem
        seed_budget, output_budget = self._compute_budgets(
            seed_vol, output_vol, committed, constraints, same_fs, hardlink_ok,
        )

        seed_remaining = seed_budget
        output_remaining = output_budget
        selected_bytes = 0
        estimated_transfer = 0

        for entry, file_id, size, torrent_name, dest in candidates:
            # Size limit constraint
            if constraints.max_file_bytes is not None and size > constraints.max_file_bytes:
                deferred.append(DeferredFile(
                    report_entry_id=entry.id,
                    file_id=file_id,
                    size=size,
                    reason=f"exceeds {_fmt_bytes(constraints.max_file_bytes)} limit",
                ))
                continue

            # Check budgets
            if same_fs and hardlink_ok:
                if size > seed_remaining:
                    deferred.append(DeferredFile(
                        report_entry_id=entry.id,
                        file_id=file_id,
                        size=size,
                        reason="exceeds remaining budget",
                    ))
                    continue
                seed_remaining -= size
            elif same_fs and not hardlink_ok:
                if size > output_remaining:
                    deferred.append(DeferredFile(
                        report_entry_id=entry.id,
                        file_id=file_id,
                        size=size,
                        reason="exceeds remaining budget",
                    ))
                    continue
                output_remaining -= size
            else:
                if size > seed_remaining or size > output_remaining:
                    deferred.append(DeferredFile(
                        report_entry_id=entry.id,
                        file_id=file_id,
                        size=size,
                        reason="exceeds remaining budget",
                    ))
                    continue
                seed_remaining -= size
                output_remaining -= size

            # Check max file count
            if constraints.max_file_count is not None and len(selected) >= constraints.max_file_count:
                deferred.append(DeferredFile(
                    report_entry_id=entry.id,
                    file_id=file_id,
                    size=size,
                    reason="exceeds max file count",
                ))
                continue

            pf = PlannedFile(
                report_entry_id=entry.id,
                file_id=file_id,
                size=size,
                torrent_name=torrent_name,
                destination=dest,
            )
            selected.append(pf)
            selected_bytes += size
            if same_fs and not hardlink_ok:
                estimated_transfer += size
            elif not same_fs:
                estimated_transfer += size * 2
            else:
                estimated_transfer += size

        volumes = self._build_volumes(
            seed_dir, output_dir, seed_vol, output_vol, committed,
            seed_budget - seed_remaining,
            output_budget - output_remaining,
            constraints,
        )

        report = self._state.get_report(report_id)
        return AcquisitionPlan(
            selected=tuple(selected),
            deferred=tuple(deferred),
            volumes=tuple(volumes),
            selected_bytes=selected_bytes,
            estimated_transfer_bytes=estimated_transfer,
            report_id=report_id,
            report_name=report.name if report else "",
        )

    def explain_deferrals(self, plan: AcquisitionPlan) -> dict[str, int]:
        """Group deferral reasons into a human-readable summary."""
        counts: dict[str, int] = {}
        for d in plan.deferred:
            counts[d.reason] = counts.get(d.reason, 0) + 1
        return counts

    # ── Volume probing ──────────────────────────────────────────────────────

    def _resolve_dirs(self) -> tuple[Path, Path]:
        """Return (seed_dir, output_dir) from settings or defaults."""
        seed = Path(self._settings.get("qbit/save_path", ".qbitseed")).expanduser().resolve()
        output = Path(self._settings.get("downloads/output_dir", "downloads")).expanduser().resolve()
        return seed, output

    def _probe_volume(
        self,
        seed_dir: Path,
        output_dir: Path,
    ) -> tuple[shutil._ntuple_diskusage, shutil._ntuple_diskusage]:
        """Probe disk usage for both directories."""
        seed_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        seed_usage = shutil.disk_usage(seed_dir)
        output_usage = shutil.disk_usage(output_dir)
        return seed_usage, output_usage

    @staticmethod
    def _same_filesystem(path_a: Path, path_b: Path) -> bool:
        """Check whether two paths are on the same filesystem."""
        try:
            return os.stat(path_a).st_dev == os.stat(path_b).st_dev
        except OSError:
            return False

    @staticmethod
    def _test_hardlink(seed_dir: Path, output_dir: Path) -> bool:
        """Test whether hardlinks work between seed and output dirs."""
        src = dst = None
        try:
            src = Path(tempfile.mkstemp(dir=str(seed_dir))[1])
            dst = output_dir / src.name
            os.link(str(src), str(dst))
            return True
        except OSError:
            return False
        finally:
            for p in (src, dst):
                if p is not None and p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass

    def _committed_bytes(
        self,
        seed_dir: Path,
        output_dir: Path,
    ) -> dict[str, int]:
        """Return committed bytes per filesystem path."""
        from minerva_db import MinervaDB

        db = self._db or MinervaDB()
        committed: dict[str, int] = {}
        for record in self._state.list_queue():
            if record.status not in _ACTIVE_STATUSES:
                continue
            items = db.get_files_by_ids([record.file_id])
            if not items:
                continue
            size = items[0].size
            dest = Path(record.destination)
            try:
                dev = os.stat(dest.parent if dest.parent.exists() else dest).st_dev
            except OSError:
                dev = id(dest.parent)
            key = str(dev)
            committed[key] = committed.get(key, 0) + size

        result: dict[str, int] = {}
        try:
            seed_dev = os.stat(seed_dir).st_dev
            result[str(seed_dev)] = committed.get(str(seed_dev), 0)
        except OSError:
            pass
        try:
            output_dev = os.stat(output_dir).st_dev
            result[str(output_dev)] = committed.get(str(output_dev), 0)
        except OSError:
            pass
        return result

    # ── Candidate collection ────────────────────────────────────────────────

    def _collect_candidates(
        self,
        entries: list,
        constraints: AcquisitionConstraints,
    ) -> list[tuple]:
        """Collect candidate entries matching constraints.

        Returns list of (entry, file_id, size, torrent_name, destination).
        """
        from minerva_db import MinervaDB

        db = self._db or MinervaDB()
        seed_dir, output_dir = self._resolve_dirs()
        candidates: list[tuple] = []

        queue_records = self._state.list_queue()
        queued_file_ids: set[int] = set()
        completed_file_ids: set[int] = set()
        for rec in queue_records:
            if rec.status in {"completed", "seeding"}:
                completed_file_ids.add(rec.file_id)
            elif rec.status in _ACTIVE_STATUSES:
                queued_file_ids.add(rec.file_id)

        for entry in entries:
            if entry.resolution == ResolutionState.NOT_FOUND:
                continue
            if entry.resolution == ResolutionState.READY and not constraints.include_automatic_matches:
                continue
            if entry.resolution == ResolutionState.REVIEW_REQUIRED:
                if not constraints.include_reviewed_matches:
                    continue
                if entry.decision not in {"accept", "fuzzy", "approved"}:
                    continue

            file_id = entry.selected_file_id or entry.automatic_file_id
            if file_id is None:
                continue

            if file_id in queued_file_ids:
                continue
            if file_id in completed_file_ids:
                continue

            items = db.get_files_by_ids([file_id])
            if not items:
                continue
            item = items[0]
            size = item.size

            if constraints.collections and item.collection not in constraints.collections:
                continue
            if constraints.systems and item.system not in constraints.systems:
                continue
            if constraints.regions and not (set(item.regions) & constraints.regions):
                continue
            if constraints.extensions:
                ext = Path(item.basename).suffix.lower()
                if ext not in constraints.extensions:
                    continue

            if constraints.require_seeded_source:
                torrent_path = (
                    Path(self._settings.get("torrent_dir", "torrents"))
                    / item.source_torrent
                )
                if not torrent_path.is_file():
                    continue

            destination = _romm_destination(output_dir, item.system, item.basename)
            candidates.append((entry, file_id, size, item.source_torrent, destination))

        return candidates

    @staticmethod
    def _sort_candidates(
        candidates: list[tuple],
        strategy: SelectionStrategy,
    ) -> list[tuple]:
        """Sort candidates by the given selection strategy."""
        if strategy == SelectionStrategy.SMALLEST_FIRST:
            candidates.sort(key=lambda c: c[2])
        elif strategy == SelectionStrategy.LARGEST_FIRST:
            candidates.sort(key=lambda c: -c[2])
        elif strategy == SelectionStrategy.CONFIDENCE_FIRST:
            candidates.sort(key=lambda c: -(c[0].automatic_confidence or 0))
        elif strategy == SelectionStrategy.AVAILABILITY_FIRST:
            candidates.sort(key=lambda c: c[2])
        # REPORT_ORDER — keep original
        return candidates

    # ── Budget computation ──────────────────────────────────────────────────

    @staticmethod
    def _compute_budgets(
        seed_vol: shutil._ntuple_diskusage,
        output_vol: shutil._ntuple_diskusage,
        committed: dict[str, int],
        constraints: AcquisitionConstraints,
        same_fs: bool,
        hardlink_ok: bool,
    ) -> tuple[int, int]:
        """Compute usable budgets for seed and output volumes.

        Returns (seed_budget, output_budget) in bytes.
        """
        if same_fs:
            total_available = seed_vol.free
            reserve = max(
                constraints.reserve_free_bytes,
                int(total_available * 0.05),
            )
            max_total = constraints.max_total_bytes or total_available
            committed_seed = committed.get(str(seed_vol.free), 0)
            budget = min(max_total, total_available - reserve - committed_seed)
            return (budget, budget) if hardlink_ok else (total_available, budget)

        seed_committed = committed.get(str(seed_vol.free), 0)
        output_committed = committed.get(str(output_vol.free), 0)
        seed_reserve = max(
            constraints.reserve_free_bytes,
            int(seed_vol.free * 0.05),
        )
        output_reserve = max(
            constraints.reserve_free_bytes,
            int(output_vol.free * 0.05),
        )
        seed_budget = seed_vol.free - seed_reserve - seed_committed
        output_budget = output_vol.free - output_reserve - output_committed
        if constraints.max_total_bytes is not None:
            seed_budget = min(seed_budget, constraints.max_total_bytes)
            output_budget = min(output_budget, constraints.max_total_bytes)
        return seed_budget, output_budget

    @staticmethod
    def _build_volumes(
        seed_dir: Path,
        output_dir: Path,
        seed_vol: shutil._ntuple_diskusage,
        output_vol: shutil._ntuple_diskusage,
        committed: dict[str, int],
        used_seed: int,
        used_output: int,
        constraints: AcquisitionConstraints,
    ) -> list[VolumeEstimate]:
        """Build per-volume estimates."""
        vols: list[VolumeEstimate] = []

        seed_used = committed.get(str(seed_vol.free), 0) + used_seed
        seed_fits = seed_used <= seed_vol.free - constraints.reserve_free_bytes
        vols.append(VolumeEstimate(
            path=seed_dir,
            available_bytes=seed_vol.free,
            committed_bytes=committed.get(str(seed_vol.free), 0),
            newly_required_bytes=used_seed,
            reserve_bytes=constraints.reserve_free_bytes,
            fits=seed_fits,
        ))

        output_used = committed.get(str(output_vol.free), 0) + used_output
        output_fits = output_used <= output_vol.free - constraints.reserve_free_bytes
        vols.append(VolumeEstimate(
            path=output_dir,
            available_bytes=output_vol.free,
            committed_bytes=committed.get(str(output_vol.free), 0),
            newly_required_bytes=used_output,
            reserve_bytes=constraints.reserve_free_bytes,
            fits=output_fits,
        ))

        return vols


def _fmt_bytes(n: int) -> str:
    """Format byte count to a human-readable string."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            return f"{int(n)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{n} TB"
