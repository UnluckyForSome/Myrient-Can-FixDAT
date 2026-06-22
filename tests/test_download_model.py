"""
Tests for ``DownloadTableModel`` — column spec conformance, data role
dispatch, mutation signals, and ``QAbstractItemModelTester``.
"""

from __future__ import annotations

from PyQt6 import QtCore
from PyQt6.QtCore import Qt

from minerva.domain.downloads import DownloadStatus
from minerva.ui.models.download_model import (
    _DOWNLOAD_COLUMNS,
    DownloadRecord,
    DownloadTableModel,
    format_eta,
    format_speed,
)

# ---------------------------------------------------------------------------
# ModelTester availability
# ---------------------------------------------------------------------------
try:
    from PyQt6.QtTest import QAbstractItemModelTester

    _HAVE_MODEL_TESTER = True
except ImportError:
    _HAVE_MODEL_TESTER = False


# ============================================================================
# Fixtures
# ============================================================================


def make_download(**overrides) -> DownloadRecord:
    """Factory helper — sensible defaults for ``DownloadRecord``."""
    defaults = dict(
        id=1,
        queue_id="abc123",
        filename="test.zip",
        url="https://example.com/test.zip",
        status=DownloadStatus.QUEUED,
        progress=0.0,
        speed=0.0,
        eta_seconds=0.0,
        error_message=None,
        started_at=None,
        completed_at=None,
        torrent_name="",
        peers=0,
        seeds=0,
        ratio=0.0,
    )
    defaults.update(overrides)
    return DownloadRecord(**defaults)


def make_model(records: list[DownloadRecord] | None = None) -> DownloadTableModel:
    """Return a ``DownloadTableModel`` with the given (or empty) records."""
    records = records or []
    return DownloadTableModel(records, _DOWNLOAD_COLUMNS)


# ============================================================================
# Column count and headers
# ============================================================================


def test_column_count():
    """GIVEN a DownloadTableModel WHEN columnCount is queried THEN it
    returns 8."""
    model = make_model()
    assert model.columnCount() == 8


def test_column_headers():
    """GIVEN a DownloadTableModel WHEN headerData is queried for each
    column THEN the headers match the spec."""
    model = make_model()
    expected = ["", "File", "Progress", "Speed", "ETA", "Seeds", "Ratio", "Actions"]
    for col, exp in enumerate(expected):
        header = model.headerData(
            col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole,
        )
        assert header == exp, f"Column {col}: expected {exp!r}, got {header!r}"


# ============================================================================
# Data role dispatch
# ============================================================================


def test_status_icon_in_status_column(qtbot):
    """GIVEN a model with a QUEUED download WHEN column 0 data is
    queried with DisplayRole THEN it returns a status icon string."""
    records = [make_download(status=DownloadStatus.QUEUED)]
    model = make_model(records)
    idx = model.index(0, 0)
    icon = idx.data(Qt.ItemDataRole.DisplayRole)
    assert isinstance(icon, str)
    assert len(icon) > 0


def test_filename_display(qtbot):
    """GIVEN a model with a download WHEN column 1 data is queried
    with DisplayRole THEN it returns the torrent/file name."""
    records = [make_download(torrent_name="my_rom.zip")]
    model = make_model(records)
    idx = model.index(0, 1)
    assert idx.data(Qt.ItemDataRole.DisplayRole) == "my_rom.zip"


def test_progress_user_role(qtbot):
    """GIVEN a model with a download at 50% WHEN column 2 data is
    queried with UserRole THEN it returns 0.5."""
    records = [make_download(progress=0.5)]
    model = make_model(records)
    idx = model.index(0, 2)
    assert idx.data(Qt.ItemDataRole.UserRole) == 0.5


def test_speed_display_downloading(qtbot):
    """GIVEN a DOWNLOADING record WHEN column 3 data is queried with
    DisplayRole THEN a formatted speed string is returned."""
    records = [make_download(status=DownloadStatus.DOWNLOADING, speed=2_097_152)]
    model = make_model(records)
    idx = model.index(0, 3)
    val = idx.data(Qt.ItemDataRole.DisplayRole)
    assert isinstance(val, str)
    assert "MB/s" in val or "KB/s" in val


def test_speed_display_not_downloading(qtbot):
    """GIVEN a QUEUED record WHEN column 3 data is queried with
    DisplayRole THEN an empty string is returned."""
    records = [make_download(status=DownloadStatus.QUEUED, speed=2_097_152)]
    model = make_model(records)
    idx = model.index(0, 3)
    assert idx.data(Qt.ItemDataRole.DisplayRole) == ""


def test_eta_display(qtbot):
    """GIVEN a DOWNLOADING record WHEN column 4 data is queried with
    DisplayRole THEN a formatted ETA string is returned."""
    records = [make_download(status=DownloadStatus.DOWNLOADING, eta_seconds=90)]
    model = make_model(records)
    idx = model.index(0, 4)
    val = idx.data(Qt.ItemDataRole.DisplayRole)
    assert isinstance(val, str)
    assert "1m" in val


def test_seeds_display(qtbot):
    """GIVEN a model WHEN column 5 data is queried with
    DisplayRole THEN the seed count string is returned."""
    records = [make_download(seeds=5)]
    model = make_model(records)
    idx = model.index(0, 5)
    assert idx.data(Qt.ItemDataRole.DisplayRole) == "5"


def test_ratio_display(qtbot):
    """GIVEN a model WHEN column 6 data is queried with
    DisplayRole THEN the ratio string is returned."""
    records = [make_download(ratio=1.5)]
    model = make_model(records)
    idx = model.index(0, 6)
    assert "1.50" in idx.data(Qt.ItemDataRole.DisplayRole)


def test_actions_user_role_returns_status(qtbot):
    """GIVEN a model WHEN column 7 data is queried with UserRole THEN
    the DownloadStatus enum is returned."""
    records = [make_download(status=DownloadStatus.COMPLETED)]
    model = make_model(records)
    idx = model.index(0, 7)
    status = idx.data(Qt.ItemDataRole.UserRole)
    assert status == DownloadStatus.COMPLETED


# ============================================================================
# Mutation signals
# ============================================================================


def test_set_records_emits_model_reset(qtbot):
    """GIVEN an empty model WHEN set_records is called THEN modelReset
    is emitted."""
    model = make_model()
    records = [make_download(id=1), make_download(id=2)]
    with qtbot.wait_signal(model.modelReset, timeout=500):
        model.set_records(records)
    assert model.rowCount() == 2


def test_set_records_clears_previous(qtbot):
    """GIVEN a model with 2 items WHEN set_records([]) is called THEN
    rowCount becomes 0."""
    model = make_model([make_download(id=1), make_download(id=2)])
    model.set_records([])
    assert model.rowCount() == 0


# ============================================================================
# QAbstractItemModelTester conformance
# ============================================================================


def test_modeltester_empty(qtbot):
    """GIVEN an empty model WHEN QAbstractItemModelTester checks THEN
    no warnings are emitted."""
    model = make_model()
    _run_modeltester(model)


def test_modeltester_populated(qtbot):
    """GIVEN a populated model WHEN QAbstractItemModelTester checks THEN
    no warnings are emitted."""
    records = [
        make_download(id=1, filename="a.zip"),
        make_download(id=2, filename="b.zip"),
        make_download(id=3, filename="c.zip"),
    ]
    model = make_model(records)
    _run_modeltester(model)


def _run_modeltester(model):
    """Run QAbstractItemModelTester or fallback conformance checks."""
    if _HAVE_MODEL_TESTER:
        tester = QAbstractItemModelTester(model)  # noqa: F841
        return

    # Fallback: minimal conformance
    assert model.rowCount() >= 0
    assert model.columnCount() >= 0
    from PyQt6.QtCore import QModelIndex

    assert model.data(QModelIndex()) is None


# ============================================================================
# Formatter unit tests
# ============================================================================


class TestFormatSpeed:
    """Unit tests for ``format_speed``."""

    def test_zero(self):
        assert format_speed(0) == "0 B/s"

    def test_bytes(self):
        assert format_speed(500) == "500 B/s"

    def test_kilobytes(self):
        assert format_speed(1024) == "1.0 KB/s"

    def test_megabytes(self):
        assert format_speed(1_048_576) == "1.0 MB/s"

    def test_gigabytes(self):
        assert format_speed(1_073_741_824) == "1.0 GB/s"

    def test_negative(self):
        assert format_speed(-1) == "0 B/s"


class TestFormatEta:
    """Unit tests for ``format_eta``."""

    def test_zero(self):
        assert format_eta(0) == "\u2014"

    def test_seconds_only(self):
        assert format_eta(30) == "30s"

    def test_minutes_seconds(self):
        assert format_eta(90) == "1m 30s"

    def test_hours_minutes(self):
        assert format_eta(7200) == "2h 0m"

    def test_negative(self):
        assert format_eta(-1) == "\u2014"
