"""
Tests for report triage — ``ReportOutcome`` computation, eligibility,
``compute_outcome`` on ``ReportAcquisitionService``.

Run with::

    PYTHONPATH=. .venv/bin/pytest tests/test_report_triage.py -q
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from minerva.domain.reports import (
    AcquisitionConstraints,
    ReportOutcome,
    ReportSummary,
    ResolutionState,
    ReviewEntry,
)
from minerva.services.report_acquisition import ReportAcquisitionService
from minerva_db import MinervaDB, SCHEMA_V3
from minerva_state import MinervaState


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def tmp_state():
    """Create a MinervaState backed by a temporary file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    state = MinervaState(db_path=tmp.name)
    yield state
    os.unlink(tmp.name)


def _build_test_index(path: str) -> None:
    """Build a small test index with known files."""
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.executescript(SCHEMA_V3)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', '3')",
    )
    conn.commit()
    conn.close()


@pytest.fixture
def test_index(tmp_path):
    """Create a small test index database."""
    db_path = tmp_path / "test_index.db"
    _build_test_index(str(db_path))
    return db_path


@pytest.fixture
def test_db(test_index):
    """Return a MinervaDB instance backed by the test index."""
    return MinervaDB(db_path=test_index)


def _make_entries(
    report_id: str,
    *,
    ready: int = 0,
    review: int = 0,
    not_found: int = 0,
) -> list[ReviewEntry]:
    """Create test entries with given resolution counts."""
    entries: list[ReviewEntry] = []
    idx = 0
    for _ in range(ready):
        entries.append(ReviewEntry(
            id=f"{report_id}_r{idx}",
            report_id=report_id,
            ordinal=idx,
            filename=f"ready_{idx}.zip",
            size=1024,
            automatic_file_id=100 + idx,
            automatic_method="exact",
            automatic_confidence=1.0,
            resolution=ResolutionState.READY,
            decision="accept",
        ))
        idx += 1
    for _ in range(review):
        entries.append(ReviewEntry(
            id=f"{report_id}_v{idx}",
            report_id=report_id,
            ordinal=idx,
            filename=f"ambig_{idx}.zip",
            size=1024,
            automatic_file_id=200 + idx,
            automatic_method="trigram",
            automatic_confidence=0.75,
            resolution=ResolutionState.REVIEW_REQUIRED,
            decision="pending",
        ))
        idx += 1
    for _ in range(not_found):
        entries.append(ReviewEntry(
            id=f"{report_id}_n{idx}",
            report_id=report_id,
            ordinal=idx,
            filename=f"nf_{idx}.bin",
            size=0,
            automatic_file_id=None,
            automatic_method=None,
            automatic_confidence=None,
            resolution=ResolutionState.NOT_FOUND,
            decision="reject",
        ))
        idx += 1
    return entries


def _seed_report(
    state: MinervaState,
    report_id: str = "test-report",
    *,
    ready: int = 0,
    review: int = 0,
    not_found: int = 0,
) -> None:
    """Save a report with entries to the state DB."""
    report = ReportSummary(
        id=report_id,
        path=f"/tmp/{report_id}.dat",
        name=report_id,
        collection="Nintendo",
        system="NES",
        requested_count=ready + review + not_found,
        ready_count=ready,
        review_required_count=review,
        not_found_count=not_found,
        status="ready",
    )
    state.save_report(report)
    entries = _make_entries(report_id, ready=ready, review=review, not_found=not_found)
    state.replace_entries(report_id, entries)


# ============================================================================
# compute_outcome
# ============================================================================


def test_outcome_actionable_when_eligible(tmp_state, test_db):
    """GIVEN a report with READY entries WHEN compute_outcome is called
    THEN outcome is ACTIONABLE."""
    _seed_report(tmp_state, "r1", ready=5)
    svc = ReportAcquisitionService(state=tmp_state, db=test_db)
    outcome = svc.compute_outcome("r1")
    assert outcome == ReportOutcome.ACTIONABLE


def test_outcome_needs_review_when_only_ambiguous(tmp_state, test_db):
    """GIVEN a report with only REVIEW_REQUIRED entries WHEN compute_outcome
    is called THEN outcome is NEEDS_REVIEW."""
    _seed_report(tmp_state, "r2", review=3)
    svc = ReportAcquisitionService(state=tmp_state, db=test_db)
    outcome = svc.compute_outcome("r2")
    assert outcome == ReportOutcome.NEEDS_REVIEW


def test_outcome_no_source_matches_when_zero_candidates(tmp_state, test_db):
    """GIVEN a report with only NOT_FOUND entries WHEN compute_outcome
    is called THEN outcome is NO_SOURCE_MATCHES."""
    _seed_report(tmp_state, "r3", not_found=4)
    svc = ReportAcquisitionService(state=tmp_state, db=test_db)
    outcome = svc.compute_outcome("r3")
    assert outcome == ReportOutcome.NO_SOURCE_MATCHES


def test_outcome_empty_when_no_entries(tmp_state, test_db):
    """GIVEN a report with no entries WHEN compute_outcome is called
    THEN outcome is EMPTY."""
    report = ReportSummary(
        id="empty", path="/tmp/empty.dat", name="Empty",
        requested_count=0,
    )
    tmp_state.save_report(report)
    svc = ReportAcquisitionService(state=tmp_state, db=test_db)
    outcome = svc.compute_outcome("empty")
    assert outcome == ReportOutcome.EMPTY


def test_outcome_filtered_out_when_size_limit_excludes_all(tmp_state, test_db):
    """GIVEN a report where size constraints exclude all candidates
    WHEN compute_outcome is called THEN outcome is FILTERED_OUT."""
    _seed_report(tmp_state, "r4", ready=3)
    svc = ReportAcquisitionService(state=tmp_state, db=test_db)
    # Use extremely tight max_file_bytes to exclude everything
    outcome = svc.compute_outcome("r4", AcquisitionConstraints(
        max_file_bytes=1,  # 1 byte — all entries are 1024 bytes
    ))
    assert outcome == ReportOutcome.FILTERED_OUT


def test_outcome_already_satisfied(tmp_state, test_db):
    """GIVEN a report where all entries are completed WHEN compute_outcome
    is called THEN outcome is ALREADY_SATISFIED."""
    from minerva.domain.downloads import QueueRecord
    from datetime import datetime, timezone

    _seed_report(tmp_state, "r5", ready=2)
    # Mark both entries as completed in the queue
    now = datetime.now(timezone.utc).isoformat()
    for i in range(2):
        rec = QueueRecord(
            id=f"q_complete_{i}",
            file_id=100 + i,  # matches the _make_entries file_ids
            status="completed",
            destination=f"/out/ready_{i}.zip",
            created_at=now,
            updated_at=now,
        )
        tmp_state.save_queue_record(rec)

    svc = ReportAcquisitionService(state=tmp_state, db=test_db)
    outcome = svc.compute_outcome("r5")
    assert outcome == ReportOutcome.ALREADY_SATISFIED


# ============================================================================
# ReportOutcome enum
# ============================================================================


def test_report_outcome_values():
    """GIVEN ReportOutcome enum THEN all expected values exist."""
    values = {e.value for e in ReportOutcome}
    expected = {
        "actionable", "needs_review", "no_source_matches",
        "filtered_out", "already_satisfied", "empty", "error",
    }
    assert values == expected


# ============================================================================
# ReportSummary new fields
# ============================================================================


def test_report_summary_triage_fields_default():
    """GIVEN a default ReportSummary THEN triage fields are zero/empty."""
    rs = ReportSummary(
        id="t", path="/t", name="t", requested_count=0,
    )
    assert rs.safe_match_count == 0
    assert rs.eligible_count == 0
    assert rs.eligible_bytes == 0
    assert rs.outcome == ""
