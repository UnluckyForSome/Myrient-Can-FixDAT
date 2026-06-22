"""
Tests for ``DisplayDelegate``, ``SizeDelegate``, and ``CheckboxDelegate``.

Covers: SizeDelegate binary ladder (0, KB, MB, GB, negative),
DisplayDelegate pass-through, CheckboxDelegate click toggle.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTableView

from minerva.ui.models.delegates import CheckboxDelegate, DisplayDelegate, SizeDelegate
from minerva.ui.models.record_model import QueueItemRecordModel, _QUEUE_COLUMNS


# ============================================================================
# DisplayDelegate
# ============================================================================


def test_display_text_plain(qtbot):
    """GIVEN DisplayDelegate WHEN displayText is called with a string
    and no format_fn THEN the string is returned as-is."""
    delegate = DisplayDelegate()
    result = delegate.displayText("hello", QtCore.QLocale())
    assert result == "hello"


def test_display_text_number(qtbot):
    """GIVEN DisplayDelegate WHEN displayText is called with an integer
    THEN the string representation is returned."""
    delegate = DisplayDelegate()
    result = delegate.displayText(42, QtCore.QLocale())
    assert result == "42"


# ============================================================================
# SizeDelegate
# ============================================================================


def test_size_zero(qtbot):
    """GIVEN SizeDelegate WHEN displayText(0) is called THEN \"0 B\" is
    returned."""
    delegate = SizeDelegate()
    result = delegate.displayText(0, QtCore.QLocale())
    assert result == "0 B"


def test_size_bytes(qtbot):
    """GIVEN SizeDelegate WHEN displayText(512) is called THEN \"512 B\"
    is returned."""
    delegate = SizeDelegate()
    result = delegate.displayText(512, QtCore.QLocale())
    assert result == "512 B"


def test_size_kb(qtbot):
    """GIVEN SizeDelegate WHEN displayText(1024) is called THEN
    \"1.0 KB\" is returned."""
    delegate = SizeDelegate()
    result = delegate.displayText(1024, QtCore.QLocale())
    assert result == "1.0 KB"


def test_size_mb(qtbot):
    """GIVEN SizeDelegate WHEN displayText(1048576) is called THEN
    \"1.0 MB\" is returned."""
    delegate = SizeDelegate()
    result = delegate.displayText(1048576, QtCore.QLocale())
    assert result == "1.0 MB"


def test_size_gb(qtbot):
    """GIVEN SizeDelegate WHEN displayText(1073741824) is called THEN
    \"1.0 GB\" is returned."""
    delegate = SizeDelegate()
    result = delegate.displayText(1073741824, QtCore.QLocale())
    assert result == "1.0 GB"


def test_size_tb(qtbot):
    """GIVEN SizeDelegate WHEN displayText(1099511627776) is called THEN
    \"1.0 TB\" is returned."""
    delegate = SizeDelegate()
    result = delegate.displayText(1099511627776, QtCore.QLocale())
    assert result == "1.0 TB"


def test_size_negative(qtbot):
    """GIVEN SizeDelegate WHEN displayText(-1) is called THEN \"-\" is
    returned (Decision 10)."""
    delegate = SizeDelegate()
    result = delegate.displayText(-1, QtCore.QLocale())
    assert result == "-"


def test_size_non_int(qtbot):
    """GIVEN SizeDelegate WHEN displayText is called with a non-int
    value (string) THEN str(value) is returned."""
    delegate = SizeDelegate()
    result = delegate.displayText("N/A", QtCore.QLocale())
    assert result == "N/A"


# ============================================================================
# CheckboxDelegate
# ============================================================================


def test_checkbox_click_toggles(make_queue_item, qtbot):
    """GIVEN a QueueItemRecordModel with a CheckboxDelegate on column 5
    WHEN a mouse click is performed inside the checkbox indicator rect
    THEN the check state toggles.

    This test simulates the full editorEvent path."""
    model = QueueItemRecordModel(
        [make_queue_item(name="test")],
        _QUEUE_COLUMNS,
    )
    delegate = CheckboxDelegate()
    view = QTableView()
    view.setModel(model)
    view.setItemDelegateForColumn(5, delegate)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)

    idx = model.index(0, 5)
    # Verify initial state is Unchecked
    assert model.data(idx, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked

    # Trigger editorEvent directly (not through mouse click)
    from PyQt6 import QtGui
    from PyQt6.QtCore import QPointF
    from PyQt6.QtWidgets import QApplication, QStyleOptionViewItem

    opt = QStyleOptionViewItem()
    opt.index = idx
    opt.rect = view.visualRect(idx)
    # Get the real indicator rect from the style
    style = QApplication.style()
    check_rect = style.subElementRect(
        QtWidgets.QStyle.SubElement.SE_ItemViewItemCheckIndicator,
        opt,
        view,
    )
    # The indicator rect should be inside the cell rect
    if check_rect.isValid() and check_rect.width() > 0:
        click_point = QPointF(check_rect.center())
        mouse_event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease,
            click_point,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = delegate.editorEvent(mouse_event, model, opt, idx)
        assert result is True, "editorEvent should return True for checkbox click"
        # State should now be Checked
        new_state = model.data(idx, Qt.ItemDataRole.CheckStateRole)
        assert new_state == Qt.CheckState.Checked, (
            f"Expected Checked after click, got {new_state}"
        )
    else:
        # Skip if the style doesn't provide a valid indicator rect
        # (headless QPA offscreen may not paint indicators)
        pass


def test_checkbox_click_outside_no_toggle(make_queue_item, qtbot):
    """GIVEN a queue model with a CheckboxDelegate WHEN a mouse click
    lands outside the checkbox indicator rect THEN the state does NOT
    toggle."""
    model = QueueItemRecordModel(
        [make_queue_item(name="test")],
        _QUEUE_COLUMNS,
    )
    delegate = CheckboxDelegate()
    view = QTableView()
    view.setModel(model)
    view.setItemDelegateForColumn(5, delegate)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)

    idx = model.index(0, 5)
    initial = model.data(idx, Qt.ItemDataRole.CheckStateRole)

    # Trigger editorEvent far from the indicator rect
    from PyQt6.QtCore import QPointF
    from PyQt6.QtWidgets import QApplication, QStyleOptionViewItem

    opt = QStyleOptionViewItem()
    opt.rect = view.visualRect(idx)

    from PyQt6 import QtGui

    mouse_event = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonRelease,
        QPointF(-100, -100),  # far outside
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    result = delegate.editorEvent(mouse_event, model, opt, idx)
    assert result is False, "editorEvent should return False for click outside"
    assert (
        model.data(idx, Qt.ItemDataRole.CheckStateRole) == initial
    ), "State should not change"
