"""
Tests for AppState — signal emission and mutator invariants.
"""

from __future__ import annotations

from PyQt6 import QtCore

from minerva.app.app_state import AppState


def test_set_selected_emits_signal(qtbot):
    """GIVEN AppState with a subscriber WHEN set_selected is called
    THEN selected_count_changed fires with the correct count."""
    state = AppState()

    with qtbot.wait_signal(state.selected_count_changed, timeout=500) as blocker:
        state.set_selected(["A", "B", "C"])

    assert blocker.args == [3]


def test_set_selected_replaces_not_merges(qtbot):
    """GIVEN AppState with existing selection WHEN set_selected is called
    THEN the set is replaced entirely."""
    state = AppState()
    state.set_selected(["A", "B"])

    with qtbot.wait_signal(state.selected_count_changed, timeout=500) as blocker:
        state.set_selected(["C"])

    assert blocker.args == [1]
    assert set(state.selected_game_ids) == {"C"}


def test_clear_selected_emits_zero(qtbot):
    """GIVEN AppState with selected items WHEN clear_selected is called
    THEN selected_count_changed emits 0."""
    state = AppState()
    state.set_selected(["X", "Y"])

    with qtbot.wait_signal(state.selected_count_changed, timeout=500) as blocker:
        state.clear_selected()

    assert blocker.args == [0]
    assert len(state.selected_game_ids) == 0


def test_selected_game_ids_is_frozenset(qtbot):
    """GIVEN AppState WHEN accessing selected_game_ids THEN it returns
    a frozenset (immutable view)."""
    state = AppState()
    state.set_selected(["A"])
    ids = state.selected_game_ids
    assert isinstance(ids, frozenset)
    assert set(ids) == {"A"}


def test_index_state_setter_emits_signal(qtbot):
    """GIVEN AppState WHEN index_state is assigned THEN
    index_state_changed fires."""
    state = AppState()

    with qtbot.wait_signal(state.index_state_changed, timeout=500) as blocker:
        state.index_state = "ready"

    assert blocker.args == ["ready"]


def test_current_report_id_no_signal(qtbot):
    """GIVEN AppState WHEN current_report_id is assigned THEN no
    signal fires (plain property, no emit)."""
    state = AppState()
    signals = []

    state.selected_count_changed.connect(lambda _: signals.append("selected"))
    state.current_report_id = "rpt-001"

    assert signals == []
    assert state.current_report_id == "rpt-001"
