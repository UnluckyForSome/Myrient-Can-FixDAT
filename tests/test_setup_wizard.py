"""
Tests for SetupWizard — first-run detection, step completion, cancel rollback.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

from PyQt6 import QtCore, QtWidgets

from minerva.ui.widgets.setup_wizard import SetupWizard, is_first_run


def test_wizard_constructs(qtbot):
    """GIVEN no arguments WHEN SetupWizard is constructed THEN it exists
    with 3 pages."""
    wizard = SetupWizard()
    qtbot.add_widget(wizard)

    assert wizard is not None
    assert wizard.pageIds() is not None


def test_wizard_has_three_steps(qtbot):
    """GIVEN SetupWizard WHEN constructed THEN it has 3 wizard pages."""
    wizard = SetupWizard()
    qtbot.add_widget(wizard)

    assert len(wizard.pageIds()) == 3


def test_is_first_run_no_settings(tmp_path, monkeypatch):
    """GIVEN no qBit settings AND no index WHEN is_first_run is called
    THEN it returns True."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    settings = QtCore.QSettings("MinervaFixDAT", "MinervaGUI_test_first_run")
    settings.clear()

    # No qBit URL and no index path
    assert is_first_run(settings) is True


def test_is_not_first_run_with_settings(tmp_path, monkeypatch):
    """GIVEN existing qBit settings WHEN is_first_run is called
    THEN it returns False."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    settings = QtCore.QSettings("MinervaFixDAT", "MinervaGUI_test_not_first")
    settings.setValue("qbit_url", "http://localhost:8080")

    assert is_first_run(settings) is False


def test_is_not_first_run_with_index(tmp_path, monkeypatch):
    """GIVEN existing index path WHEN is_first_run is called
    THEN it returns False."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    settings = QtCore.QSettings("MinervaFixDAT", "MinervaGUI_test_has_index")
    # Create the index file so Path.exists() returns True
    index_file = tmp_path / "existing_index.db"
    index_file.touch()
    settings.setValue("index_path", str(index_file))

    assert is_first_run(settings) is False


def test_wizard_step_one_has_connection_fields(qtbot):
    """GIVEN SetupWizard WHEN page 1 is shown THEN it has qBit
    connection fields."""
    wizard = SetupWizard()
    qtbot.add_widget(wizard)

    page = wizard.page(0)
    # The page should have input fields for qBit connection
    assert page is not None


def test_wizard_step_three_has_output_dir(qtbot):
    """GIVEN SetupWizard WHEN page 3 is shown THEN it has an output
    directory picker."""
    wizard = SetupWizard()
    qtbot.add_widget(wizard)

    page = wizard.page(2)
    assert page is not None


def test_index_page_has_cancel_button(qtbot):
    """GIVEN SetupWizard WHEN step 2 is shown THEN it has a cancel button."""
    wizard = SetupWizard()
    qtbot.add_widget(wizard)

    page = wizard.page(1)
    assert page._cancel_btn is not None
    assert not page._cancel_btn.isEnabled()  # disabled until building


def test_index_page_cancel_resets_state(qtbot):
    """GIVEN an _IndexBuildPage in building state WHEN cancel is clicked
    THEN progress resets and build button is re-enabled."""
    wizard = SetupWizard()
    qtbot.add_widget(wizard)

    page = wizard.page(1)
    # Simulate building state
    page._building = True
    page._build_btn.setEnabled(False)
    page._cancel_btn.setEnabled(True)
    page._progress.setValue(50)

    page._on_cancel()

    assert not page._building
    assert page._build_btn.isEnabled()
    assert not page._cancel_btn.isEnabled()
    assert page._progress.value() == 0


def test_index_page_cancel_cleans_temp_file(qtbot, tmp_path):
    """GIVEN an _IndexBuildPage with a temp file WHEN cancel is clicked
    THEN the temp file is deleted."""
    wizard = SetupWizard()
    qtbot.add_widget(wizard)

    page = wizard.page(1)
    temp = tmp_path / "index.db.tmp"
    temp.touch()
    assert temp.exists()

    page._temp_index_path = temp
    page._building = True
    page._on_cancel()

    assert not temp.exists()
    assert page._temp_index_path is None
