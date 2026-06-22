"""
pytest-qt fixtures for Minerva GUI tests
=========================================

Test configuration:
  - Session-scoped QApplication (auto from pytest-qt)
  - Isolated QSettings via XDG_CONFIG_HOME monkeypatch
  - qtawesome fallback for headless CI (set_defaults)
  - tmp_path-based storage isolation
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_API", "pyqt6")
os.environ.setdefault("PYTEST_QT_API", "pyqt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import qtawesome as qta

# ── QtAwesome setup is deferred to the ``qapp`` fixture below.
# Calling qta.set_defaults() before a QApplication exists can corrupt
# the font charmap in qtawesome 1.4+. We set it after QApp creation.

# ── Session-scoped QApp ──────────────────────────────────────────────────────
# pytest-qt provides the ``qapp`` fixture for us; we just add our own
# fixtures that depend on it.  If you need a custom session-scoped QApp,
# uncomment below:


@pytest.fixture(scope="session")
def qapp(qapp):
    """Ensure QApplication has org/app names set for QSettings + QtAwesome init."""
    from PyQt6 import QtWidgets

    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.setOrganizationName("MinervaFixDAT")
        app.setApplicationName("MinervaGUI_test")
        # Initialise QtAwesome now that a QApp exists
        import qtawesome as qta
        try:
            qta.set_defaults(color="#e8eaf0")
        except Exception:
            pass
    return app


@pytest.fixture
def app_shell(qtbot, tmp_path, monkeypatch):
    """Create an AppShell with isolated QSettings and no external state.

    - ``tmp_path``-based QSettings (never touches real config).
    - Uses a unique QSettings application name to prevent
      cross-contamination with ``MinervaWindow`` tests (Qt's
      ``QSettings`` caches the file path globally by org/app).
    - No DB scan, no index, no tray icon.
    - ``qtbot`` manages the widget lifecycle.
    """
    from PyQt6 import QtCore

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)

    # ponytail: isolate the download controller's state + index DBs to tmp_path.
    # Without this, QSettings defaults state_db_path to "data/minerva_state.db"
    # (relative to CWD = the real project DB), so has_active_downloads() sees
    # real queued records and closeEvent pops a blocking exit dialog.
    settings = QtCore.QSettings("MinervaFixDAT", "MinervaGUI_app_shell_test")
    settings.setValue("state_db_path", str(tmp_path / "state.db"))
    settings.setValue("index_path", str(tmp_path / "index.db"))

    from minerva.app.shell import AppShell

    shell = AppShell(settings_app="MinervaGUI_app_shell_test")
    qtbot.addWidget(shell)
    shell.show()
    qtbot.waitExposed(shell)
    return shell


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Return a freshly-created QSettings instance backed by a temp file.

    Does NOT depend on MinervaWindow — use this for settings-only tests.
    """
    from PyQt6 import QtCore

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
    return QtCore.QSettings("MinervaFixDAT", "MinervaGUI_test")


# ==============================================================================
# Model/view fixtures (added by model-view-foundation)
# ==============================================================================


@pytest.fixture
def make_queue_item():
    """Return a factory function for ``QueueItem`` with sensible defaults.

    Usage::

        item = make_queue_item(name="foo", matched_size=2048)

    Any keyword override is merged on top of the defaults.
    """
    from minerva.app.legacy_data import QueueItem

    def _make(**overrides):
        defaults = dict(
            path="/tmp/default",
            name="default",
            entries_count=10,
            matched_count=5,
            unmatched_count=2,
            matched_size=1024,
            report=None,
        )
        defaults.update(overrides)
        return QueueItem(**defaults)

    return _make


@pytest.fixture
def empty_queue_model():
    """Return an empty ``QueueItemRecordModel`` with no records."""
    from minerva.ui.models.record_model import QueueItemRecordModel, _QUEUE_COLUMNS

    model = QueueItemRecordModel([], _QUEUE_COLUMNS)
    return model


@pytest.fixture
def populated_queue_model(make_queue_item):
    """Return a ``QueueItemRecordModel`` with 4 deterministic records."""
    from minerva.ui.models.record_model import QueueItemRecordModel, _QUEUE_COLUMNS

    items = [
        make_queue_item(name="Alpha", entries_count=100, matched_size=512),
        make_queue_item(name="beta", entries_count=50, matched_size=2048),
        make_queue_item(name="Gamma", entries_count=200, matched_size=1048576),
        make_queue_item(
            name="delta",
            entries_count=75,
            matched_size=1073741824,
        ),
    ]
    model = QueueItemRecordModel(items, _QUEUE_COLUMNS)
    return model
