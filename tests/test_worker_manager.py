"""
Tests for WorkerManager — is_active and prepare_shutdown.
"""

from __future__ import annotations

from unittest.mock import Mock

from minerva.app.worker_manager import WorkerManager


def test_is_active_default_false(qtbot):
    """GIVEN a freshly-constructed WorkerManager WHEN is_active is
    called THEN it returns False (no filter thread attached)."""
    mgr = WorkerManager()
    assert mgr.is_active() is False


def test_is_active_with_thread_running(qtbot):
    """GIVEN a WorkerManager with an active filter_load_thread WHEN
    is_active is called THEN it returns True."""
    mgr = WorkerManager()
    thread = Mock()
    thread.is_alive.return_value = True
    mgr.filter_load_thread = thread  # type: ignore[assignment]

    assert mgr.is_active() is True


def test_is_active_with_stopped_thread(qtbot):
    """GIVEN a WorkerManager with a stopped filter_load_thread WHEN
    is_active is called THEN it returns False."""
    mgr = WorkerManager()
    thread = Mock()
    thread.is_alive.return_value = False
    mgr.filter_load_thread = thread  # type: ignore[assignment]

    assert mgr.is_active() is False


def test_is_active_with_none_thread(qtbot):
    """GIVEN a WorkerManager with filter_load_thread=None WHEN is_active
    is called THEN it returns False."""
    mgr = WorkerManager()
    mgr.filter_load_thread = None
    assert mgr.is_active() is False


def test_prepare_shutdown_returns_true_when_idle(qtbot):
    """GIVEN an idle WorkerManager WHEN prepare_shutdown is called
    THEN it returns True without error."""
    mgr = WorkerManager()
    result = mgr.prepare_shutdown(timeout_ms=100)
    assert result is True
