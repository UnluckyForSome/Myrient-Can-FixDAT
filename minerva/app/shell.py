"""
AppShell — thin QMainWindow owning navigation, page switching, and shared state.
"""

from __future__ import annotations

import logging
import typing
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.app.app_state import AppState
from minerva.app.download_controller import DownloadController
from minerva.app.app_sidebar import AppSidebar
from minerva.app.page_id import PageId
from minerva.app.page_registry import PageRegistry
from minerva.app.pages import (
    LibraryPage,
    ReportsPage,
    SettingsPage,
)
from minerva.app.worker_manager import WorkerManager
from minerva_db import DEFAULT_INDEX_PATH, DEFAULT_TORRENT_DIR, MinervaDB
from minerva_qbit import QBittorrentClient
from minerva_state import MinervaState
from minerva.ui.density import Density
from minerva.ui.theme import ThemeTokens, apply_theme
from minerva.ui.widgets.download_tray import DownloadTray
from minerva.ui.widgets.download_tray_content import DownloadTrayContent

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

log = logging.getLogger(__name__)


class AppShell(QtWidgets.QMainWindow):
    """Main application window — sidebar, stacked pages, shared state.

    Composition
    -----------
    *   ``AppState`` — in-memory signal bus (no DB, no QSettings).
    *   ``WorkerManager`` — download-worker and filter-thread lifecycles.
    *   ``PageRegistry`` — lazy page construction and caching.
    *   ``AppSidebar`` — 3 QAction-backed navigation rows (240 px fixed) + tray toggle.
    *   ``QStackedWidget`` — page surface (right of sidebar).

    ``QSettings`` keys owned by the shell:
    ``geometry``, ``window_state``, ``splitter_sizes``, ``current_tab``,
    ``ui/density``.

    Pages own their own QSettings keys: ``qbit_url``, ``qbit_user``,
    ``qbit_pass``, ``output_dir``, ``use_qbit``, ``recent_files``.
    AppState owns zero settings keys.

    Parameters
    ----------
    settings_org, settings_app
        QSettings organisation and application names.  Exposed for test
        isolation — production callers should never pass these.
    """

    def __init__(
        self,
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMFORTABLE,
        settings_org: str = "MinervaFixDAT",
        settings_app: str = "MinervaGUI",
    ) -> None:
        super().__init__()
        self._tokens = tokens
        self._density = density
        self._settings_org = settings_org
        self._settings_app = settings_app

        # ── Core owned objects ──────────────────────────────────────────
        self._app_state = AppState(self)
        self._worker_manager = WorkerManager(self)
        self._registry = PageRegistry(self)
        self._actions: dict[PageId, QtGui.QAction] = {}
        self._sidebar: AppSidebar | None = None
        self._stack = QtWidgets.QStackedWidget()
        self._current_page_id: PageId = PageId.REPORTS

        # ── Download controller (qBittorrent) ─────────────────────────
        self._qbit_settings_watcher: QtCore.QTimer | None = None
        self._download_controller: DownloadController | None = None
        self._closed: bool = False

        # Native QMainWindow chrome (no FramelessWindowHint)
        self.setWindowTitle("Minerva FixDAT")

        self._init_actions()
        self._init_ui()
        self._register_pages()
        self._create_download_controller()
        self._restore_settings_and_show_initial_page()

    # ── Public API ──────────────────────────────────────────────────────

    @property
    def app_state(self) -> AppState:
        return self._app_state

    @property
    def registry(self) -> PageRegistry:
        return self._registry

    @property
    def sidebar(self) -> AppSidebar | None:
        return self._sidebar

    @property
    def download_controller(self) -> DownloadController | None:
        return self._download_controller

    @property
    def worker_manager(self) -> WorkerManager:
        return self._worker_manager

    @property
    def tray(self) -> DownloadTray:
        return self._tray

    def show_page(self, page_id: PageId) -> None:
        """Show a page, respecting the current page's dirty-state contract."""
        current = self._stack.currentWidget()
        if current is not None and current is not self._registry._cache.get(page_id):
            if hasattr(current, "can_deactivate") and not current.can_deactivate():
                if self._sidebar is not None:
                    self._sidebar.set_active(self._current_page_id)
                return
            if hasattr(current, "deactivate"):
                current.deactivate()

        page = self._registry.get_or_create(page_id, self._app_state)
        if page.parentWidget() is not self._stack:
            self._stack.addWidget(page)
            self._restore_page_layout(page_id, page)
        self._stack.setCurrentWidget(page)
        self._current_page_id = page_id
        if self._sidebar is not None:
            self._sidebar.set_active(page_id)
        page.activate()

    def apply_appearance(self, density: Density, accent: str = "blue") -> None:
        """Apply density/accent immediately to all constructed pages."""
        self._density = density
        self._tokens = ThemeTokens.for_accent(accent)
        app = QtWidgets.QApplication.instance()
        if app is not None:
            apply_theme(app, self._tokens, self._density)
        if self._sidebar is not None:
            self._sidebar.apply_tokens(self._tokens)
            self._sidebar.apply_density(self._density)
        for page in self._registry.iter_constructed():
            for widget in [page, *page.findChildren(QtWidgets.QWidget)]:
                if hasattr(widget, "apply_tokens"):
                    widget.apply_tokens(self._tokens)
                if hasattr(widget, "apply_density"):
                    widget.apply_density(self._density)

    def reload_download_controller(self) -> None:
        """Recreate qBittorrent services after connection settings change."""
        if self._download_controller is not None:
            self._download_controller.stop_monitoring()
            self._download_controller.deleteLater()
        self._download_controller = None
        self._create_download_controller()
        self._app_state.queue_changed.emit()

    # ── Initialisation helpers ──────────────────────────────────────────

    def _init_actions(self) -> None:
        """Create 3 QActions — one per top-level navigation page."""
        labels = {
            PageId.REPORTS: "Reports",
            PageId.LIBRARY: "Library",
            PageId.SETTINGS: "Settings",
        }
        for pid in PageId:
            action = QtGui.QAction(labels[pid], self)
            action.triggered.connect(lambda _checked, p=pid: self.show_page(p))
            self._actions[pid] = action

    def _init_ui(self) -> None:
        """Build the central widget: sidebar (left) + stack/tray (right)."""
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        layout = QtWidgets.QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar
        self._sidebar = AppSidebar(
            actions=self._actions,
            tokens=self._tokens,
            density=self._density,
        )
        self._app_state.selected_count_changed.connect(
            self._sidebar.set_selection_count,
        )
        layout.addWidget(self._sidebar)

        # Right side: stack (top) + download tray (bottom)
        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # Stacked widget
        self._stack = QtWidgets.QStackedWidget()
        right_layout.addWidget(self._stack, stretch=1)

        # Download tray
        self._tray = DownloadTray(self._app_state)
        tray_content = DownloadTrayContent(self._app_state)
        self._tray.set_content(tray_content)
        right_layout.addWidget(self._tray)

        # Wire sidebar tray toggle → tray toggle
        self._sidebar.tray_toggled.connect(self._tray.toggle)

        layout.addWidget(right, stretch=1)

        # Status bar
        self.statusBar().showMessage("Ready")

        # Enable drag-and-drop on the central area
        self.setAcceptDrops(True)

    def _register_pages(self) -> None:
        """Register all page factories."""
        self._registry.register(
            PageId.REPORTS,
            lambda pid, st: ReportsPage(st),
        )
        self._registry.register(
            PageId.LIBRARY,
            lambda pid, st: LibraryPage(st),
        )
        self._registry.register(
            PageId.SETTINGS,
            lambda pid, st: SettingsPage(st),
        )

    def _restore_settings_and_show_initial_page(self) -> None:
        """Restore shell-owned QSettings keys and show saved/fallback tab."""
        settings = QtCore.QSettings(self._settings_org, self._settings_app)
        geo = settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        state = settings.value("window_state")
        if state is not None:
            self.restoreState(state)

        density_value = settings.value("ui/density", self._density.value, str)
        accent = settings.value("ui/accent", "blue", str)
        try:
            self.apply_appearance(Density(density_value), accent)
        except ValueError:
            self.apply_appearance(Density.COMPACT, accent)

        tab_value = settings.value("current_tab", "", str)
        saved_page = PageId.REPORTS
        if tab_value:
            try:
                saved_page = PageId(tab_value)
            except ValueError:
                saved_page = PageId.REPORTS
        self.show_page(saved_page)

    def _save_settings(self) -> None:
        """Persist shell-owned QSettings keys."""
        settings = QtCore.QSettings(self._settings_org, self._settings_app)
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("window_state", self.saveState())
        self._save_page_layouts(settings)
        settings.setValue("current_tab", self._current_page_id.value)
        settings.setValue(
            "ui/density",
            self._density.value,
        )

    def _auto_save_queue(self) -> None:
        """Best-effort auto-save of the download queue during close.

        No-op until a backend hook is wired; safe to call at any time.
        """
        # ponytail: intentionally a no-op; queue state is persisted via
        # _save_settings and per-page prepare_close. Kept as a hook so
        # closeEvent and tests can rely on it existing.
        return None

    def _save_page_layouts(self, settings: QtCore.QSettings) -> None:
        for page_id, page in self._registry._cache.items():
            for index, splitter in enumerate(page.findChildren(QtWidgets.QSplitter)):
                settings.setValue(
                    f"page_layouts/{page_id.value}/splitter_{index}",
                    splitter.sizes(),
                )

    def _restore_page_layout(self, page_id: PageId, page: QtWidgets.QWidget) -> None:
        settings = QtCore.QSettings(self._settings_org, self._settings_app)
        for index, splitter in enumerate(page.findChildren(QtWidgets.QSplitter)):
            sizes = settings.value(
                f"page_layouts/{page_id.value}/splitter_{index}",
                None,
            )
            if sizes:
                splitter.setSizes([int(value) for value in sizes])

    # ── Download controller lifecycle ────────────────────────────────────

    def _create_download_controller(self) -> None:
        """Build the persistent qBittorrent controller from saved settings."""
        settings = QtCore.QSettings(self._settings_org, self._settings_app)
        qbit_url = settings.value("qbit_url", "http://localhost:8080", str)
        qbit_user = settings.value("qbit_user", "admin", str)
        qbit_pass = settings.value("qbit_pass", "", str)
        seed_dir = settings.value("qbit_seed_dir", ".qbitseed", str)
        index_path = settings.value("index_path", str(DEFAULT_INDEX_PATH), str)
        state_path = settings.value("state_db_path", "data/minerva_state.db", str)

        try:
            client = QBittorrentClient(qbit_url, qbit_user, qbit_pass)
            db = MinervaDB(index_path)
            state = MinervaState(state_path)
            controller = DownloadController(state, self._app_state, client, seed_dir)
            controller.queue_changed.connect(self._app_state.queue_changed.emit)
            controller.error.connect(self._show_runtime_error)
            controller.runtime_changed.connect(self._app_state.runtime_changed.emit)
            controller.activity_event.connect(self._app_state.activity_event.emit)
            controller.file_spec_resolver = lambda file_id: db.get_download_spec(
                file_id,
                Path(settings.value("torrent_dir", str(DEFAULT_TORRENT_DIR), str)),
            )
            self._download_controller = controller
            # ponytail: monitoring is started on first showEvent, not here,
            # so shells constructed but never shown (e.g. attribute-only
            # unit tests) don't spawn a QThread that would be destroyed
            # while running during GC.
        except Exception as exc:
            log.warning("Download controller unavailable: %s", exc, exc_info=True)
            self._download_controller = None
            self.statusBar().showMessage(f"Downloads unavailable: {exc}", 8000)

    def _show_runtime_error(self, message: str) -> None:
        """Display a non-blocking status bar error message."""
        self.statusBar().showMessage(f"Error: {message}", 5000)

    # ── Drag-and-drop ───────────────────────────────────────────────────

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        """Accept drags with URLs (files) so the active page can handle them."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        """Delegate drop to the currently visible page."""
        current = self._stack.currentWidget()
        try:
            current.handle_drop(event)  # type: ignore[union-attr]
        except AttributeError:
            log.exception(
                "Current widget %r has no handle_drop", current,
            )

    # ── Window lifecycle ────────────────────────────────────────────────

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        # Start the qBittorrent monitor once the window is first shown.
        # start_monitoring is idempotent (no-op if already running).
        if self._download_controller is not None:
            self._download_controller.start_monitoring()

    def __del__(self) -> None:
        # Best-effort: stop the qBittorrent monitor QThread before the
        # parent-child cascade deletes it during GC. Qt aborts ("QThread:
        # Destroyed while thread is still running") otherwise, and
        # pytest-qt's addWidget never calls closeEvent at teardown.
        # __del__ runs before ~QObject, so children are still alive here.
        try:
            controller = getattr(self, "_download_controller", None)
            if controller is not None:
                controller.stop_monitoring()
        except Exception:
            pass

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """5-step pinned close order.

        1. Worker-prompt: if active, ask user; abort on Cancel.
        2. Auto-save queue (best-effort import from minerva_gui).
        3. Per-page ``prepare_close()`` on every constructed page.
        4. Persist shell-owned QSettings keys.
        5. Destroy / accept.

        Idempotent: a second close (e.g. qtbot teardown after ``close()``)
        just accepts without re-running the pipeline.
        """
        if self._closed:
            event.accept()
            return
        self._closed = True
        # Step 1 — worker-prompt: if a worker is active, ask user; abort on Cancel.
        if self._worker_manager.is_active() or (
            self._download_controller is not None
            and self._download_controller.has_active_downloads()
        ):
            reply = QtWidgets.QMessageBox.question(
                self,
                "Confirm Exit",
                "A worker is in progress. Stop it and exit?",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.Cancel,
                QtWidgets.QMessageBox.StandardButton.Cancel,
            )
            if reply == QtWidgets.QMessageBox.StandardButton.Cancel:
                event.ignore()
                return

        # Step 2 — auto-save queue (best-effort) + join workers
        self._auto_save_queue()
        self._worker_manager.prepare_shutdown()

        # Step 3 — per-page prepare_close
        for page in self._registry.iter_constructed():
            page.prepare_close()

        # Step 4 — persist settings
        self._save_settings()

        # Step 5 — destroy
        if self._download_controller is not None:
            self._download_controller.stop_monitoring()
            self._download_controller.deleteLater()
            self._download_controller = None
        while self._stack.count() > 0:
            w = self._stack.widget(0)
            self._stack.removeWidget(w)
            w.deleteLater()
        try:
            self._worker_manager.deleteLater()
        except RuntimeError:
            pass  # Already deleted during teardown
        super().closeEvent(event)
        event.accept()
