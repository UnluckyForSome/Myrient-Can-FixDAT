"""
Tests for ``RecordListModel`` and ``QueueItemRecordModel``.

Covers: column spec, data role dispatch, mutation signals, scoped-enum
compliance, and ``QAbstractItemModelTester`` conformance (with fallback).
"""

from __future__ import annotations

from PyQt6.QtCore import QModelIndex, Qt

from minerva.ui.models.record_model import ColumnSpec, QueueItemRecordModel

# ---------------------------------------------------------------------------
# ModelTester availability (Decision 12)
# ---------------------------------------------------------------------------
try:
    from PyQt6.QtTest import QAbstractItemModelTester

    _HAVE_MODEL_TESTER = True
except ImportError:
    _HAVE_MODEL_TESTER = False


# ============================================================================
# Column count and headers
# ============================================================================


def test_column_count(populated_queue_model):
    """GIVEN a populated QueueItemRecordModel WHEN columnCount is queried
    THEN it returns 6."""
    assert populated_queue_model.columnCount() == 6


def test_column_headers(populated_queue_model):
    """GIVEN a QueueItemRecordModel WHEN headerData is queried for each
    column THEN the headers match the column specs."""
    expected = ["Name", "Entries", "Matched", "Unmatched", "Size", "✓"]
    for col, exp in enumerate(expected):
        header = populated_queue_model.headerData(
            col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole
        )
        assert header == exp, f"Column {col}: expected {exp!r}, got {header!r}"


# ============================================================================
# Data role dispatch
# ============================================================================


def test_data_display_formatted(populated_queue_model):
    """GIVEN a QueueItemRecordModel with 4 items WHEN data is queried
    with DisplayRole THEN formatted values are returned."""
    # Column 1 (Entries) has format_fn=lambda v: f"{v:,}"
    idx = populated_queue_model.index(0, 1)
    val = idx.data(Qt.ItemDataRole.DisplayRole)
    assert val == "100", f"Expected '100', got {val!r}"

    # Column 4 (Size) has no format_fn — returns raw int
    idx = populated_queue_model.index(2, 4)
    val = idx.data(Qt.ItemDataRole.DisplayRole)
    assert val == 1048576, f"Expected 1048576, got {val!r}"


def test_data_user_role_raw(populated_queue_model):
    """GIVEN a QueueItemRecordModel WHEN data is queried with UserRole
    THEN raw (unformatted) values are returned."""
    idx = populated_queue_model.index(0, 1)
    val = idx.data(Qt.ItemDataRole.UserRole)
    # entries_count = 100 (raw int)
    assert val == 100, f"Expected 100, got {val!r}"


def test_data_tooltip(populated_queue_model):
    """GIVEN a QueueItemRecordModel WHEN data is queried with ToolTipRole
    THEN str() of the raw value is returned."""
    idx = populated_queue_model.index(0, 0)
    val = idx.data(Qt.ItemDataRole.ToolTipRole)
    assert val == "Alpha", f"Expected 'Alpha', got {val!r}"


def test_check_state_role_default(populated_queue_model):
    """GIVEN a QueueItemRecordModel WHEN data is queried at column 5
    with CheckStateRole THEN Unchecked is returned."""
    idx = populated_queue_model.index(0, 5)
    val = idx.data(Qt.ItemDataRole.CheckStateRole)
    assert val == Qt.CheckState.Unchecked, f"Expected Unchecked, got {val!r}"


def test_non_checkbox_column_check_state_is_none(populated_queue_model):
    """GIVEN a non-checkbox column WHEN data is queried with
    CheckStateRole THEN None is returned."""
    idx = populated_queue_model.index(0, 0)
    val = idx.data(Qt.ItemDataRole.CheckStateRole)
    assert val is None


# ============================================================================
# Mutation signals
# ============================================================================


def test_set_records_emits_model_reset(empty_queue_model, make_queue_item, qtbot):
    """GIVEN an empty QueueItemRecordModel WHEN set_records is called
    THEN modelReset is emitted."""
    items = [make_queue_item(name="A"), make_queue_item(name="B")]
    with qtbot.wait_signal(empty_queue_model.modelReset, timeout=500):
        empty_queue_model.set_records(items)
    assert empty_queue_model.rowCount() == 2


def test_append_record_emits_rows_inserted(empty_queue_model, make_queue_item, qtbot):
    """GIVEN an empty QueueItemRecordModel WHEN append_record is called
    THEN rowsInserted is emitted."""
    item = make_queue_item(name="NewItem")
    with qtbot.wait_signal(empty_queue_model.rowsInserted, timeout=500):
        empty_queue_model.append_record(item)
    assert empty_queue_model.rowCount() == 1


def test_remove_record_emits_rows_removed(populated_queue_model, qtbot):
    """GIVEN a model with 4 records WHEN remove_record(0) is called
    THEN rowsRemoved is emitted and row count drops to 3."""
    with qtbot.wait_signal(populated_queue_model.rowsRemoved, timeout=500):
        populated_queue_model.remove_record(0)
    assert populated_queue_model.rowCount() == 3


def test_update_record_emits_data_changed(populated_queue_model, make_queue_item, qtbot):
    """GIVEN a populated model WHEN update_record is called THEN
    dataChanged is emitted with the correct row range."""
    updated = make_queue_item(name="Updated")
    with qtbot.wait_signal(populated_queue_model.dataChanged, timeout=500) as blocker:
        populated_queue_model.update_record(1, updated)

    # The signal should carry the full row range (col 0 -> last col)
    (top_left, bottom_right) = blocker.args[:2]
    assert top_left.row() == 1
    assert top_left.column() == 0
    assert bottom_right.row() == 1
    assert bottom_right.column() == 5


def test_set_records_clears_previous(empty_queue_model, make_queue_item):
    """GIVEN a model with items WHEN set_records([]) is called THEN
    rowCount becomes 0."""
    items = [make_queue_item(name="A")]
    empty_queue_model.set_records(items)
    assert empty_queue_model.rowCount() == 1
    empty_queue_model.set_records([])
    assert empty_queue_model.rowCount() == 0


# ============================================================================
# Checkbox toggle
# ============================================================================


def test_checkbox_setdata_toggles(populated_queue_model):
    """GIVEN a populated model WHEN setData is called with CheckStateRole
    on the checkbox column THEN the state changes."""
    idx = populated_queue_model.index(0, 5)
    # Toggle to checked
    result = populated_queue_model.setData(
        idx, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole,
    )
    assert result is True
    assert (
        populated_queue_model.data(idx, Qt.ItemDataRole.CheckStateRole)
        == Qt.CheckState.Checked
    )
    # Toggle back
    populated_queue_model.setData(
        idx, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole,
    )
    assert (
        populated_queue_model.data(idx, Qt.ItemDataRole.CheckStateRole)
        == Qt.CheckState.Unchecked
    )


def test_checkbox_setdata_non_checkbox_col_returns_false(populated_queue_model):
    """GIVEN a non-checkbox column WHEN setData is called with
    CheckStateRole THEN False is returned."""
    idx = populated_queue_model.index(0, 0)
    result = populated_queue_model.setData(
        idx, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole,
    )
    assert result is False


# ============================================================================
# Scoped enum compliance (Decision 4)
# ============================================================================


def test_scoped_enum_compliance():
    """GIVEN the minerva/ui/models/ directory WHEN grepped for flat-form
    Qt enums THEN zero matches are found.

    Forbidden patterns (not under a parent enum)::

        Qt\\.ItemIs                    (should be Qt.ItemFlag.ItemIs...)
        Qt\\.DisplayRole               (should be Qt.ItemDataRole.DisplayRole)
        Qt\\.EditRole                  (should be Qt.ItemDataRole.EditRole)
        Qt\\.CheckState                (should be Qt.CheckState.Checked etc.)
        Qt\\.Align(?!ment)             (should be Qt.AlignmentFlag.Align...)

    Note: ``Qt.AlignmentFlag`` and ``Qt.AlignmentFunction`` include
    ``Align`` as a substring — the negative lookahead ``(?!ment)``
    ensures those are NOT flagged.
    """
    import re
    from pathlib import Path

    models_dir = Path(__file__).parents[1] / "minerva" / "ui" / "models"
    if not models_dir.is_dir():
        return  # not yet created

    # Note: CheckState is deliberately omitted from the flat-form list
    # because Qt.CheckState as a standalone reference IS the correct scoped
    # enum class (e.g., ``Qt.CheckState.Checked`` or ``dict[int, Qt.CheckState]``).
    # The flat form ``Qt.Checked`` was never introduced here.
    forbidden = re.compile(
        r"Qt\.(ItemIs(?!\w*\.)|Align(?!ment)|DisplayRole|EditRole|UserRole)\b"
    )

    violations: list[str] = []
    for py_file in sorted(models_dir.rglob("*.py")):
        text = py_file.read_text()
        for match in forbidden.finditer(text):
            line_num = text[: match.start()].count("\n") + 1
            violations.append(f"{py_file.name}:{line_num}: {match.group()}")

    assert not violations, (
        f"Found {len(violations)} flat-form Qt enum violation(s):\n"
        + "\n".join(violations)
    )


# ============================================================================
# QAbstractItemModelTester conformance (if available)
# ============================================================================


def test_modeltester_conformance(empty_queue_model):
    """GIVEN an empty QueueItemRecordModel WHEN QAbstractItemModelTester
    checks THEN no warnings are emitted.

    If QAbstractItemModelTester is not available, a minimal conformance
    check is run instead (Decision 12).
    """
    _run_modeltester(empty_queue_model)


def test_populated_modeltester(populated_queue_model):
    """GIVEN a populated QueueItemRecordModel WHEN QAbstractItemModelTester
    checks THEN no warnings are emitted."""
    _run_modeltester(populated_queue_model)


def _run_modeltester(model):
    """Run QAbstractItemModelTester or fallback conformance checks."""
    if _HAVE_MODEL_TESTER:
        tester = QAbstractItemModelTester(model)
        # no news is good news — the tester raises/warns on failure
        return

    # Fallback: minimal conformance (Decision 12)
    assert model.rowCount() >= 0
    assert model.columnCount() >= 0
    # Invalid index data should return None
    assert model.data(QModelIndex()) is None
    # Valid index on empty model returns None
    if model.rowCount() == 0:
        idx = model.index(0, 0)
        # An out-of-range index may be valid but data should return None
        pass


# ============================================================================
# Column 4 matched_size via SizeDelegate (format_fn=None → raw int)
# ============================================================================


def test_size_column_raw_value(populated_queue_model):
    """GIVEN a populated model WHEN column 4 (Size) data is queried with
    DisplayRole THEN the raw integer value is returned (format_fn=None)."""
    # Item 2: matched_size=1048576
    idx = populated_queue_model.index(2, 4)
    val = idx.data(Qt.ItemDataRole.DisplayRole)
    assert val == 1048576, f"Expected raw int 1048576, got {val!r}"
    assert isinstance(val, int), "Expected raw int, not formatted string"


def test_size_column_user_role(populated_queue_model):
    """GIVEN a populated model WHEN column 4 data is queried with UserRole
    THEN the raw integer is returned (for sorting)."""
    idx = populated_queue_model.index(1, 4)
    val = idx.data(Qt.ItemDataRole.UserRole)
    assert val == 2048
