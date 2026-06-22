"""
Tests for Density persistence via QSettings in AppShell.
"""

from __future__ import annotations

from PyQt6 import QtCore

from minerva.app.shell import AppShell
from minerva.ui.density import Density

_SETTINGS_ORG = "MinervaFixDAT"
_SETTINGS_APP = "MinervaGUI_density_test"


def test_density_default_is_comfortable():
    """GIVEN a freshly constructed AppShell WITH default density
    THEN _density is Density.COMFORTABLE."""
    shell = AppShell(
        settings_org=_SETTINGS_ORG,
        settings_app=_SETTINGS_APP,
    )
    assert shell._density == Density.COMFORTABLE


def test_density_saved_to_qsettings_on_close(qtbot, tmp_path, monkeypatch):
    """GIVEN AppShell WHEN closeEvent fires THEN 'ui/density' is saved."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "density_test"))
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)

    monkeypatch.setattr(
        "PyQt6.QtWidgets.QMessageBox.question",
        lambda *a, **kw: __import__("PyQt6.QtWidgets").QtWidgets.QMessageBox.StandardButton.Yes,
    )

    shell = AppShell(
        settings_org=_SETTINGS_ORG,
        settings_app=_SETTINGS_APP,
    )
    qtbot.addWidget(shell)
    monkeypatch.setattr(shell, "_auto_save_queue", lambda: None)

    shell.close()

    settings = QtCore.QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    saved = settings.value("ui/density", "", str)
    assert saved in ("comfortable", "compact")
