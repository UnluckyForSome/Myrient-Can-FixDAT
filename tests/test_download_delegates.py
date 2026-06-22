"""Tests for DownloadStatusDelegate._style and DownloadProgressDelegate."""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from minerva.domain.downloads import DownloadStatus
from minerva.ui.models.download_delegates import (
    DownloadProgressDelegate,
    DownloadStatusDelegate,
)


class TestStatusDelegateStyle:
    def _delegate(self) -> DownloadStatusDelegate:
        return DownloadStatusDelegate()

    def test_queued(self):
        text, fg, bg = self._delegate()._style(DownloadStatus.QUEUED)
        assert text == "Queued"

    def test_starting(self):
        text, _, _ = self._delegate()._style(DownloadStatus.STARTING)
        assert text == "Starting"

    def test_downloading(self):
        text, _, _ = self._delegate()._style(DownloadStatus.DOWNLOADING)
        assert text == "Downloading"

    def test_paused(self):
        text, _, _ = self._delegate()._style(DownloadStatus.PAUSED)
        assert text == "Paused"

    def test_seeding(self):
        text, _, _ = self._delegate()._style(DownloadStatus.SEEDING)
        assert text == "Seeding"

    def test_completed(self):
        text, _, _ = self._delegate()._style(DownloadStatus.COMPLETED)
        assert text == "Completed"

    def test_failed(self):
        text, _, _ = self._delegate()._style(DownloadStatus.FAILED)
        assert text == "Failed"

    def test_cancelled(self):
        text, _, _ = self._delegate()._style(DownloadStatus.CANCELLED)
        assert text == "Cancelled"

    def test_all_statuses_have_nonempty_colors(self):
        d = self._delegate()
        for status in DownloadStatus:
            text, fg, bg = d._style(status)
            assert text
            assert fg
            assert bg


class TestStatusDelegateConstruction:
    def test_constructs(self):
        d = DownloadStatusDelegate()
        assert d is not None

    def test_constructs_with_parent(self, qtbot):
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        d = DownloadStatusDelegate(parent)
        assert d.parent() is parent


class TestProgressDelegateConstruction:
    def test_constructs(self):
        d = DownloadProgressDelegate()
        assert d is not None

    def test_constructs_with_parent(self, qtbot):
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        d = DownloadProgressDelegate(parent=parent)
        assert d.parent() is parent
