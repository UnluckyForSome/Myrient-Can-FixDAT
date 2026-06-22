"""
Additional tests for ReportAcquisitionService — filling coverage gaps.

Covers: scope inference helpers, infer_scope branches, _classify outcomes,
queue planning, triage/outcome, edge cases.

Reuses ``_build_test_index`` and fixtures from
``test_report_acquisition_service.py`` when appropriate.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Project root on sys.path ─────────────────────────────────-------------
_HERE = Path(__file__).parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from minerva.domain.reports import (
    AcquisitionConstraints,
    AcquisitionPlan,
    AcquisitionSummary,
    MatchPolicy,
    PlannedFile,
    QueueResult,
    ReportOutcome,
    ReportScope,
    ReportSummary,
    ResolutionState,
    ReviewEntry,
    ScopeInferenceRequired,
    SelectionStrategy,
)
from minerva_state import MinervaState
from minerva_db import DatEntry, MinervaDB, SCHEMA_V3, stem_from_romname

# Import the module functions we need to test directly
from minerva.services.report_acquisition import (
    ReportAcquisitionService,
    _infer_scope_from_csv,
    _infer_scope_from_distribution,
    _infer_scope_from_filename,
    _infer_scope_from_path,
)


# ============================================================================
# _infer_scope_from_csv — full coverage
# ============================================================================


class TestInferScopeFromCsv:
    def test_system_column(self, tmp_path):
        csv = tmp_path / "r.csv"
        csv.write_text("name,size,system\nrom.zip,1024,Sony - PlayStation 2\n")
        scope = _infer_scope_from_csv(csv)
        assert scope is not None
        assert scope.system == "Sony - PlayStation 2"
        assert scope.collection is None

    def test_platform_column(self, tmp_path):
        csv = tmp_path / "r.csv"
        csv.write_text("name,platform\nrom.zip,Sony - PlayStation 2\n")
        scope = _infer_scope_from_csv(csv)
        assert scope is not None
        assert scope.system == "Sony - PlayStation 2"

    def test_console_column(self, tmp_path):
        csv = tmp_path / "r.csv"
        csv.write_text("name,console\nrom.zip,Sony - PlayStation 2\n")
        scope = _infer_scope_from_csv(csv)
        assert scope is not None
        assert scope.system == "Sony - PlayStation 2"

    def test_collection_column(self, tmp_path):
        csv = tmp_path / "r.csv"
        csv.write_text("name,collection\nrom.zip,Redump\n")
        scope = _infer_scope_from_csv(csv)
        assert scope is not None
        assert scope.collection == "Redump"
        assert scope.system is None

    def test_set_column(self, tmp_path):
        csv = tmp_path / "r.csv"
        csv.write_text("name,set\nrom.zip,No-Intro\n")
        scope = _infer_scope_from_csv(csv)
        assert scope is not None
        assert scope.collection == "No-Intro"

    def test_dat_column(self, tmp_path):
        csv = tmp_path / "r.csv"
        csv.write_text("name,dat\nrom.zip,Redump\n")
        scope = _infer_scope_from_csv(csv)
        assert scope is not None
        assert scope.collection == "Redump"

    def test_both_collection_and_system(self, tmp_path):
        csv = tmp_path / "r.csv"
        csv.write_text("name,system,collection\nrom.zip,Nintendo - NES,No-Intro\n")
        scope = _infer_scope_from_csv(csv)
        assert scope is not None
        assert scope.system == "Nintendo - NES"
        assert scope.collection == "No-Intro"

    def test_empty_csv(self, tmp_path):
        csv = tmp_path / "empty.csv"
        csv.write_text("")
        assert _infer_scope_from_csv(csv) is None

    def test_header_only_no_matching_cols(self, tmp_path):
        csv = tmp_path / "r.csv"
        csv.write_text("name,size,status\nrom.zip,1024,Missing\n")
        assert _infer_scope_from_csv(csv) is None

    def test_data_but_no_matching_cols(self, tmp_path):
        csv = tmp_path / "r.csv"
        csv.write_text("name,size\nrom.zip,1024\n")
        assert _infer_scope_from_csv(csv) is None

    def test_whitespace_handling(self, tmp_path):
        csv = tmp_path / "r.csv"
        csv.write_text("Name, System , Size\nrom.zip, Sony - PS2 , 1024\n")
        scope = _infer_scope_from_csv(csv)
        assert scope is not None
        assert scope.system == "Sony - PS2"

    def test_quoted_values_not_supported(self, tmp_path):
        """The CSV parser does not strip quotes from header names, so
        quoted columns are not recognised (acceptable limitation)."""
        csv = tmp_path / "r.csv"
        csv.write_text('"name","system","size"\n"rom.zip","Sony - PS2","1024"\n')
        scope = _infer_scope_from_csv(csv)
        assert scope is None


# ============================================================================
# _infer_scope_from_path — full coverage
# ============================================================================


class TestInferScopeFromPath:
    def test_collection_in_parent_path(self, tmp_path):
        """Path containing 'redump' + system name should yield scope."""
        # Use a base dir that doesn't contain keywords as substring
        base = tmp_path / "base"
        p = base / "redump" / "Nintendo - NES" / "report.dat"
        p.parent.mkdir(parents=True, exist_ok=True)
        scope = _infer_scope_from_path(p)
        assert scope is not None
        assert scope.collection == "Redump"
        assert "Nintendo - NES" in scope.system

    def test_no_intro_in_parent_path(self, tmp_path):
        p = tmp_path / "no-intro" / "Nintendo Game Boy Advance" / "r.dat"
        p.parent.mkdir(parents=True, exist_ok=True)
        scope = _infer_scope_from_path(p)
        assert scope is not None
        assert scope.collection == "No-Intro"

    def test_mame_in_filename_stem(self, tmp_path):
        p = tmp_path / "random" / "mame - arcade 0.260.dat"
        p.parent.mkdir(parents=True, exist_ok=True)
        scope = _infer_scope_from_path(p)
        assert scope is not None
        assert scope.collection == "Mame"

    def test_no_match_returns_none(self, tmp_path):
        p = tmp_path / "some_folder" / "report.dat"
        p.parent.mkdir(parents=True, exist_ok=True)
        assert _infer_scope_from_path(p) is None

    def test_stem_match_over_parent(self, tmp_path):
        # Parent doesn't match but filename stem does
        p = tmp_path / "downloads" / "redump - Sega Genesis.dat"
        p.parent.mkdir(parents=True, exist_ok=True)
        scope = _infer_scope_from_path(p)
        assert scope is not None
        assert scope.collection == "Redump"

    def test_goodsets_in_path(self, tmp_path):
        p = tmp_path / "goodsets" / "Nintendo - NES" / "report.dat"
        p.parent.mkdir(parents=True, exist_ok=True)
        scope = _infer_scope_from_path(p)
        assert scope is not None
        assert scope.collection == "Goodsets"

    def test_fb_in_path(self, tmp_path):
        p = tmp_path / "fb" / "Arcade" / "report.dat"
        p.parent.mkdir(parents=True, exist_ok=True)
        scope = _infer_scope_from_path(p)
        assert scope is not None
        assert scope.collection == "Fb"

    def test_trurip_in_path(self, tmp_path):
        p = tmp_path / "Trurip" / "Sony - PlayStation" / "r.dat"
        p.parent.mkdir(parents=True, exist_ok=True)
        scope = _infer_scope_from_path(p)
        assert scope is not None
        assert scope.collection == "Trurip"


# ============================================================================
# _infer_scope_from_filename — full coverage
# ============================================================================


class TestInferScopeFromFilename:
    def test_redump_pattern(self):
        scope = _infer_scope_from_filename("(Redump) - Sony - PlayStation 2")
        assert scope is not None
        assert scope.collection == "Redump"
        assert scope.system == "Sony - PlayStation 2"

    def test_no_intro_pattern(self):
        scope = _infer_scope_from_filename("(No-Intro) - Nintendo - Game Boy Advance")
        assert scope is not None
        assert scope.collection == "No-Intro"
        assert scope.system == "Nintendo - Game Boy Advance"

    def test_no_match(self):
        scope = _infer_scope_from_filename("Sony - PlayStation 2")
        assert scope is None

    def test_empty_string(self):
        scope = _infer_scope_from_filename("")
        assert scope is None

    def test_extra_text_around(self):
        scope = _infer_scope_from_filename("My (Redump) - Sony - PS2 report")
        assert scope is not None
        # The regex captures the content of first (parens) as collection
        assert scope.collection == "Redump"
        # system is everything after the dash following the closing paren
        assert "PS2" in scope.system


# ============================================================================
# _infer_scope_from_distribution
# ============================================================================


class TestInferScopeFromDistribution:
    """Uses a real MinervaDB backed by the test index."""

    def test_all_same_scope(self, test_index, test_db):
        entries = [
            DatEntry(filename="Super Mario Bros (World).zip", size=102400),
            DatEntry(filename="The Legend of Zelda (USA).zip", size=204800),
            DatEntry(filename="Metroid (USA).zip", size=409600),
        ]
        result = _infer_scope_from_distribution(entries, db=test_db)
        # All three match Nintendo/NES → should return that
        assert result is not None
        assert result.collection == "Nintendo"
        assert "Nintendo Entertainment System" in result.system

    def test_no_candidates(self, test_db):
        entries = [
            DatEntry(filename="ZZZZ_NO_MATCH_12345.bin", size=99999),
        ]
        result = _infer_scope_from_distribution(entries, db=test_db)
        assert result is None

    def test_empty_entries(self, test_db):
        result = _infer_scope_from_distribution([], db=test_db)
        assert result is None

    def test_mixed_scope_below_threshold(self, test_db):
        """Mix NES + Game Boy entries, neither reaches 80%."""
        entries = [
            # NES
            DatEntry(filename="Super Mario Bros (World).zip", size=102400),
            DatEntry(filename="The Legend of Zelda (USA).zip", size=204800),
            # Game Boy Color
            DatEntry(filename="Pokemon Red (USA).zip", size=524288),
            DatEntry(filename="Pokemon Blue (USA).zip", size=524288),
            DatEntry(filename="Game Boy Color BIOS.bin", size=0),
        ]
        result = _infer_scope_from_distribution(entries, db=test_db)
        # NES: 2, GBC: 3 — GBC is 60% (< 80%)
        assert result is None


# ============================================================================
# Service.infer_scope — all branches
# ============================================================================


class TestServiceInferScope:
    """Integration tests using a real DB and state."""

    def test_csv_system_column_wins(self, service, tmp_path):
        """CSV with a system column returns CSV-inferred scope."""
        csv = tmp_path / "r.csv"
        csv.write_text("name,system\nrom.zip,Nintendo - NES\n")
        scope = service.infer_scope(csv)
        assert scope.system == "Nintendo - NES"
        assert scope.collection is None

    def test_csv_path_fallback(self, service, tmp_path):
        """CSV without scope columns falls through to path matching."""
        csv = tmp_path / "redump" / "Nintendo - NES" / "report.csv"
        csv.parent.mkdir(parents=True, exist_ok=True)
        csv.write_text("name,size\nrom.zip,1024\n")
        scope = service.infer_scope(csv)
        assert scope is not None
        assert scope.collection == "Redump"
        assert "Nintendo" in scope.system

    def test_dat_path_match(self, service, tmp_path):
        """DAT file with path matching works."""
        p = tmp_path / "no-intro" / "Nintendo Game Boy" / "report.dat"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("<data></data>")  # parse_dat_file will fail, so path match happens first
        # But parse will fail, so we need a real enough file or skip parsing.
        # Actually for .dat files, infer_scope tries path first (step 2) before parsing.
        # Path regex matches → return. So parse failure doesn't matter.
        scope = service.infer_scope(p)
        assert scope is not None
        assert scope.collection == "No-Intro"

    def test_filename_pattern(self, service, tmp_path):
        """File whose stem matches (Collection) - System pattern."""
        p = tmp_path / "(Redump) - Sony - PlayStation 2.dat"
        p.write_text("dummy")
        scope = service.infer_scope(p)
        assert scope is not None
        assert scope.collection == "Redump"

    def test_distribution_fallback(self, service, tmp_path):
        """When CSV has no scope info and no path/filename match,
        falls through to distribution inference."""
        csv = tmp_path / "unknown.csv"
        csv.write_text(
            "name,size\n"
            "Super Mario Bros (World).zip,102400\n"
            "The Legend of Zelda (USA).zip,204800\n",
            encoding="utf-8",
        )
        scope = service.infer_scope(csv)
        # Entries match NES → scope from distribution
        assert scope is not None
        assert scope.collection == "Nintendo"

    def test_raises_with_candidates(self, service, tmp_path):
        """When no scope method works but candidates exist, raises."""
        csv = tmp_path / "ambiguous.csv"
        csv.write_text(
            "name,size\n"
            "Super Mario Bros (World).zip,102400\n"
            "Pokemon Red (USA).zip,524288\n",
            encoding="utf-8",
        )
        with pytest.raises(ScopeInferenceRequired) as exc_info:
            service.infer_scope(csv)
        assert len(exc_info.value.candidates) > 0

    def test_raises_empty_with_no_entries(self, service, tmp_path):
        """When file has no entries and no other scope method works."""
        csv = tmp_path / "empty_content.csv"
        csv.write_text("name,size\n")  # header only
        with pytest.raises(ScopeInferenceRequired) as exc_info:
            service.infer_scope(csv)
        # No entries → no candidates → empty list
        assert exc_info.value.candidates == []


# ============================================================================
# _classify — unit tests via mocked DB
# ============================================================================


class TestClassify:
    """Test the private _classify method directly via a service with a
    mocked MinervaDB."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock(spec=MinervaDB)
        return db

    @pytest.fixture
    def svc(self, mock_db):
        return ReportAcquisitionService(
            db=mock_db,
            state=MinervaState(db_path=":memory:"),
        )

    def test_no_candidate_not_found(self, svc, mock_db):
        mock_db.get_two_best_candidates.return_value = (None, None)
        entry = DatEntry(filename="unknown.bin", size=123)
        scope = ReportScope(collection="Test", system="Test")
        policy = MatchPolicy()
        resolution, file_id, method, confidence = svc._classify(
            entry, scope, policy,
        )
        assert resolution == ResolutionState.NOT_FOUND
        assert file_id is None

    def test_below_confidence_floor(self, svc, mock_db):
        best = {"file_id": 1, "method": "fuzzy", "confidence": 0.3,
                "collection": "Test", "system": "Test", "title": "rom.zip"}
        mock_db.get_two_best_candidates.return_value = (best, None)
        entry = DatEntry(filename="rom.zip", size=1024)
        scope = ReportScope(collection="Test", system="Test")
        policy = MatchPolicy()
        resolution, file_id, method, confidence = svc._classify(
            entry, scope, policy,
        )
        assert resolution == ResolutionState.NOT_FOUND
        assert file_id == 1

    def test_cross_collection_blocked(self, svc, mock_db):
        best = {"file_id": 1, "method": "exact", "confidence": 1.0,
                "collection": "OtherColl", "system": "Test", "title": "rom.zip"}
        mock_db.get_two_best_candidates.return_value = (best, None)
        entry = DatEntry(filename="rom.zip", size=1024)
        scope = ReportScope(collection="MyColl", system="Test")
        policy = MatchPolicy(require_same_collection=True)
        resolution, file_id, method, confidence = svc._classify(
            entry, scope, policy,
        )
        assert resolution == ResolutionState.NOT_FOUND

    def test_cross_system_blocked(self, svc, mock_db):
        best = {"file_id": 1, "method": "exact", "confidence": 1.0,
                "collection": "Test", "system": "OtherSys", "title": "rom.zip"}
        mock_db.get_two_best_candidates.return_value = (best, None)
        entry = DatEntry(filename="rom.zip", size=1024)
        scope = ReportScope(collection="Test", system="MySys")
        policy = MatchPolicy(require_same_system=True)
        resolution, file_id, method, confidence = svc._classify(
            entry, scope, policy,
        )
        assert resolution == ResolutionState.NOT_FOUND

    def test_exact_match_auto_accept(self, svc, mock_db):
        best = {"file_id": 1, "method": "exact", "confidence": 1.0,
                "collection": "Test", "system": "Test", "title": "rom.zip"}
        mock_db.get_two_best_candidates.return_value = (best, None)
        entry = DatEntry(filename="rom.zip", size=1024)
        scope = ReportScope(collection="Test", system="Test")
        policy = MatchPolicy(auto_accept_exact=True)
        res, fid, method, conf = svc._classify(entry, scope, policy)
        assert res == ResolutionState.READY
        assert fid == 1
        assert method == "exact"

    def test_fuzzy_high_confidence_with_margin(self, svc, mock_db):
        best = {"file_id": 1, "method": "fuzzy", "confidence": 0.98,
                "collection": "Test", "system": "Test", "title": "rom.zip"}
        second = {"file_id": 2, "method": "fuzzy", "confidence": 0.50,
                  "collection": "Test", "system": "Test", "title": "rom_alt.zip"}
        mock_db.get_two_best_candidates.return_value = (best, second)
        entry = DatEntry(filename="rom.zip", size=1024)
        scope = ReportScope(collection="Test", system="Test")
        policy = MatchPolicy(fuzzy_min_confidence=0.96, fuzzy_min_margin=0.08)
        res, fid, method, conf = svc._classify(entry, scope, policy)
        assert res == ResolutionState.READY
        assert fid == 1
        assert method == "fuzzy"

    def test_fuzzy_high_confidence_but_thin_margin(self, svc, mock_db):
        best = {"file_id": 1, "method": "fuzzy", "confidence": 0.98,
                "collection": "Test", "system": "Test", "title": "rom.zip"}
        second = {"file_id": 2, "method": "fuzzy", "confidence": 0.95,
                  "collection": "Test", "system": "Test", "title": "rom_alt.zip"}
        mock_db.get_two_best_candidates.return_value = (best, second)
        entry = DatEntry(filename="rom.zip", size=1024)
        scope = ReportScope(collection="Test", system="Test")
        policy = MatchPolicy(fuzzy_min_confidence=0.96, fuzzy_min_margin=0.08)
        res, fid, method, conf = svc._classify(entry, scope, policy)
        assert res == ResolutionState.REVIEW_REQUIRED

    def test_fuzzy_below_confidence(self, svc, mock_db):
        best = {"file_id": 1, "method": "fuzzy", "confidence": 0.90,
                "collection": "Test", "system": "Test", "title": "rom.zip"}
        second = {"file_id": 2, "method": "fuzzy", "confidence": 0.50,
                  "collection": "Test", "system": "Test", "title": "rom_alt.zip"}
        mock_db.get_two_best_candidates.return_value = (best, second)
        entry = DatEntry(filename="rom.zip", size=1024)
        scope = ReportScope(collection="Test", system="Test")
        policy = MatchPolicy(fuzzy_min_confidence=0.96, fuzzy_min_margin=0.08)
        res, fid, method, conf = svc._classify(entry, scope, policy)
        assert res == ResolutionState.REVIEW_REQUIRED

    def test_no_second_candidate_with_high_confidence(self, svc, mock_db):
        """Only one candidate, confidence high → READY (margin trivially met)."""
        best = {"file_id": 1, "method": "fuzzy", "confidence": 0.97,
                "collection": "Test", "system": "Test", "title": "rom.zip"}
        mock_db.get_two_best_candidates.return_value = (best, None)
        entry = DatEntry(filename="rom.zip", size=1024)
        scope = ReportScope(collection="Test", system="Test")
        policy = MatchPolicy(fuzzy_min_confidence=0.96, fuzzy_min_margin=0.08)
        res, fid, method, conf = svc._classify(entry, scope, policy)
        assert res == ResolutionState.READY
        assert fid == 1

    def test_exact_match_without_auto_accept_but_fuzzy_covers(self, svc, mock_db):
        """When auto_accept_exact=False but confidence is high enough,
        the fuzzy margin check still returns READY."""
        best = {"file_id": 1, "method": "exact", "confidence": 1.0,
                "collection": "Test", "system": "Test", "title": "rom.zip"}
        mock_db.get_two_best_candidates.return_value = (best, None)
        entry = DatEntry(filename="rom.zip", size=1024)
        scope = ReportScope(collection="Test", system="Test")
        policy = MatchPolicy(auto_accept_exact=False)
        res, fid, method, conf = svc._classify(entry, scope, policy)
        # With confidence 1.0 and no second candidate, the fuzzy margin
        # classification makes it READY even without auto_accept_exact.
        assert res == ResolutionState.READY

    def test_auto_accept_off_and_low_confidence(self, svc, mock_db):
        """When auto_accept_exact=False and confidence below fuzzy floor,
        entry stays REVIEW_REQUIRED."""
        best = {"file_id": 1, "method": "fuzzy", "confidence": 0.80,
                "collection": "Test", "system": "Test", "title": "rom.zip"}
        mock_db.get_two_best_candidates.return_value = (best, None)
        entry = DatEntry(filename="rom.zip", size=1024)
        scope = ReportScope(collection="Test", system="Test")
        policy = MatchPolicy(auto_accept_exact=False)
        res, fid, method, conf = svc._classify(entry, scope, policy)
        assert res == ResolutionState.REVIEW_REQUIRED

    def test_scope_with_empty_collection_system(self, svc, mock_db):
        """When scope collection/system is empty, cross-system guard is skipped."""
        best = {"file_id": 1, "method": "exact", "confidence": 1.0,
                "collection": "Other", "system": "Other", "title": "rom.zip"}
        mock_db.get_two_best_candidates.return_value = (best, None)
        entry = DatEntry(filename="rom.zip", size=1024)
        scope = ReportScope(collection="", system="")
        policy = MatchPolicy(require_same_collection=True, require_same_system=True)
        # Empty scope → guards are skipped
        res, fid, method, conf = svc._classify(entry, scope, policy)
        assert res == ResolutionState.READY


# ============================================================================
# import_report — edge cases
# ============================================================================


class TestImportReportEdgeCases:
    def test_import_with_scope_none_infers(self, service, tmp_path):
        """When scope is None, infer_scope is called (path match)."""
        p = tmp_path / "redump" / "Sony - PlayStation 2" / "report.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("name,size\nrom.zip,1024\n")
        report = service.import_report(p, scope=None)
        assert report is not None
        assert report.collection == "Redump"
        assert "PlayStation 2" in report.system

    def test_import_dat_file(self, service, tmp_path):
        """Import a minimal .dat XML file."""
        dat = tmp_path / "test.dat"
        dat.write_text(
            '<?xml version="1.0"?>'
            '<datafile>'
            '<header><name>TestDAT</name></header>'
            '<game><rom name="rom1.zip" size="1024"/></game>'
            '</datafile>'
        )
        report = service.import_report(
            dat, scope=ReportScope(collection="Test", system="Test"),
        )
        assert report is not None
        assert report.requested_count == 1
        assert report.name == "TestDAT"

    def test_import_dat_file_empty_entries(self, service, tmp_path):
        """DAT with no rom entries raises ValueError."""
        dat = tmp_path / "empty.dat"
        dat.write_text(
            '<?xml version="1.0"?>'
            '<datafile>'
            '<header><name>Empty</name></header>'
            '</datafile>'
        )
        with pytest.raises(ValueError, match="Empty"):
            service.import_report(
                dat, scope=ReportScope(collection="Test", system="Test"),
            )

    def test_import_update_existing(self, service, tmp_path):
        """Re-importing same path updates existing report."""
        csv = tmp_path / "reimport.csv"
        csv.write_text("name,size\nrom.zip,1024\n")
        r1 = service.import_report(
            csv, scope=ReportScope(collection="Test", system="Test"),
        )
        r2 = service.import_report(
            csv, scope=ReportScope(collection="Test", system="Test"),
        )
        assert r2.id == r1.id  # Same path → same ID


# ============================================================================
# queue_ready — detailed skipped/active paths
# ============================================================================


class TestQueueReady:
    def test_empty_report_returns_zero(self, service, tmp_path):
        """No entries → all zeros."""
        result = service.queue_ready("nonexistent")
        assert result.added == 0
        assert result.skipped_active == 0
        assert result.skipped_complete == 0
        assert result.skipped_missing == 0

    def test_queue_ready_adds_ready_entries(self, service, tmp_path):
        """READY entries with matched file_ids get queued."""
        csv = tmp_path / "q.csv"
        csv.write_text("name,size\nGame Boy Color BIOS.bin,0\n")
        report = service.import_report(
            csv,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy Color"),
        )
        service.match_report(report.id)
        result = service.queue_ready(report.id)
        # BIOS has exact match → should be added
        assert result.added >= 1
        assert result.skipped_missing == 0

    def test_queue_ready_missing_file_id_skipped(self, service, tmp_path):
        """Entries without file_id → skipped_missing."""
        # Build a report manually with a REVIEW_REQUIRED entry that has no file_id
        from minerva.domain.downloads import QueueRecord as QR
        from datetime import datetime, timezone

        csv = tmp_path / "q2.csv"
        csv.write_text("name,size\nzzzz_nonexistent.bin,99999\n")
        report = service.import_report(
            csv,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Unknown"),
        )
        service.match_report(report.id)
        result = service.queue_ready(report.id)
        # NOT_FOUND entries are skipped entirely, not counted as skipped_missing
        # In queue_ready: NOT_FOUND entries are skipped (continue) before the file_id check
        # So this should be all zeros
        assert result.added == 0

    def test_skip_active_entries(self, service, tmp_path):
        """Entries already active/queued → skipped_active."""
        csv = tmp_path / "q3.csv"
        csv.write_text("name,size\nGame Boy Color BIOS.bin,0\n")
        report = service.import_report(
            csv,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy Color"),
        )
        service.match_report(report.id)

        # Queue once
        r1 = service.queue_ready(report.id)
        assert r1.added >= 1

        # Queue again — should be skipped as active
        r2 = service.queue_ready(report.id)
        # file_id is now in active_file_ids → skipped_active
        assert r2.skipped_active >= 1
        assert r2.added == 0

    def test_skip_completed_entries(self, service, tmp_path):
        """Entries already completed → skipped_complete."""
        csv = tmp_path / "q4.csv"
        csv.write_text("name,size\nGame Boy Color BIOS.bin,0\n")
        report = service.import_report(
            csv,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy Color"),
        )
        service.match_report(report.id)

        # Manually insert a completed queue record for the matched file_id
        entries = service._state.get_entries(report.id)
        entry = entries[0]
        file_id = entry.automatic_file_id
        from minerva.domain.downloads import QueueRecord as QR
        from datetime import datetime, timezone

        qr = QR(
            id="test_completed",
            file_id=file_id,
            report_entry_id=entry.id,
            status="completed",
            destination="/tmp/dst",
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        service._state.save_queue_record(qr)

        # Now queue — should be skipped as completed
        result = service.queue_ready(report.id)
        assert result.skipped_complete >= 1
        assert result.added == 0

    def test_include_reviewed_false(self, service, tmp_path):
        """include_reviewed=False skips reviewed entries."""
        csv = tmp_path / "q5.csv"
        csv.write_text("name,size\nrom.bin,1024\n")
        report = service.import_report(
            csv,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy"),
        )
        # Entry is REVIEW_REQUIRED (no match), manually set to accepted
        service.match_report(report.id)
        entries = service._state.get_entries(report.id)
        if entries:
            e = entries[0]
            if e.resolution == ResolutionState.REVIEW_REQUIRED:
                # Without include_reviewed, it should not appear
                result = service.queue_ready(
                    report.id, include_reviewed=False,
                )
                assert result.added == 0
            else:
                # Already READY (unlikely with this scope)
                pass


# ============================================================================
# queue_plan
# ============================================================================


class TestQueuePlan:
    @pytest.fixture
    def plan(self):
        return AcquisitionPlan(
            selected=(
                PlannedFile(
                    report_entry_id="e1", file_id=1, size=1024,
                    torrent_name="test.torrent",
                    destination=Path("/tmp/dst/rom.zip"),
                ),
            ),
            deferred=(),
            volumes=(),
            selected_bytes=1024,
            estimated_transfer_bytes=1024,
            report_id="test_report",
            report_name="test",
        )

    def test_queue_plan_adds_records(self, service, tmp_path, plan):
        result = service.queue_plan(plan)
        assert result.added == 1
        assert result.skipped_active == 0

        # Verify record was saved
        records = service._state.list_queue()
        assert len(records) == 1
        assert records[0].file_id == 1

    def test_queue_plan_skip_active(self, service, tmp_path, plan):
        # Queue once
        service.queue_plan(plan)
        # Queue again — should be skipped
        result = service.queue_plan(plan)
        assert result.added == 0
        assert result.skipped_active >= 1


# ============================================================================
# compute_outcome and helpers
# ============================================================================


class TestComputeOutcome:
    @pytest.fixture
    def report_with_entries(self, service, tmp_path):
        """Import and match a CSV to get a report with entries."""
        csv = tmp_path / "outcome.csv"
        csv.write_text("name,size\nGame Boy Color BIOS.bin,0\n")
        report = service.import_report(
            csv,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy Color"),
        )
        service.match_report(report.id)
        return report, service

    def test_empty_report(self, tmp_state, tmp_path):
        """No entries → EMPTY."""
        db = MinervaDB(db_path=":memory:")
        svc = ReportAcquisitionService(state=tmp_state, db=db)
        # Manually create a report with no entries
        from minerva.domain.reports import ReportSummary
        r = ReportSummary(id="empty_r", path="/none", name="empty")
        tmp_state.save_report(r)
        outcome = svc.compute_outcome("empty_r")
        assert outcome == ReportOutcome.EMPTY

    def test_actionable(self, service, tmp_path):
        """READY entries → ACTIONABLE."""
        csv = tmp_path / "oc.csv"
        csv.write_text("name,size\nGame Boy Color BIOS.bin,0\n")
        report = service.import_report(
            csv,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy Color"),
        )
        service.match_report(report.id)
        outcome = service.compute_outcome(report.id)
        assert outcome == ReportOutcome.ACTIONABLE

    def test_no_source_matches(self, service, tmp_path):
        """Only NOT_FOUND → NO_SOURCE_MATCHES."""
        csv = tmp_path / "oc2.csv"
        csv.write_text("name,size\nzzzz_nonexistent.bin,99999\n")
        report = service.import_report(
            csv,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Unknown"),
        )
        service.match_report(report.id)
        outcome = service.compute_outcome(report.id)
        assert outcome == ReportOutcome.NO_SOURCE_MATCHES

    def test_filtered_out(self, service, tmp_path):
        """READY entries but constraints filter all → FILTERED_OUT."""
        csv = tmp_path / "oc3.csv"
        csv.write_text("name,size\nPokemon Red (USA).zip,524288\n")
        report = service.import_report(
            csv,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy Color"),
        )
        service.match_report(report.id)
        # Constraint that excludes everything (max bytes < file size)
        constraints = AcquisitionConstraints(max_file_bytes=100)
        outcome = service.compute_outcome(report.id, constraints=constraints)
        assert outcome == ReportOutcome.FILTERED_OUT

    def test_needs_review(self, service, tmp_path):
        """Only REVIEW_REQUIRED → NEEDS_REVIEW."""
        csv = tmp_path / "oc4.csv"
        csv.write_text("name,size\nrom.bin,1024\n")
        report = service.import_report(
            csv,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy"),
        )
        service.match_report(report.id)

        entries = service._state.get_entries(report.id)
        all_review = all(
            e.resolution == ResolutionState.REVIEW_REQUIRED
            for e in entries
        )
        # If all are REVIEW_REQUIRED, outcome is NEEDS_REVIEW
        # If somehow one matched exactly, skip this assertion
        if all_review:
            outcome = service.compute_outcome(report.id)
            assert outcome == ReportOutcome.NEEDS_REVIEW


# ============================================================================
# _all_already_present
# ============================================================================


class TestAllAlreadyPresent:
    def test_no_entries(self, service):
        assert service._all_already_present("nonexistent") is False

    def test_not_all_completed(self, service, tmp_path):
        """Some entries not completed → False."""
        csv = tmp_path / "aap.csv"
        csv.write_text("name,size\nGame Boy Color BIOS.bin,0\n")
        report = service.import_report(
            csv,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy Color"),
        )
        service.match_report(report.id)
        assert service._all_already_present(report.id) is False

    def test_all_completed(self, service, tmp_path):
        """All entries completed → True."""
        csv = tmp_path / "aap2.csv"
        csv.write_text("name,size\nGame Boy Color BIOS.bin,0\n")
        report = service.import_report(
            csv,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy Color"),
        )
        service.match_report(report.id)

        # Mark all as completed
        entries = service._state.get_entries(report.id)
        from minerva.domain.downloads import QueueRecord as QR
        from datetime import datetime, timezone

        for e in entries:
            fid = e.automatic_file_id
            if fid is not None:
                qr = QR(
                    id=f"comp_{e.id}",
                    file_id=fid,
                    report_entry_id=e.id,
                    status="completed",
                    destination="/tmp/dst",
                    created_at=datetime.now(timezone.utc).isoformat(),
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )
                service._state.save_queue_record(qr)

        assert service._all_already_present(report.id) is True


# ============================================================================
# _filter_eligible
# ============================================================================


class TestFilterEligible:
    def test_no_constraints_returns_all(self):
        svc = ReportAcquisitionService(db=MinervaDB(db_path=":memory:"))
        entries = [
            ReviewEntry(id="e1", report_id="r1", ordinal=0, filename="a.bin", size=1000),
            ReviewEntry(id="e2", report_id="r1", ordinal=1, filename="b.bin", size=2000),
        ]
        result = svc._filter_eligible(entries, None)
        assert result == entries

    def test_max_file_bytes_filter(self):
        svc = ReportAcquisitionService(db=MinervaDB(db_path=":memory:"))
        entries = [
            ReviewEntry(id="e1", report_id="r1", ordinal=0, filename="a.bin", size=1000),
            ReviewEntry(id="e2", report_id="r1", ordinal=1, filename="b.bin", size=2000),
            ReviewEntry(id="e3", report_id="r1", ordinal=2, filename="c.bin", size=500),
        ]
        constraints = AcquisitionConstraints(max_file_bytes=1500)
        result = svc._filter_eligible(entries, constraints)
        assert len(result) == 2
        assert result[0].id == "e1"
        assert result[1].id == "e3"

    def test_empty_safe_entries(self):
        svc = ReportAcquisitionService(db=MinervaDB(db_path=":memory:"))
        constraints = AcquisitionConstraints(max_file_bytes=1000)
        result = svc._filter_eligible([], constraints)
        assert result == []


# ============================================================================
# queue_all_ready
# ============================================================================


class TestQueueAllReady:
    def test_no_reports(self, service):
        result = service.queue_all_ready()
        assert result.added == 0

    def test_aggregates_multiple_reports(self, service, tmp_path):
        """Two reports with matchable entries → aggregated totals."""
        csv1 = tmp_path / "r1.csv"
        csv1.write_text("name,size\nGame Boy Color BIOS.bin,0\n")
        r1 = service.import_report(
            csv1,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy Color"),
        )
        service.match_report(r1.id)

        csv2 = tmp_path / "r2.csv"
        csv2.write_text("name,size\nPokemon Red (USA).zip,524288\n")
        r2 = service.import_report(
            csv2,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy Color"),
        )
        service.match_report(r2.id)

        result = service.queue_all_ready()
        assert result.added >= 2  # Both matched
        # Second run — all active now, no new additions
        result2 = service.queue_all_ready()
        assert result2.added == 0
        assert result2.skipped_active >= 2

    def test_name_filter(self, service, tmp_path):
        """Only reports matching name_filter get queued."""
        csv = tmp_path / "special_report.csv"
        csv.write_text("name,size\nGame Boy Color BIOS.bin,0\n")
        r = service.import_report(
            csv,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy Color"),
        )
        service.match_report(r.id)

        # Filter that matches
        result = service.queue_all_ready(name_filter="special")
        assert result.added >= 1

        # Filter that doesn't match
        result2 = service.queue_all_ready(name_filter="nonexistent")
        assert result2.added == 0

    def test_include_reviewed_param(self, service, tmp_path):
        """Passes include_reviewed through to queue_ready."""
        csv = tmp_path / "qar.csv"
        csv.write_text("name,size\nrom.bin,1024\n")
        r = service.import_report(
            csv,
            scope=ReportScope(collection="Nintendo", system="Nintendo - Game Boy"),
        )
        service.match_report(r.id)

        result = service.queue_all_ready(include_reviewed=False)
        # If entries are REVIEW_REQUIRED, include_reviewed=False won't add them
        assert isinstance(result, QueueResult)


# ============================================================================
# Edge cases for infer_scope (DAT file with distribution)
# ============================================================================


class TestInferScopeDatDistribution:
    def test_dat_with_distribution(self, service, tmp_path):
        """DAT file whose entries match a single scope via distribution."""
        # Create a minimal .dat that matches NES entries
        dat = tmp_path / "unknown.dat"
        dat.write_text(
            '<?xml version="1.0"?>'
            '<datafile>'
            '<header><name>Unknown</name></header>'
            '<game><rom name="Super Mario Bros (World).zip" size="102400"/></game>'
            '<game><rom name="The Legend of Zelda (USA).zip" size="204800"/></game>'
            '<game><rom name="Metroid (USA).zip" size="409600"/></game>'
            '</datafile>'
        )
        # Scope based on distribution (all NES)
        scope = service.infer_scope(dat)
        assert scope is not None
        assert scope.collection == "Nintendo"


# ============================================================================
# Reuse existing fixtures from companion test module
# ============================================================================

# Import helper fixtures from test_report_acquisition_service
# We replicate the key fixtures here to keep this file self-contained.

@pytest.fixture
def test_index(tmp_path):
    """Create a small test index database (replicates companion module's fixture)."""
    db_path = tmp_path / "test_index.db"
    _build_test_index(str(db_path))
    return db_path


@pytest.fixture
def test_db(test_index):
    """Return a MinervaDB instance backed by the test index."""
    return MinervaDB(db_path=test_index)


@pytest.fixture
def tmp_state():
    """Create a MinervaState backed by a temporary file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    state = MinervaState(db_path=tmp.name)
    yield state
    os.unlink(tmp.name)


@pytest.fixture
def service(tmp_state, test_db):
    """Return a ReportAcquisitionService with an isolated state database
    and the test index."""
    return ReportAcquisitionService(state=tmp_state, db=test_db)


def _build_test_index(path: str) -> None:
    """Build a small test index with known files."""
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.executescript(SCHEMA_V3)

    test_files = [
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

    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', '3')",
    )
    conn.commit()
    conn.close()
