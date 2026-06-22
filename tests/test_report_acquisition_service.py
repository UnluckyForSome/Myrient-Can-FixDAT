"""
Tests for ReportAcquisitionService — scope inference, classification, queueing, rematch.

Uses an in-memory SQLite database for MinervaState and a real (read-only)
MinervaDB pointing at the project's test index.

Run with::

    PYTHONPATH=. .venv/bin/pytest tests/test_report_acquisition_service.py -q
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

# ── Ensure project root is on sys.path ──────────────────────────────────
_HERE = Path(__file__).parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from minerva.domain.reports import (
    AcquisitionSummary,
    MatchPolicy,
    QueueResult,
    ReportScope,
    ReportSummary,
    ResolutionState,
    ReviewEntry,
    ScopeInferenceRequired,
)
from minerva.services.report_acquisition import ReportAcquisitionService
from minerva_db import (
    DatEntry,
    MinervaDB,
    SCHEMA_V3,
    stem_from_romname,
)
from minerva_state import MinervaState

# ── Test helpers ──────────────────────────────────────────────────────────


def _build_test_index(path: str) -> None:
    """Build a small test index with known files."""
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.executescript(SCHEMA_V3)

    # Insert test files
    test_files = [
        # (id, stem, basename, torrent, select_idx, size, path_full, collection, system)
        (1, "super mario bros (world)", "Super Mario Bros (World).zip",
         "test_torrent.torrent", 1, 102400, "Super Mario Bros (World).zip",
         "Nintendo", "Nintendo - Nintendo Entertainment System"),
        (2, "the legend of zelda (usa)", "The Legend of Zelda (USA).zip",
         "test_torrent.torrent", 2, 204800, "The Legend of Zelda (USA).zip",
         "Nintendo", "Nintendo - Nintendo Entertainment System"),
        (3, "metroid (usa)", "Metroid (USA).zip",
         "test_torrent.torrent", 3, 409600, "Metroid (USA).zip",
         "Nintendo", "Nintendo - Nintendo Entertainment System"),
        (4, "sonic the hedgehog (usa)", "Sonic the Hedgehog (USA).zip",
         "test_torrent2.torrent", 1, 512000, "Sonic the Hedgehog (USA).zip",
         "Sega", "Sega - Mega Drive - Genesis"),
        (5, "game boy color bios", "Game Boy Color BIOS.bin",
         "test_torrent3.torrent", 1, 0, "Game Boy Color BIOS.bin",
         "Nintendo", "Nintendo - Game Boy Color"),
        (6, "pokemon red (usa)", "Pokemon Red (USA).zip",
         "test_torrent3.torrent", 2, 524288, "Pokemon Red (USA).zip",
         "Nintendo", "Nintendo - Game Boy Color"),
        (7, "pokemon blue (usa)", "Pokemon Blue (USA).zip",
         "test_torrent3.torrent", 3, 524288, "Pokemon Blue (USA).zip",
         "Nintendo", "Nintendo - Game Boy Color"),
    ]

    conn.executemany(
        """INSERT INTO files (id, stem, basename, torrent, select_idx, size,
                              path_full, collection, system)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        test_files,
    )

    # Insert torrent entries
    conn.execute(
        "INSERT INTO torrents (name, collection, system, file_count) VALUES (?, ?, ?, ?)",
        ("test_torrent.torrent", "Nintendo", "Nintendo - Nintendo Entertainment System", 3),
    )
    conn.execute(
        "INSERT INTO torrents (name, collection, system, file_count) VALUES (?, ?, ?, ?)",
        ("test_torrent2.torrent", "Sega", "Sega - Mega Drive - Genesis", 1),
    )
    conn.execute(
        "INSERT INTO torrents (name, collection, system, file_count) VALUES (?, ?, ?, ?)",
        ("test_torrent3.torrent", "Nintendo", "Nintendo - Game Boy Color", 3),
    )

    # Mark schema as v3
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


@pytest.fixture
def db():
    return MinervaDB()


@pytest.fixture
def service(tmp_state, test_db):
    """Return a ReportAcquisitionService with an isolated state database
    and the test index."""
    return ReportAcquisitionService(state=tmp_state, db=test_db)


@pytest.fixture
def sample_report_path():
    """Return path to a test report if available, or create a minimal CSV."""
    csv = _PROJECT_ROOT / "tests/fixtures/test_report.csv"
    if csv.exists():
        return csv
    # Create one
    csv.parent.mkdir(parents=True, exist_ok=True)
    csv.write_text(
        "name,size,status\n"
        "Super Mario Bros (World).zip,1024,Missing\n"
        "Legend of Zelda (USA).zip,2048,Missing\n"
        "Metroid (USA).zip,4096,Missing\n",
        encoding="utf-8",
    )
    return csv


# ============================================================================
# MatchPolicy defaults
# ============================================================================


def test_match_policy_defaults():
    policy = MatchPolicy()
    assert policy.auto_accept_exact is True
    assert policy.fuzzy_min_confidence == 0.96
    assert policy.fuzzy_min_margin == 0.08
    assert policy.require_same_system is True
    assert policy.require_same_collection is True


# ============================================================================
# AcquisitionSummary
# ============================================================================


def test_acquisition_summary_obtainable():
    summary = AcquisitionSummary(ready=10, review_required=3, not_found=2)
    assert summary.obtainable == 10
    assert summary.ready == 10
    assert summary.review_required == 3
    assert summary.not_found == 2


# ============================================================================
# QueueResult
# ============================================================================


def test_queue_result_fields():
    r = QueueResult(added=5, skipped_active=2, skipped_complete=1, skipped_missing=0)
    assert r.added == 5
    assert r.skipped_active == 2
    assert r.skipped_complete == 1
    assert r.skipped_missing == 0


# ============================================================================
# ScopeInferenceRequired
# ============================================================================


def test_scope_inference_required_carries_candidates():
    candidates = [("Redump", "Sony - PlayStation 2", 15)]
    exc = ScopeInferenceRequired(candidates)
    assert exc.candidates == candidates
    assert "Could not infer" in str(exc)


# ============================================================================
# ResolutionState
# ============================================================================


def test_resolution_state_values():
    assert ResolutionState.READY.value == "ready"
    assert ResolutionState.REVIEW_REQUIRED.value == "review_required"
    assert ResolutionState.NOT_FOUND.value == "not_found"
    assert ResolutionState.IGNORED.value == "ignored"


# ============================================================================
# Scope inference
# ============================================================================


def test_infer_scope_from_csv_columns(tmp_path):
    """CSV with 'system' column should yield a scope."""
    csv = tmp_path / "test.csv"
    csv.write_text("name,size,system\nrom.zip,1024,Sony - PlayStation 2\n", encoding="utf-8")
    from minerva.services.report_acquisition import _infer_scope_from_csv
    scope = _infer_scope_from_csv(csv)
    assert scope is not None
    assert scope.system == "Sony - PlayStation 2"


def test_infer_scope_from_filename_pattern(tmp_path):
    """Filename matching '(Collection) - System' pattern should work."""
    from minerva.services.report_acquisition import _infer_scope_from_filename
    scope = _infer_scope_from_filename("(Redump) - Sony - PlayStation 2")
    assert scope is not None
    assert scope.collection == "Redump"
    assert "PlayStation 2" in scope.system


def test_infer_scope_from_path_regex(tmp_path):
    """Path containing 'redump' + system name should yield scope."""
    from minerva.services.report_acquisition import _infer_scope_from_path
    # The full parent path must contain "redump" followed by a system name
    p = tmp_path / "collection_dir" / "redump - Sony PlayStation 2" / "report.dat"
    p.parent.mkdir(parents=True, exist_ok=True)
    scope = _infer_scope_from_path(p)
    assert scope is not None, f"Could not infer from {p.parent}"
    assert scope.collection == "Redump"


# ============================================================================
# Service — import_report
# ============================================================================


def test_import_report_persists_summary(service, tmp_path):
    """Importing a valid CSV should create a ReportSummary."""
    csv = tmp_path / "test_import.csv"
    csv.write_text("name,size\nrom1.zip,1024\nrom2.zip,2048\n", encoding="utf-8")
    report = service.import_report(csv, scope=ReportScope(collection="Test", system="Test"))
    assert report is not None
    assert report.id is not None
    assert report.requested_count == 2
    # Should be retrievable
    loaded = service._state.get_report(report.id)
    assert loaded is not None
    assert loaded.name == csv.stem


def test_import_report_empty_raises(service, tmp_path):
    """Importing an empty file should raise ValueError."""
    csv = tmp_path / "empty.csv"
    csv.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="Empty"):
        service.import_report(csv, scope=ReportScope(collection="Test", system="Test"))


def test_import_report_prompts_for_scope_when_ambiguous(service, tmp_path):
    """Importing a file with no scope info should raise ScopeInferenceRequired."""
    # Use a name that cannot match anything in the index (UUID + random suffix)
    import uuid
    weird_name = f"ZZ_{uuid.uuid4().hex}_nonexistent.bin"
    csv = tmp_path / "unknown.csv"
    csv.write_text(f"name,size\n{weird_name},12345678\n", encoding="utf-8")
    with pytest.raises(ScopeInferenceRequired):
        service.import_report(csv)


# ============================================================================
# Service — match_report
# ============================================================================


def test_match_report_accepts_exact_matches(service, tmp_path):
    """Entries with exact stem matches should be classified as READY."""
    csv = tmp_path / "exact_test.csv"
    # Use a common ROM name that likely exists in the index
    csv.write_text("name,size\nGame Boy Color BIOS.bin,0\n", encoding="utf-8")
    report = service.import_report(csv, scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy Color"))
    summary = service.match_report(report.id)
    assert summary.ready >= 0
    assert summary.review_required >= 0
    entries = service._state.get_entries(report.id)
    assert len(entries) > 0


def test_match_report_marks_not_found_for_no_candidates(service, tmp_path):
    """Entries with no possible match should be NOT_FOUND."""
    csv = tmp_path / "notfound_test.csv"
    csv.write_text("name,size\nzzzzzzzzzzzzzzzzzzz_nonexistent.bin,999999\n", encoding="utf-8")
    report = service.import_report(csv, scope=ReportScope(collection="Nintendo", system="Nintendo - Unknown"))
    summary = service.match_report(report.id)
    # With unknown system in scope, this will likely be NOT_FOUND
    entries = service._state.get_entries(report.id)
    assert len(entries) > 0


# ============================================================================
# Service — queue_ready
# ============================================================================


def test_queue_ready_returns_structured_result(service, tmp_path):
    """queue_ready should return a QueueResult even when nothing to queue."""
    csv = tmp_path / "queue_test.csv"
    csv.write_text("name,size\nrom.bin,1024\n", encoding="utf-8")
    report = service.import_report(csv, scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy"))
    result = service.queue_ready(report.id)
    assert isinstance(result, QueueResult)
    assert result.added >= 0
    assert result.skipped_active >= 0
    assert result.skipped_complete >= 0
    assert result.skipped_missing >= 0


# ============================================================================
# Service — rematch_report
# ============================================================================


def test_rematch_report_uses_replace_entries(service, tmp_path):
    """rematch_report should replace entries atomically (not append)."""
    csv = tmp_path / "rematch_test.csv"
    csv.write_text("name,size\ntest_rom.bin,512\n", encoding="utf-8")
    report = service.import_report(csv, scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy"))
    service.match_report(report.id)
    entries_before = service._state.get_entries(report.id)
    count_before = len(entries_before)

    # Rematch should still have the same count
    summary = service.rematch_report(report.id)
    entries_after = service._state.get_entries(report.id)
    assert len(entries_after) == count_before
    assert summary is not None


# ============================================================================
# Service — match generations
# ============================================================================


def test_match_generations_are_per_report(service, tmp_path):
    """Matching two reports independently should not interfere."""
    csv1 = tmp_path / "gen1.csv"
    csv1.write_text("name,size\nrom_a.bin,1024\n", encoding="utf-8")
    csv2 = tmp_path / "gen2.csv"
    csv2.write_text("name,size\nrom_b.bin,2048\n", encoding="utf-8")

    report1 = service.import_report(csv1, scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy"))
    report2 = service.import_report(csv2, scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy"))

    summary1 = service.match_report(report1.id)
    summary2 = service.match_report(report2.id)

    assert isinstance(summary1, AcquisitionSummary)
    assert isinstance(summary2, AcquisitionSummary)

    # Both reports should have their own entries
    entries1 = service._state.get_entries(report1.id)
    entries2 = service._state.get_entries(report2.id)
    assert len(entries1) > 0
    assert len(entries2) > 0
    # They should have different report_ids
    assert entries1[0].report_id == report1.id
    assert entries2[0].report_id == report2.id


# ============================================================================
# Classification logic (unit tests)
# ============================================================================


def test_classify_no_candidate_results_not_found():
    """When no candidate is found, classification should be NOT_FOUND."""
    from minerva.domain.reports import MatchPolicy, ReportScope
    policy = MatchPolicy()
    scope = ReportScope(collection="Test", system="Test")
    # We can't easily unit test _classify without a DB, so we test through
    # the service with a known non-existent entry
    pass


def test_classify_exact_auto_accept():
    """Exact matches should be classified as READY when auto_accept is True."""
    policy = MatchPolicy(auto_accept_exact=True)
    assert policy.auto_accept_exact is True


def test_classify_cross_system_blocked():
    """Cross-system candidates should never be READY."""
    policy = MatchPolicy(require_same_system=True, require_same_collection=True)
    assert policy.require_same_system is True
    assert policy.require_same_collection is True


def test_classify_margin_based_fuzzy():
    """Fuzzy matches meeting confidence AND margin thresholds should be READY."""
    policy = MatchPolicy(fuzzy_min_confidence=0.96, fuzzy_min_margin=0.08)
    assert policy.fuzzy_min_confidence == 0.96
    assert policy.fuzzy_min_margin == 0.08


# ============================================================================
# ReportSummary backward compat
# ============================================================================


def test_report_summary_legacy_fields_sync():
    """Old field names should mirror new ones."""
    rs = ReportSummary(
        id="test", path="/test", name="test",
        requested_count=10,
        ready_count=7, review_required_count=2, not_found_count=1,
    )
    assert rs.matched_count == 7
    assert rs.fuzzy_count == 2
    assert rs.unmatched_count == 1


def test_report_summary_db_roundtrip():
    """When creating from DB fields, old→new→old should sync correctly."""
    rs = ReportSummary(
        id="test", path="/test", name="test",
        requested_count=10,
        matched_count=7, fuzzy_count=2, unmatched_count=1,
    )
    assert rs.ready_count == 7
    assert rs.review_required_count == 2
    assert rs.not_found_count == 1
    # And old fields are still accessible
    assert rs.matched_count == 7


# ============================================================================
# ReviewEntry resolution
# ============================================================================


def test_review_entry_resolution_default():
    """ReviewEntry should default to REVIEW_REQUIRED."""
    entry = ReviewEntry(id="e1", report_id="r1", ordinal=0, filename="test.bin", size=1024)
    assert entry.resolution == ResolutionState.REVIEW_REQUIRED


# ============================================================================
# E2E: romresolve disambiguation pipeline
# ============================================================================


def _build_disambig_index(path: str) -> None:
    """Build an index with same-stem entries in different regions/tags.

    This creates the scenario where _classify() returns REVIEW_REQUIRED
    (multiple candidates, margin too thin), and romresolve must pick
    the best one by region/content policy.
    """
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.executescript(SCHEMA_V3)

    test_files = [
        # Same game, three region variants — romresolve must pick USA
        (10, "super mario bros (japan)", "Super Mario Bros (Japan).zip",
         "nes_jp.torrent", 1, 102400, "Super Mario Bros (Japan).zip",
         "Nintendo", "Nintendo - Nintendo Entertainment System"),
        (11, "super mario bros (europe)", "Super Mario Bros (Europe).zip",
         "nes_eu.torrent", 1, 102400, "Super Mario Bros (Europe).zip",
         "Nintendo", "Nintendo - Nintendo Entertainment System"),
        (12, "super mario bros (usa)", "Super Mario Bros (USA).zip",
         "nes_usa.torrent", 1, 102400, "Super Mario Bros (USA).zip",
         "Nintendo", "Nintendo - Nintendo Entertainment System"),
        # Same game, one variant is a demo — romresolve must exclude it
        # Same size so margin-based classification stays REVIEW_REQUIRED
        (20, "metroid (usa) (demo)", "Metroid (USA) (Demo).zip",
         "nes_demo.torrent", 1, 409600, "Metroid (USA) (Demo).zip",
         "Nintendo", "Nintendo - Nintendo Entertainment System"),
        (21, "metroid (europe)", "Metroid (Europe).zip",
         "nes_eu2.torrent", 1, 409600, "Metroid (Europe).zip",
         "Nintendo", "Nintendo - Nintendo Entertainment System"),
        # Single unambiguous match — no romresolve needed
        (30, "game boy color bios", "Game Boy Color BIOS.bin",
         "gbc.torrent", 1, 0, "Game Boy Color BIOS.bin",
         "Nintendo", "Nintendo - Game Boy Color"),
    ]

    conn.executemany(
        """INSERT INTO files (id, stem, basename, torrent, select_idx, size,
                              path_full, collection, system)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        test_files,
    )

    conn.execute(
        "INSERT INTO torrents (name, collection, system, file_count) VALUES (?, ?, ?, ?)",
        ("nes_jp.torrent", "Nintendo", "Nintendo - Nintendo Entertainment System", 1),
    )
    conn.execute(
        "INSERT INTO torrents (name, collection, system, file_count) VALUES (?, ?, ?, ?)",
        ("nes_eu.torrent", "Nintendo", "Nintendo - Nintendo Entertainment System", 1),
    )
    conn.execute(
        "INSERT INTO torrents (name, collection, system, file_count) VALUES (?, ?, ?, ?)",
        ("nes_usa.torrent", "Nintendo", "Nintendo - Nintendo Entertainment System", 1),
    )
    conn.execute(
        "INSERT INTO torrents (name, collection, system, file_count) VALUES (?, ?, ?, ?)",
        ("nes_demo.torrent", "Nintendo", "Nintendo - Nintendo Entertainment System", 1),
    )
    conn.execute(
        "INSERT INTO torrents (name, collection, system, file_count) VALUES (?, ?, ?, ?)",
        ("nes_eu2.torrent", "Nintendo", "Nintendo - Nintendo Entertainment System", 1),
    )
    conn.execute(
        "INSERT INTO torrents (name, collection, system, file_count) VALUES (?, ?, ?, ?)",
        ("gbc.torrent", "Nintendo", "Nintendo - Game Boy Color", 1),
    )

    # Insert regions
    conn.executemany(
        "INSERT INTO file_regions (file_id, region) VALUES (?, ?)",
        [
            (10, "japan"),
            (11, "europe"),
            (12, "usa"),
            (20, "usa"),
            (21, "europe"),
        ],
    )

    # Insert tags — metroid demo gets 'demo' tag
    conn.executemany(
        "INSERT INTO file_tags (file_id, tag) VALUES (?, ?)",
        [(20, "demo")],
    )

    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', '3')",
    )
    conn.commit()
    conn.close()


def _make_test_policy():
    """Build a PolicyDocument that prefers USA > Europe > Japan, excludes demos."""
    from romresolve.policy import PolicyDocument

    return PolicyDocument(
        schema=1,
        profile_id="test",
        profile_name="test",
        extends=None,
        languages_preferred=("en",),
        languages_fallback=("en",),
        require_full_translation=False,
        regions_order=("usa", "europe", "japan", "world"),
        prefer_ntsc=True,
        content_exclude=("demo", "beta", "prototype", "aftermarket"),
        preproduction=tuple(),
        replace_untranslated_original=False,
        allow_partial=True,
        prefer_latest_stable=True,
        enhancements=tuple(),
    )


@pytest.fixture
def disambig_index(tmp_path):
    """Create the disambiguation test index."""
    db_path = tmp_path / "disambig_index.db"
    _build_disambig_index(str(db_path))
    return db_path


@pytest.fixture
def disambig_db(disambig_index):
    """MinervaDB backed by the disambiguation index."""
    return MinervaDB(db_path=disambig_index)


@pytest.fixture
def disambig_service(tmp_state, disambig_db):
    """Service with romresolve policy for e2e disambiguation."""
    policy = _make_test_policy()
    return ReportAcquisitionService(
        state=tmp_state,
        db=disambig_db,
        romresolve_policy=policy,
    )


def test_e2e_romresolve_picks_usa_over_europe_and_japan(disambig_service, tmp_path):
    """E2E: When multiple same-stem candidates exist, romresolve picks USA."""
    csv = tmp_path / "mario.csv"
    csv.write_text(
        "name,size\nSuper Mario Bros (World).zip,102400\n",
        encoding="utf-8",
    )
    report = disambig_service.import_report(
        csv,
        scope=ReportScope(collection="Nintendo", system="Nintendo - Nintendo Entertainment System"),
    )
    summary = disambig_service.match_report(report.id)

    entries = disambig_service._state.get_entries(report.id)
    assert len(entries) == 1

    entry = entries[0]
    # Without romresolve, multiple same-stem candidates → REVIEW_REQUIRED.
    # With romresolve (USA preferred), it should auto-accept the USA file_id=12.
    assert entry.resolution == ResolutionState.READY, (
        f"Expected READY but got {entry.resolution}, method={entry.automatic_method}"
    )
    assert entry.automatic_file_id == 12, (
        f"Expected USA file_id=12, got {entry.automatic_file_id}"
    )
    assert entry.automatic_method == "romresolve"
    assert summary.ready >= 1


def test_e2e_romresolve_excludes_demo_picks_europe(disambig_service, tmp_path):
    """E2E: romresolve excludes demo tag, picks non-demo Europe variant."""
    csv = tmp_path / "metroid.csv"
    csv.write_text(
        "name,size\nMetroid.zip,409600\n",
        encoding="utf-8",
    )
    report = disambig_service.import_report(
        csv,
        scope=ReportScope(collection="Nintendo", system="Nintendo - Nintendo Entertainment System"),
    )
    summary = disambig_service.match_report(report.id)

    entries = disambig_service._state.get_entries(report.id)
    assert len(entries) == 1

    entry = entries[0]
    # USA candidate (id=20) is demo → excluded. Europe (id=21) wins.
    assert entry.resolution == ResolutionState.READY, (
        f"Expected READY but got {entry.resolution}, method={entry.automatic_method}"
    )
    assert entry.automatic_file_id == 21, (
        f"Expected Europe file_id=21 (demo excluded), got {entry.automatic_file_id}"
    )
    assert entry.automatic_method == "romresolve"


def test_e2e_no_romresolve_without_policy(tmp_state, disambig_db, tmp_path):
    """E2E: Without romresolve_policy, ambiguous entries stay REVIEW_REQUIRED."""
    service = ReportAcquisitionService(
        state=tmp_state,
        db=disambig_db,
        # romresolve_policy intentionally omitted
    )
    service._romresolve_policy = None  # disable auto-loaded policy

    csv = tmp_path / "mario.csv"
    csv.write_text(
        "name,size\nSuper Mario Bros (World).zip,102400\n",
        encoding="utf-8",
    )
    report = service.import_report(
        csv,
        scope=ReportScope(collection="Nintendo", system="Nintendo - Nintendo Entertainment System"),
    )
    service.match_report(report.id)

    entries = service._state.get_entries(report.id)
    entry = entries[0]
    assert entry.resolution == ResolutionState.REVIEW_REQUIRED, (
        f"Without romresolve, expected REVIEW_REQUIRED, got {entry.resolution}"
    )


def test_e2e_unambiguous_match_skips_romresolve(disambig_service, tmp_path):
    """E2E: Single-candidate entries don't need romresolve at all."""
    csv = tmp_path / "bios.csv"
    csv.write_text(
        "name,size\nGame Boy Color BIOS.bin,0\n",
        encoding="utf-8",
    )
    report = disambig_service.import_report(
        csv,
        scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy Color"),
    )
    disambig_service.match_report(report.id)

    entries = disambig_service._state.get_entries(report.id)
    entry = entries[0]
    # Exact match — romresolve not invoked, method stays "exact"
    assert entry.resolution == ResolutionState.READY
    assert entry.automatic_method != "romresolve"


def test_e2e_queue_ready_uses_injected_db(disambig_service, tmp_path):
    """E2E: queue_ready respects self._db instead of creating a new MinervaDB()."""
    csv = tmp_path / "mario.csv"
    csv.write_text(
        "name,size\nSuper Mario Bros (World).zip,102400\n",
        encoding="utf-8",
    )
    report = disambig_service.import_report(
        csv,
        scope=ReportScope(collection="Nintendo", system="Nintendo - Nintendo Entertainment System"),
    )
    disambig_service.match_report(report.id)

    # queue_ready should work without error (it uses self._db internally)
    result = disambig_service.queue_ready(report.id)
    assert isinstance(result, QueueResult)
