"""
Central icon provider wrapping QtAwesome.

``Icons`` exposes static factory methods that return ``QIcon``.
All icons use ``fa5s.*`` prefix for consistency.

Usage::

    from minerva.ui.icons import Icons
    icon = Icons.reports()
    button.setIcon(icon)
    success_icon = Icons.status_success()
"""

from __future__ import annotations

import qtawesome as qta
from PyQt6 import QtGui


class Icons:
    """Named icon factories wrapping ``qtawesome``.

    All icons use ``fa5s`` (Font Awesome 5 Solid). Semantic colour
    variants use explicit hex colours for status differentiation.
    """

    _initialized = False

    @classmethod
    def _ensure(cls) -> None:
        if cls._initialized:
            return
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            # QtAwesome needs a running QApplication. If none exists yet,
            # skip initialization — it will happen on the next call once
            # a QApp is available. The flag stays False so we retry.
            return
        qta.set_defaults(color="#e8eaf0")
        cls._initialized = True

    # ── Application ─────────────────────────────────────────────────────

    @classmethod
    def app(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.gamepad")

    # ── Status / action icons ───────────────────────────────────────────

    @classmethod
    def check(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.check-circle")

    @classmethod
    def error(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.times-circle")

    @classmethod
    def skip(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.step-forward")

    @classmethod
    def stop(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.stop-circle")

    @classmethod
    def search(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.search")

    @classmethod
    def folder_open(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.folder-open")

    @classmethod
    def settings(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.cog")

    @classmethod
    def queue(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.list")

    @classmethod
    def download(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.download")

    @classmethod
    def upload(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.upload")

    @classmethod
    def close(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.times")

    @classmethod
    def back(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.arrow-left")

    @classmethod
    def forward(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.arrow-right")

    @classmethod
    def play(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.play")

    @classmethod
    def pause(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.pause")

    @classmethod
    def retry(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.redo-alt")

    @classmethod
    def trash(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.trash-alt")

    # ── Navigation icons ────────────────────────────────────────────────

    @classmethod
    def reports(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.file-alt")

    @classmethod
    def library(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.book")

    @classmethod
    def collections(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.layer-group")

    @classmethod
    def match_review(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.search-plus")

    @classmethod
    def activity(cls) -> QtGui.QIcon:
        cls._ensure()
        return qta.icon("fa5s.scroll")

    # ── Semantic colour variants ────────────────────────────────────────

    @classmethod
    def status_success(cls) -> QtGui.QIcon:
        """Green check icon for success notifications."""
        cls._ensure()
        return qta.icon("fa5s.check-circle", color="#66c38a")

    @classmethod
    def status_warning(cls) -> QtGui.QIcon:
        """Yellow warning icon."""
        cls._ensure()
        return qta.icon("fa5s.exclamation-triangle", color="#f0b75c")

    @classmethod
    def status_error(cls) -> QtGui.QIcon:
        """Red error icon."""
        cls._ensure()
        return qta.icon("fa5s.times-circle", color="#ef7777")

    @classmethod
    def status_info(cls) -> QtGui.QIcon:
        """Blue info icon."""
        cls._ensure()
        return qta.icon("fa5s.info-circle", color="#2f5f9e")

# Additional dashboard actions are assigned after the class definition to keep
# compatibility with older imports while expanding the semantic icon surface.
def _icon_factory(name: str, color: str | None = None):
    def _factory(cls):
        cls._ensure()
        kwargs = {"color": color} if color else {}
        return qta.icon(name, **kwargs)
    return classmethod(_factory)

Icons.add = _icon_factory("fa5s.plus")
Icons.refresh = _icon_factory("fa5s.sync-alt")
Icons.trash = _icon_factory("fa5s.trash-alt")
Icons.file = _icon_factory("fa5s.file")
Icons.database = _icon_factory("fa5s.database")
Icons.chart = _icon_factory("fa5s.chart-line")
Icons.warning = _icon_factory("fa5s.exclamation-triangle")
Icons.copy = _icon_factory("fa5s.copy")
Icons.external = _icon_factory("fa5s.external-link-alt")
Icons.play = _icon_factory("fa5s.play")
Icons.pause = _icon_factory("fa5s.pause")
Icons.retry = _icon_factory("fa5s.redo")
Icons.filter = _icon_factory("fa5s.filter")
Icons.image = _icon_factory("fa5s.image")
Icons.save = _icon_factory("fa5s.save")
