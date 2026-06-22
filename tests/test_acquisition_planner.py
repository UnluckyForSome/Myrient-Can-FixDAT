"""Tests for AcquisitionPlanner — pure computation, volume/budget logic."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from minerva.domain.downloads import DownloadStatus, QueueRecord
from minerva.domain.library import LibraryItem
from minerva.domain.reports import (
    AcquisitionConstraints,
    ResolutionState,
    ReviewEntry,
    SelectionStrategy,
)
from minerva.services.acquisition_planner import AcquisitionPlanner, _fmt_bytes
from minerva_state import MinervaState


# ============================================================================
# Helpers
# ============================================================================


def _make_entry(
    entry_id: str = "e1",
    report_id: str = "r1",
    resolution: ResolutionState = ResolutionState.READY,
    automatic_file_id: int | None = 1,
    selected_file_id: int | None = None,
    confidence: float | None = 0.9,
    decision: str = "accept",
) -> ReviewEntry:
    return ReviewEntry(
        id=entry_id,
        report_id=report_id,
        ordinal=0,
        filename="rom.zip",
        size=100,
        automatic_file_id=automatic_file_id,
        automatic_method="exact",
        automatic_confidence=confidence,
        decision=decision,
        selected_file_id=selected_file_id,
        resolution=resolution,
    )


def _make_item(
    file_id: int = 1,
    size: int = 100,
    collection: str = "Nintendo",
    system: str = "NES",
    basename: str = "rom.zip",
    regions: tuple[str, ...] = ("USA",),
    source_torrent: str = "test.torrent",
) -> LibraryItem:
    return LibraryItem(
        id=file_id, stem="rom", basename=basename, collection=collection,
        system=system, size=size, source_torrent=source_torrent,
        source_index=1, path_in_torrent=basename, tags=(), regions=regions,
    )


# ============================================================================
# Formatting
# ============================================================================


class TestFmtBytes:
    def test_bytes(self):
        assert "B" in _fmt_bytes(100)

    def test_kilobytes(self):
        assert "KB" in _fmt_bytes(1024)

    def test_megabytes(self):
        assert "MB" in _fmt_bytes(1024 * 1024)
    

# ============================================================================
# Static helpers
# ============================================================================


class TestStaticHelpers:
    def test_same_filesystem_same_tmp(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        assert AcquisitionPlanner._same_filesystem(a, b) is True

    def test_same_filesystem_one_missing(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        assert AcquisitionPlanner._same_filesystem(a, b) is False

    def test_test_hardlink_ok(self, tmp_path):
        seed = tmp_path / "seed"
        out = tmp_path / "out"
        seed.mkdir()
        out.mkdir()
        assert AcquisitionPlanner._test_hardlink(seed, out) is True

    def test_test_hardlink_fails_across_devices(self, tmp_path):
        seed = tmp_path / "seed"
        out = tmp_path / "out"
        seed.mkdir()
        out.mkdir()

        def failing_link(*args, **kwargs):
            raise OSError("cross-device")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("os.link", failing_link)
            assert AcquisitionPlanner._test_hardlink(seed, out) is False

    def test_sort_candidates_smallest_first(self):
        cands = [
            (_make_entry("e1"), 1, 300, "t.zip", Path("d1")),
            (_make_entry("e2"), 2, 100, "t.zip", Path("d2")),
            (_make_entry("e3"), 3, 200, "t.zip", Path("d3")),
        ]
        sorted_ = AcquisitionPlanner._sort_candidates(cands, SelectionStrategy.SMALLEST_FIRST)
        assert [c[2] for c in sorted_] == [100, 200, 300]

    def test_sort_candidates_largest_first(self):
        cands = [
            (_make_entry("e1"), 1, 100, "t.zip", Path("d1")),
            (_make_entry("e2"), 2, 300, "t.zip", Path("d2")),
        ]
        sorted_ = AcquisitionPlanner._sort_candidates(cands, SelectionStrategy.LARGEST_FIRST)
        assert [c[2] for c in sorted_] == [300, 100]

    def test_sort_candidates_confidence_first(self):
        e_low = _make_entry("e1", confidence=0.3)
        e_high = _make_entry("e2", confidence=0.9)
        cands = [
            (e_low, 1, 100, "t.zip", Path("d1")),
            (e_high, 2, 200, "t.zip", Path("d2")),
        ]
        sorted_ = AcquisitionPlanner._sort_candidates(cands, SelectionStrategy.CONFIDENCE_FIRST)
        assert sorted_[0][0].id == "e2"

    def test_sort_candidates_report_order(self):
        cands = [
            (_make_entry("e1"), 1, 300, "t.zip", Path("d1")),
            (_make_entry("e2"), 2, 100, "t.zip", Path("d2")),
        ]
        sorted_ = AcquisitionPlanner._sort_candidates(cands, SelectionStrategy.REPORT_ORDER)
        assert [c[0].id for c in sorted_] == ["e1", "e2"]


# ============================================================================
# Budget and volume building
# ============================================================================


class TestComputeBudgets:
    def test_same_fs_hardlink_ok(self):
        usage = shutil._ntuple_diskusage(total=200, used=50, free=150)
        committed = {}
        constraints = AcquisitionConstraints(reserve_free_bytes=10)
        seed_budget, output_budget = AcquisitionPlanner._compute_budgets(
            usage, usage, committed, constraints, same_fs=True, hardlink_ok=True,
        )
        assert seed_budget == output_budget
        assert seed_budget <= 140

    def test_same_fs_copy_required(self):
        usage = shutil._ntuple_diskusage(total=200, used=50, free=150)
        committed = {}
        constraints = AcquisitionConstraints(reserve_free_bytes=10)
        seed_budget, output_budget = AcquisitionPlanner._compute_budgets(
            usage, usage, committed, constraints, same_fs=True, hardlink_ok=False,
        )
        assert seed_budget > output_budget  # seed gets full free; output gets reserved-committed budget

    def test_different_filesystems(self):
        seed_usage = shutil._ntuple_diskusage(total=200, used=50, free=150)
        out_usage = shutil._ntuple_diskusage(total=300, used=50, free=250)
        committed = {}
        constraints = AcquisitionConstraints(reserve_free_bytes=10, max_total_bytes=100)
        s, o = AcquisitionPlanner._compute_budgets(
            seed_usage, out_usage, committed, constraints, same_fs=False, hardlink_ok=False,
        )
        assert s <= 100
        assert o <= 100


class TestBuildVolumes:
    def test_fits_true(self):
        usage = shutil._ntuple_diskusage(total=200, used=50, free=150)
        constraints = AcquisitionConstraints(reserve_free_bytes=10)
        seed_dir = out_dir = Path("/tmp")
        vols = AcquisitionPlanner._build_volumes(
            seed_dir, out_dir, usage, usage, {}, 0, 0, constraints,
        )
        assert all(v.fits for v in vols)

    def test_used_bytes_reduce_budget(self):
        usage = shutil._ntuple_diskusage(total=200, used=180, free=20)
        constraints = AcquisitionConstraints(reserve_free_bytes=10)
        seed_dir = out_dir = Path("/tmp")
        vols = AcquisitionPlanner._build_volumes(
            seed_dir, out_dir, usage, usage, {}, 20, 20, constraints,
        )
        assert all(not v.fits for v in vols)


# ============================================================================
# Commitment accounting
# ============================================================================


class TestCommittedBytes:
    def test_active_records_counted(self, tmp_path):
        seed_dir = tmp_path / "seed"
        out_dir = tmp_path / "out"
        seed_dir.mkdir()
        out_dir.mkdir()
        state = MinervaState(tmp_path / "state.db")
        db = MagicMock()
        db.get_files_by_ids.return_value = [
            SimpleNamespace(size=500, id=1, file_id=1),
        ]
        state.save_queue_record(QueueRecord(
            id="q1", file_id=1, report_entry_id="e1",
            status=DownloadStatus.DOWNLOADING.value,
            destination=str(out_dir / "a.zip"),
            created_at="", updated_at="",
        ))

        planner = AcquisitionPlanner(state=state, db=db, settings={
            "qbit/save_path": str(seed_dir),
            "downloads/output_dir": str(out_dir),
        })
        committed = planner._committed_bytes(seed_dir, out_dir)
        assert any(v > 0 for v in committed.values())

    def test_completed_records_ignored(self, tmp_path):
        seed_dir = tmp_path / "seed"
        out_dir = tmp_path / "out"
        seed_dir.mkdir()
        out_dir.mkdir()
        state = MinervaState(tmp_path / "state.db")
        db = MagicMock()
        db.get_files_by_ids.return_value = [
            SimpleNamespace(size=500, id=1, file_id=1),
        ]
        state.save_queue_record(QueueRecord(
            id="q1", file_id=1, report_entry_id="e1",
            status=DownloadStatus.COMPLETED.value,
            destination=str(out_dir / "a.zip"),
            created_at="", updated_at="",
        ))

        planner = AcquisitionPlanner(state=state, db=db, settings={
            "qbit/save_path": str(seed_dir),
            "downloads/output_dir": str(out_dir),
        })
        committed = planner._committed_bytes(seed_dir, out_dir)
        assert all(v == 0 for v in committed.values())


# ============================================================================
# Candidate collection
# ============================================================================


class TestCollectCandidates:
    def test_ready_entry_selected(self, tmp_path):
        state = MagicMock()
        state.list_queue.return_value = []
        state.get_entries.return_value = [
            _make_entry("e1", resolution=ResolutionState.READY, automatic_file_id=42),
        ]
        db = MagicMock()
        db.get_files_by_ids.return_value = [_make_item(42, size=100)]
        planner = AcquisitionPlanner(state=state, db=db, settings={
            "downloads/output_dir": str(tmp_path / "out"),
        })
        cands = planner._collect_candidates(
            state.get_entries("r1"), AcquisitionConstraints(),
        )
        assert len(cands) == 1
        assert cands[0][1] == 42

    def test_not_found_skipped(self):
        state = MagicMock()
        state.list_queue.return_value = []
        state.get_entries.return_value = [
            _make_entry("e1", resolution=ResolutionState.NOT_FOUND),
        ]
        planner = AcquisitionPlanner(state=state, db=MagicMock())
        cands = planner._collect_candidates(
            state.get_entries("r1"), AcquisitionConstraints(),
        )
        assert cands == []

    def test_automatic_match_deferred_when_disabled(self):
        state = MagicMock()
        state.list_queue.return_value = []
        state.get_entries.return_value = [
            _make_entry("e1", resolution=ResolutionState.READY, automatic_file_id=1),
        ]
        planner = AcquisitionPlanner(state=state, db=MagicMock())
        cands = planner._collect_candidates(
            state.get_entries("r1"),
            AcquisitionConstraints(include_automatic_matches=False),
        )
        assert cands == []

    def test_reviewed_entry_requires_approved_decision(self):
        state = MagicMock()
        state.list_queue.return_value = []
        state.get_entries.return_value = [
            _make_entry(
                "e1", resolution=ResolutionState.REVIEW_REQUIRED,
                selected_file_id=7, decision="reject",
            ),
        ]
        db = MagicMock()
        db.get_files_by_ids.return_value = [_make_item(7)]
        planner = AcquisitionPlanner(state=state, db=db)
        cands = planner._collect_candidates(
            state.get_entries("r1"), AcquisitionConstraints(),
        )
        assert cands == []

    def test_queued_file_id_skipped(self, tmp_path):
        state = MagicMock()
        state.list_queue.return_value = [
            QueueRecord(id="q1", file_id=1, status=DownloadStatus.QUEUED.value),
        ]
        state.get_entries.return_value = [
            _make_entry("e1", selected_file_id=1, resolution=ResolutionState.READY),
        ]
        planner = AcquisitionPlanner(state=state, db=MagicMock())
        cands = planner._collect_candidates(
            state.get_entries("r1"), AcquisitionConstraints(),
        )
        assert cands == []

    def test_collection_filter(self):
        state = MagicMock()
        state.list_queue.return_value = []
        state.get_entries.return_value = [
            _make_entry("e1", selected_file_id=1, resolution=ResolutionState.READY),
        ]
        db = MagicMock()
        db.get_files_by_ids.return_value = [_make_item(1, collection="Sega")]
        planner = AcquisitionPlanner(state=state, db=db)
        cands = planner._collect_candidates(
            state.get_entries("r1"),
            AcquisitionConstraints(collections=frozenset({"Nintendo"})),
        )
        assert cands == []

    def test_extension_filter(self):
        state = MagicMock()
        state.list_queue.return_value = []
        state.get_entries.return_value = [
            _make_entry("e1", selected_file_id=1, resolution=ResolutionState.READY),
        ]
        db = MagicMock()
        db.get_files_by_ids.return_value = [_make_item(1, basename="rom.bin")]
        planner = AcquisitionPlanner(state=state, db=db)
        cands = planner._collect_candidates(
            state.get_entries("r1"),
            AcquisitionConstraints(extensions=frozenset({".zip"})),
        )
        assert cands == []

    def test_require_seeded_source_missing_torrent(self):
        state = MagicMock()
        state.list_queue.return_value = []
        state.get_entries.return_value = [
            _make_entry("e1", selected_file_id=1, resolution=ResolutionState.READY),
        ]
        db = MagicMock()
        db.get_files_by_ids.return_value = [_make_item(1)]
        planner = AcquisitionPlanner(state=state, db=db, settings={
            "torrent_dir": "/nonexistent/torrents",
        })
        cands = planner._collect_candidates(
            state.get_entries("r1"),
            AcquisitionConstraints(require_seeded_source=True),
        )
        assert cands == []


# ============================================================================
# Build plan end-to-end
# ============================================================================


class TestBuildPlan:
    def test_end_to_end_selects_file(self, tmp_path):
        seed_dir = tmp_path / ".qbitseed"
        out_dir = tmp_path / "downloads"
        seed_dir.mkdir()
        out_dir.mkdir()
        state = MagicMock()
        report_id = "r1"
        state.get_entries.return_value = [
            _make_entry(report_id=report_id, selected_file_id=10, resolution=ResolutionState.READY),
        ]
        state.get_report.return_value = SimpleNamespace(name="Test Report")
        state.list_queue.return_value = []
        db = MagicMock()
        db.get_files_by_ids.return_value = [_make_item(10, size=50)]

        planner = AcquisitionPlanner(state=state, db=db, settings={
            "qbit/save_path": str(seed_dir),
            "downloads/output_dir": str(out_dir),
        })
        plan = planner.build_plan(
            report_id, AcquisitionConstraints(reserve_free_bytes=1),
        )

        assert len(plan.selected) == 1
        assert plan.selected[0].file_id == 10
        assert plan.selected_bytes == 50
        assert plan.deferred == ()
        assert plan.report_name == "Test Report"
        assert len(plan.volumes) == 2

    def test_max_file_count_deferred(self, tmp_path):
        seed_dir = tmp_path / ".qbitseed"
        out_dir = tmp_path / "downloads"
        seed_dir.mkdir()
        out_dir.mkdir()
        state = MagicMock()
        state.get_entries.return_value = [
            _make_entry("e1", selected_file_id=10, resolution=ResolutionState.READY),
            _make_entry("e2", selected_file_id=11, resolution=ResolutionState.READY),
        ]
        state.get_report.return_value = None
        state.list_queue.return_value = []
        db = MagicMock()
        db.get_files_by_ids.side_effect = lambda ids: [_make_item(ids[0], size=10)]

        planner = AcquisitionPlanner(state=state, db=db, settings={
            "qbit/save_path": str(seed_dir),
            "downloads/output_dir": str(out_dir),
        })
        plan = planner.build_plan(
            "r1", AcquisitionConstraints(
                max_file_count=1, max_total_bytes=10_000_000_000, reserve_free_bytes=1,
            ),
        )
        assert len(plan.selected) == 1
        assert len(plan.deferred) == 1
        assert "max file count" in plan.deferred[0].reason

    def test_max_size_deferred(self, tmp_path):
        seed_dir = tmp_path / ".qbitseed"
        out_dir = tmp_path / "downloads"
        seed_dir.mkdir()
        out_dir.mkdir()
        state = MagicMock()
        state.get_entries.return_value = [
            _make_entry("e1", selected_file_id=10, resolution=ResolutionState.READY),
        ]
        state.get_report.return_value = None
        state.list_queue.return_value = []
        db = MagicMock()
        db.get_files_by_ids.return_value = [_make_item(10, size=1024)]

        planner = AcquisitionPlanner(state=state, db=db, settings={
            "qbit/save_path": str(seed_dir),
            "downloads/output_dir": str(out_dir),
        })
        plan = planner.build_plan(
            "r1", AcquisitionConstraints(max_file_bytes=512, reserve_free_bytes=1),
        )
        assert len(plan.selected) == 0
        assert len(plan.deferred) == 1
        assert "limit" in plan.deferred[0].reason


# ============================================================================
# Explain deferrals
# ============================================================================


class TestExplainDeferrals:
    def test_groups_reasons(self):
        state = MagicMock()
        planner = AcquisitionPlanner(state=state)
        from minerva.domain.reports import DeferredFile
        plan = MagicMock()
        plan.deferred = [
            DeferredFile("e1", 1, 100, "too big"),
            DeferredFile("e2", 2, 200, "too big"),
            DeferredFile("e3", 3, 300, "no match"),
        ]
        summary = planner.explain_deferrals(plan)
        assert summary == {"too big": 2, "no match": 1}

    def test_empty_plan(self):
        planner = AcquisitionPlanner(state=MagicMock())
        from minerva.domain.reports import AcquisitionPlan
        plan = AcquisitionPlan(
            selected=(), deferred=(), volumes=(),
            selected_bytes=0, estimated_transfer_bytes=0,
            report_id="r1", report_name="",
        )
        assert planner.explain_deferrals(plan) == {}
