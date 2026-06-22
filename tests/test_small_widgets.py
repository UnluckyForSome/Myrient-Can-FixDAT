"""Tests for small widget helpers: SectionCard, FilterChip, BusyOverlay, ActivityList."""

from __future__ import annotations

import time

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.ui.density import Density
from minerva.ui.icons import Icons
from minerva.ui.widgets.activity_list import ActivityList
from minerva.ui.widgets.busy_overlay import BusyOverlay, _SpinnerWidget
from minerva.ui.widgets.filter_chip import FilterChip
from minerva.ui.widgets.section_card import SectionCard


# ============================================================================
# SectionCard
# ============================================================================


class TestSectionCard:
    def test_constructs_without_title(self, qtbot):
        card = SectionCard()
        qtbot.addWidget(card)
        assert card.content_layout() is not None

    def test_constructs_with_title_and_icon(self, qtbot):
        icon = QtGui.QIcon()
        card = SectionCard(title="Details", icon=icon)
        qtbot.addWidget(card)
        assert card.findChild(QtWidgets.QLabel, "sectionTitle") is not None

    def test_content_layout_adds_widget(self, qtbot):
        card = SectionCard()
        qtbot.addWidget(card)
        label = QtWidgets.QLabel("hi")
        card.content_layout().addWidget(label)
        assert label.parent() is card

    def test_density_used_for_padding(self, qtbot):
        card = SectionCard(density=Density.COMFORTABLE)
        qtbot.addWidget(card)
        assert card._density == Density.COMFORTABLE


# ============================================================================
# FilterChip
# ============================================================================


class TestFilterChip:
    def test_checked(self, qtbot):
        chip = FilterChip("NES", checked=True)
        qtbot.addWidget(chip)
        assert chip.isChecked()
        assert chip.text() == "NES"

    def test_unchecked_by_default(self, qtbot):
        chip = FilterChip("SNES")
        qtbot.addWidget(chip)
        assert not chip.isChecked()

    def test_checkable(self, qtbot):
        chip = FilterChip("Test")
        qtbot.addWidget(chip)
        assert chip.isCheckable()

    def test_object_name(self, qtbot):
        chip = FilterChip("Test")
        qtbot.addWidget(chip)
        assert chip.objectName() == "filterChip"


# ============================================================================
# BusyOverlay
# ============================================================================


class TestBusyOverlay:
    def test_constructs_without_cancel(self, qtbot):
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        overlay = BusyOverlay(parent, "Loading…")
        assert overlay.findChild(QtWidgets.QPushButton, "subtleButton") is None

    def test_constructs_with_cancel(self, qtbot):
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        overlay = BusyOverlay(parent, "Loading…", cancellable=True)
        btn = overlay.findChild(QtWidgets.QPushButton, "subtleButton")
        assert btn is not None
        assert btn.text() == "Cancel"

    def test_show_starts_spinner(self, qtbot):
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        overlay = BusyOverlay(parent, "Loading…")
        overlay.show()
        assert overlay._spinner._timer.isActive()
        overlay.hide()

    def test_show_updates_text(self, qtbot):
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        overlay = BusyOverlay(parent, "A")
        overlay.show("B")
        assert overlay._message_label.text() == "B"
        overlay.hide()

    def test_hide_stops_spinner(self, qtbot):
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        overlay = BusyOverlay(parent, "Loading…")
        overlay.show()
        overlay.hide()
        assert not overlay._spinner._timer.isActive()

    def test_set_text(self, qtbot):
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        overlay = BusyOverlay(parent, "A")
        overlay.set_text("B")
        assert overlay._message_label.text() == "B"

    def test_cancel_emits_signal(self, qtbot):
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        overlay = BusyOverlay(parent, "Working", cancellable=True)
        with qtbot.wait_signal(overlay.cancel_requested, timeout=1000):
            overlay._on_cancel()


class TestSpinnerWidget:
    def test_rotate(self, qtbot):
        spinner = _SpinnerWidget()
        qtbot.addWidget(spinner)
        spinner.start()
        spinner._rotate()
        assert spinner._angle == 30
        spinner.stop()

    def test_set_colour(self, qtbot):
        spinner = _SpinnerWidget()
        qtbot.addWidget(spinner)
        spinner.set_colour("#ff0000")
        assert spinner._colour == "#ff0000"


# ============================================================================
# ActivityList
# ============================================================================


class TestActivityList:
    def test_add_event(self, qtbot):
        lst = ActivityList(max_items=100)
        qtbot.addWidget(lst)
        lst.add_event("download", "Started foo.zip", "14:32")
        assert lst.count() == 1

    def test_add_multiple_events(self, qtbot):
        lst = ActivityList(max_items=100)
        qtbot.addWidget(lst)
        for i in range(3):
            lst.add_event("info", f"event {i}", "14:32")
        assert lst.count() == 3

    def test_max_items_enforced(self, qtbot):
        lst = ActivityList(max_items=2)
        qtbot.addWidget(lst)
        for i in range(5):
            lst.add_event("info", f"event {i}", "14:32")
        assert lst.count() == 2

    def test_clear_removes_all(self, qtbot):
        lst = ActivityList(max_items=100)
        qtbot.addWidget(lst)
        lst.add_event("info", "event", "14:32")
        lst.clear()
        assert lst.count() == 0

    def test_unknown_category_uses_default(self, qtbot):
        lst = ActivityList(max_items=100)
        qtbot.addWidget(lst)
        lst.add_event("weird", "event", "14:32")
        assert lst.count() == 1

    def test_all_known_categories(self, qtbot):
        lst = ActivityList(max_items=100)
        qtbot.addWidget(lst)
        for category in ["download", "check", "error", "skip", "search", "activity", "info"]:
            lst.add_event(category, f"{category} event", "14:32")
        assert lst.count() == 7
