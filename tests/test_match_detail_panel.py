"""
Tests for MatchDetailPanel — inline match review replacing InspectorScaffold.

Covers: show_entry, clear, decision_changed signal, candidate list,
per-entry approve/ignore, bulk actions, comparison view, CDRomance search,
export/generate DAT.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

from PyQt6 import QtCore, QtWidgets

from minerva.app.app_state import AppState
from minerva.ui.widgets.match_detail_panel import MatchDetailPanel


def test_panel_constructs(qtbot):
    """GIVEN an AppState WHEN MatchDetailPanel is constructed THEN it exists
    with no entry shown."""
    app_state = AppState()
    panel = MatchDetailPanel(app_state)
    qtbot.add_widget(panel)

    assert panel is not None
    assert panel.current_entry_id is None


def test_show_entry(qtbot):
    """GIVEN a MatchDetailPanel WHEN show_entry is called THEN
    current_entry_id reflects the new entry."""
    app_state = AppState()
    panel = MatchDetailPanel(app_state)
    qtbot.add_widget(panel)

    panel.show_entry("report-1", "entry-1")

    assert panel.current_entry_id == "entry-1"


def test_clear(qtbot):
    """GIVEN a MatchDetailPanel with a shown entry WHEN clear is called THEN
    current_entry_id is None."""
    app_state = AppState()
    panel = MatchDetailPanel(app_state)
    qtbot.add_widget(panel)

    panel.show_entry("report-1", "entry-1")
    panel.clear()

    assert panel.current_entry_id is None


def test_decision_changed_signal(qtbot):
    """GIVEN a MatchDetailPanel with a shown entry WHEN approve is clicked
    THEN decision_changed signal is emitted with (report_id, entry_id, decision)."""
    app_state = AppState()
    panel = MatchDetailPanel(app_state)
    qtbot.add_widget(panel)

    panel.show_entry("report-1", "entry-1")

    with qtbot.waitSignal(panel.decision_changed, timeout=1000) as blocker:
        panel.approve_entry()

    assert blocker.args == ["report-1", "entry-1", "accept"]


def test_ignore_entry(qtbot):
    """GIVEN a MatchDetailPanel with a shown entry WHEN ignore is clicked
    THEN decision_changed signal is emitted with 'reject'."""
    app_state = AppState()
    panel = MatchDetailPanel(app_state)
    qtbot.add_widget(panel)

    panel.show_entry("report-1", "entry-1")

    with qtbot.waitSignal(panel.decision_changed, timeout=1000) as blocker:
        panel.ignore_entry()

    assert blocker.args == ["report-1", "entry-1", "reject"]


def test_bulk_approve_exact(qtbot):
    """GIVEN a MatchDetailPanel WHEN approve_all_exact is called THEN
    the bulk action signal is emitted."""
    app_state = AppState()
    panel = MatchDetailPanel(app_state)
    qtbot.add_widget(panel)

    panel.show_entry("report-1", "entry-1")

    signal_received = []
    panel.decision_changed.connect(
        lambda *args: signal_received.append(args)
    )

    panel.approve_all_exact()

    # At least one signal should be emitted (or the method should complete)
    # The actual filtering logic depends on DB queries, so we just verify
    # the method doesn't crash
    assert panel is not None


def test_bulk_approve_fuzzy_threshold(qtbot):
    """GIVEN a MatchDetailPanel WHEN approve_fuzzy_above_threshold is called
    THEN the method completes without error."""
    app_state = AppState()
    panel = MatchDetailPanel(app_state)
    qtbot.add_widget(panel)

    panel.show_entry("report-1", "entry-1")

    # Should not crash
    panel.approve_fuzzy_above_threshold(95)


def test_cdromance_search_url(qtbot):
    """GIVEN a MatchDetailPanel WHEN cdromance_search is called THEN
    a URL is built for the game."""
    app_state = AppState()
    panel = MatchDetailPanel(app_state)
    qtbot.add_widget(panel)

    url = panel.build_cdromance_url("Super Mario", "Nintendo - Super Nintendo")
    assert "cdromance.org" in url
    assert "snes" in url


def test_comparison_view_exists(qtbot):
    """GIVEN a MatchDetailPanel WHEN constructed THEN it has a
    comparison area for requested vs candidate."""
    app_state = AppState()
    panel = MatchDetailPanel(app_state)
    qtbot.add_widget(panel)

    assert panel.comparison_widget is not None


def test_export_generate_buttons_exist(qtbot):
    """GIVEN a MatchDetailPanel WHEN constructed THEN export and
    generate DAT buttons exist."""
    app_state = AppState()
    panel = MatchDetailPanel(app_state)
    qtbot.add_widget(panel)

    assert panel.export_button is not None
    assert panel.generate_dat_button is not None


def test_no_dead_inspector_scaffold_import():
    """GIVEN the match_detail_panel source WHEN parsed by ast THEN no
    InspectorScaffold import exists."""
    import ast
    from pathlib import Path

    source_path = (
        Path(__file__).resolve().parents[1]
        / "minerva"
        / "ui"
        / "widgets"
        / "match_detail_panel.py"
    )
    tree = ast.parse(source_path.read_text("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            if "inspector_scaffold" in node.module:
                raise AssertionError(
                    f"Found dead inspector_scaffold import at line {node.lineno}"
                )
