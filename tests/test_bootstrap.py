"""Tests for bootstrap.create_main_window and main() ordering."""

from __future__ import annotations

import ast
from pathlib import Path

from PyQt6 import QtCore

from minerva.app.bootstrap import create_main_window


class TestCreateMainWindow:
    def test_returns_main_window(self, qtbot, monkeypatch, tmp_path):
        """GIVEN the bootstrap helper WHEN called THEN it returns an AppShell."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
        settings = QtCore.QSettings("MinervaFixDAT", "MinervaGUI")
        settings.setValue("state_db_path", str(tmp_path / "state.db"))
        settings.setValue("index_path", str(tmp_path / "index.db"))

        win = create_main_window()
        qtbot.addWidget(win)
        assert win is not None
        assert win.__class__.__name__ == "AppShell"


def test_wizard_runs_before_show():
    """GIVEN the bootstrap source WHEN parsed THEN the is_first_run check
    appears BEFORE win.show()."""
    source_path = (
        Path(__file__).resolve().parents[1]
        / "minerva"
        / "app"
        / "bootstrap.py"
    )
    source = source_path.read_text("utf-8")
    tree = ast.parse(source)

    # Find the main() function
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            lines = source.splitlines()
            # Find line numbers (0-indexed) of is_first_run and win.show
            first_run_line = None
            show_line = None
            for i, line in enumerate(lines):
                if "is_first_run" in line and first_run_line is None:
                    first_run_line = i
                if "win.show()" in line and show_line is None:
                    show_line = i
            assert first_run_line is not None, "is_first_run not found in main()"
            assert show_line is not None, "win.show() not found in main()"
            assert first_run_line < show_line, (
                f"is_first_run (line {first_run_line + 1}) must come before "
                f"win.show() (line {show_line + 1})"
            )
