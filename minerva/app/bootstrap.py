"""
Application entry point — QApplication setup and AppShell launch.

Usage::

    python -m minerva.app.bootstrap              # normal launch
    python -m minerva.app.bootstrap --index       # build index first
    python -m minerva.app.bootstrap --rebuild     # rebuild index first

Compatibility::
    ``python minerva_gui.py`` forwards here via ``minerva/app/bootstrap.py``.
"""

from __future__ import annotations

import sys
import time

from PyQt6 import QtCore, QtWidgets


def create_application(argv: list[str]) -> QtWidgets.QApplication:
    """Build and configure the QApplication instance."""
    QtCore.QCoreApplication.setAttribute(
        QtCore.Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True
    )
    app = QtWidgets.QApplication(argv)
    app.setApplicationName("Minerva Can FixDAT")
    app.setApplicationDisplayName("Minerva Can FixDAT")
    app.setOrganizationName("MinervaFixDAT")
    app.setStyle("Fusion")

    # Set a concrete default font so custom-painted delegates that read
    # QFont().pixelSize() get a real value (-1 produces QPainter warnings
    # in the Qt log).
    from PyQt6 import QtGui
    base_font = QtGui.QFont(app.font())
    if base_font.pointSize() <= 0 and base_font.pixelSize() <= 0:
        base_font.setPointSize(10)
    app.setFont(base_font)

    # Apply the design-system theme
    from minerva.ui.theme import apply_theme

    apply_theme(app)

    # Initialise QtAwesome global defaults
    from minerva.ui.icons import Icons

    Icons._ensure()

    return app


def create_main_window() -> QtWidgets.QMainWindow:
    """Build the main application window."""
    from minerva.app.shell import AppShell

    return AppShell()


def main() -> int:
    """Entry point: parse CLI args, create app, show shell, exec."""
    if "--index" in sys.argv or "--rebuild" in sys.argv:
        print("Building index…")
        from minerva_db import build_index

        t0 = time.time()
        build_index()
        print(f"Done in {time.time() - t0:.1f}s")

    app = create_application(sys.argv)
    win = create_main_window()

    # First-run wizard check (BEFORE show so wizard is modal)
    settings = QtCore.QSettings("MinervaFixDAT", "MinervaGUI")
    from minerva.ui.widgets.setup_wizard import SetupWizard, is_first_run
    if is_first_run(settings):
        wizard = SetupWizard(win)
        wizard.exec()

    win.show()

    exit_code = app.exec()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
