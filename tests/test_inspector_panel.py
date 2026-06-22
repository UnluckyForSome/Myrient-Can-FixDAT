"""Tests for the deprecated InspectorPanel wrapper."""

from __future__ import annotations

import warnings

import pytest
from PyQt6 import QtGui, QtWidgets

from minerva.ui.theme import ThemeTokens
from minerva.ui.density import Density
from minerva.ui.widgets.inspector_panel import (
    InspectorPanel,
    InspectorSection,
)
from minerva.ui.widgets.status_badge import BadgeKind


@pytest.fixture
def panel(qtbot):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        p = InspectorPanel()
    qtbot.addWidget(p)
    return p


class TestConstruction:
    def test_constructs_with_deprecation_warning(self, qtbot):
        with pytest.warns(DeprecationWarning):
            p = InspectorPanel()
        qtbot.addWidget(p)

    def test_default_title(self, panel):
        assert panel._name.text() == "Select a report"

    def test_default_status(self, panel):
        assert panel._status.text() == "No selection"


class TestClear:
    def test_clear_sets_message(self, panel):
        panel.clear("Pick something")
        assert panel._name.text() == "Pick something"

    def test_clear_resets_status(self, panel):
        panel.clear()
        assert panel._status.text() == "No selection"
        assert panel._status._kind == BadgeKind.NEUTRAL


class TestSetHeader:
    def test_sets_name_and_status(self, panel):
        panel.set_header("Report X", "Ready", BadgeKind.SUCCESS)
        assert panel._name.text() == "Report X"
        assert panel._status.text() == "Ready"


class TestSetSections:
    def test_empty_sections_clears_property_lists(self, panel):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            panel.set_sections([InspectorSection("A", [("k", "v")])])
        panel.set_sections([])
        assert len(panel._property_lists) == 0

    def test_adds_property_lists(self, panel):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            panel.set_sections([
                InspectorSection("Details", [("Name", "foo"), ("Size", "100")]),
            ])
        assert len(panel._property_lists) == 1


class TestAddAction:
    def test_adds_button(self, panel):
        btn = panel.add_action("Delete")
        assert btn.text() == "Delete"

    def test_primary_sets_object_name(self, panel):
        btn = panel.add_action("Save", primary=True)
        assert btn.objectName() == "actionGroupPrimary"

    def test_secondary_sets_object_name(self, panel):
        btn = panel.add_action("Cancel", primary=False)
        assert btn.objectName() == "actionGroupSecondary"


class TestSetActionsEnabled:
    def test_disables_all_buttons(self, panel):
        panel.add_action("A")
        panel.add_action("B")
        panel.set_actions_enabled(False)
        for i in range(panel.actions_layout.count()):
            w = panel.actions_layout.itemAt(i).widget()
            assert not w.isEnabled()

    def test_enables_all_buttons(self, panel):
        panel.add_action("A")
        panel.set_actions_enabled(False)
        panel.set_actions_enabled(True)
        w = panel.actions_layout.itemAt(0).widget()
        assert w.isEnabled()


class TestApplyTokens:
    def test_updates_tokens(self, panel):
        tokens = ThemeTokens()
        panel.apply_tokens(tokens)
        assert panel._tokens is tokens


class TestApplyDensity:
    def test_updates_density(self, panel):
        panel.apply_density(Density.COMPACT)
        assert panel._density == Density.COMPACT


class TestInspectorSectionDeprecated:
    def test_emits_deprecation_warning(self):
        with pytest.warns(DeprecationWarning):
            s = InspectorSection("Title")
        assert s.title == "Title"
        assert s.rows == []

    def test_accepts_rows(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            s = InspectorSection("Title", [("k", "v")])
        assert s.rows == [("k", "v")]
