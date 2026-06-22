"""Reference-quality Downloads dashboard."""

from __future__ import annotations

import enum
import logging
import time
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.app.app_state import AppState
from minerva.app.download_controller import DownloadController
from minerva.app.page_id import PageId
from minerva.app.pages.base import BasePage
from minerva.domain.downloads import DownloadRuntime, DownloadStatus
from minerva.ui.icons import Icons
from minerva.ui.models.delegates import ActionDelegate, DisplayDelegate, ProgressDelegate
from minerva.ui.models.download_model import (
    DownloadRecord,
    DownloadTableModel,
    _DOWNLOAD_COLUMNS,
    format_speed,
)
from minerva.ui.notifications import NotificationService
from minerva.ui.widgets.activity_list import ActivityList
from minerva.ui.widgets.content_state import ContentState
from minerva.ui.widgets.cover_art import CoverProvider
from minerva.ui.widgets.download_inspector import DownloadInspector
from minerva.ui.widgets.empty_state import EmptyState
from minerva.ui.widgets.metric_card import MetricCard, MetricKind
from minerva.ui.widgets.metric_strip import MetricStrip
from minerva.ui.widgets.page_header import PageHeader
from minerva.ui.widgets.responsive_workspace import ResponsiveWorkspace
from minerva.ui.widgets.segmented_control import SegmentedControl
from minerva.ui.widgets.speed_chart import SpeedChart
from minerva.ui.widgets.surface_panel import SurfacePanel
from minerva_db import DEFAULT_INDEX_PATH, MinervaDB

log = logging.getLogger(__name__)


class DownloadPageState(enum.Enum):
    EMPTY = "empty"
    RESULTS = "results"


class _DownloadFilterProxy(QtCore.QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text = ""
        self._status = "all"
        # Disable automatic re-sort/re-filter on source changes; we
        # apply them explicitly on the events that actually matter.
        # Runtime telemetry ticks no longer trigger a cascade re-filter
        # across all rows.
        self.setDynamicSortFilter(False)

    def setSourceModel(self, source_model):  # noqa: N802
        previous = self.sourceModel()
        if previous is not None:
            try:
                previous.modelReset.disconnect(self.invalidateFilter)
            except (TypeError, RuntimeError):
                pass
            try:
                previous.dataChanged.disconnect(self._re_sort)
            except (TypeError, RuntimeError):
                pass
        super().setSourceModel(source_model)
        if source_model is not None:
            # Structural changes: re-apply the filter so newly visible
            # rows are filtered and removed rows disappear from the view.
            source_model.modelReset.connect(self.invalidateFilter)
            # Per-cell data changes: re-apply the current sort so row
            # order stays consistent with the active sort column. The
            # filter is intentionally NOT re-applied here — runtime ticks
            # don't change filter decisions (text and status are stable
            # per record; the haystack only mutates when torrent_name
            # changes, which is rare and cheap to re-check on demand).
            source_model.dataChanged.connect(self._re_sort)

    def _re_sort(self, *_args) -> None:
        col = self.sortColumn()
        if col >= 0:
            self.sort(col, self.sortOrder())

    def set_text(self, text: str) -> None:
        self._text = text.strip().casefold()
        self.invalidateFilter()

    def set_status(self, status: str) -> None:
        self._status = status
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):  # noqa: N802
        model = self.sourceModel()
        if not isinstance(model, DownloadTableModel):
            return True
        record = model.record_at(source_row)
        if record is None:
            return False

        status_groups = {
            "active": {
                DownloadStatus.STARTING,
                DownloadStatus.DOWNLOADING,
                DownloadStatus.PAUSED,
                DownloadStatus.SEEDING,
            },
            "queued": {DownloadStatus.QUEUED},
            "completed": {DownloadStatus.COMPLETED},
            "failed": {DownloadStatus.FAILED, DownloadStatus.CANCELLED},
        }
        if self._status != "all" and self._status in status_groups:
            if record.status not in status_groups[self._status]:
                return False

        if self._text and self._text not in record.haystack:
            return False
        return True


class DownloadsPage(BasePage):
    """Queue, telemetry, task inspector, throughput and recent activity."""

    def __init__(self, app_state: AppState) -> None:
        super().__init__(app_state)
        self.setObjectName("downloadsPage")
        self._settings = QtCore.QSettings("MinervaFixDAT", "MinervaGUI")
        self._notifications = NotificationService(self)
        self._controller: DownloadController | None = None
        self._library_items: dict[int, object] = {}
        self._cover_provider = CoverProvider(
            self._settings.value("cover_dir", "covers", str)
        )
        # Cached index-DB connection. Reopened only if ``index_path`` changes.
        self._minerva_db: MinervaDB | None = None
        self._minerva_db_path: str | None = None
        # Tracks the queue id of the record last shown in the inspector so
        # we can skip cover-art decode on every runtime tick.
        self._inspector_record_id: str | None = None
        # Idempotency: signature of the last successful queue refresh,
        # used to short-circuit duplicate ``queue_changed`` emissions
        # (the controller fires both ``queue_changed`` and
        # ``app_state.queue_changed`` in lockstep and this page is
        # connected to both).
        self._last_refresh_signature: tuple | None = None
        # Speed-throttle: last total download speed observed on a
        # runtime tick. ``_update_dashboard`` is skipped when this is
        # unchanged, because no aggregate-bearing field can have moved.
        self._last_total_down: float | None = None
        # Tracks whether the user explicitly chose a filter tab. When
        # ``False`` the smart default is applied on first data load.
        self._user_set_filter = False
        self._resolve_controller()

        self._model = DownloadTableModel([], _DOWNLOAD_COLUMNS, parent=self)
        self._proxy = _DownloadFilterProxy(self)
        self._proxy.setSourceModel(self._model)

        self._build_ui()
        self._wire_signals()
        self._restore_layout()
        self._refresh_from_controller()

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        self._header = PageHeader(
            "Downloads",
            "Manage the active queue, monitor progress, and control qBittorrent tasks.",
        )
        self._pause_all_btn = self._header.add_action("Pause all", Icons.pause())
        self._resume_all_btn = self._header.add_action("Resume", Icons.play())
        self._cancel_selected_btn = self._header.add_action(
            "Cancel selected", Icons.trash(), danger=True
        )
        root.addWidget(self._header)

        # ── KPI strip ──────────────────────────────────────────────────
        self._active_metric = MetricCard(
            "Active", "0", MetricKind.INFO,
            icon=Icons.download(), subtitle="No active transfers",
        )
        self._down_speed_metric = MetricCard(
            "Download speed", "0 B/s", MetricKind.NEUTRAL,
            icon=Icons.download(), subtitle="Total throughput",
        )
        self._up_speed_metric = MetricCard(
            "Upload speed", "0 B/s", MetricKind.NEUTRAL,
            icon=Icons.upload(), subtitle="Total seeding",
        )
        self._queued_metric = MetricCard(
            "Queued", "0", MetricKind.PURPLE,
            icon=Icons.queue(), subtitle="Waiting items",
        )
        self._metric_strip = MetricStrip([
            self._active_metric,
            self._down_speed_metric,
            self._up_speed_metric,
            self._queued_metric,
        ])
        root.addWidget(self._metric_strip)

        self._empty_state = EmptyState(
            icon=Icons.download(),
            title="Your download queue is empty",
            description="Select games in Library or approve report matches to add them here.",
            action_text="Open Library",
        )
        self._empty_state.action_clicked.connect(self._open_library)

        self._content_state = QtWidgets.QStackedWidget()
        self._content_state.addWidget(self._empty_state)  # index 0 = EMPTY
        content = self._build_content_widget()
        self._content_state.addWidget(content)  # index 1 = RESULTS
        root.addWidget(self._content_state, 1)

    def _build_content_widget(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Queue panel ─────────────────────────────────────────────────
        self._queue_panel = SurfacePanel("Download Queue")
        self._queue_panel.body_layout.setSpacing(0)

        # Connection status (compact inline row)
        connection_row = QtWidgets.QFrame()
        connection_row.setObjectName("downloadConnectionInline")
        connection_layout = QtWidgets.QHBoxLayout(connection_row)
        connection_layout.setContentsMargins(0, 4, 0, 4)
        connection_layout.setSpacing(4)
        self._connection_dot = QtWidgets.QLabel("\u25cf")
        self._connection_dot.setObjectName("downloadConnectionDot")
        connection_layout.addWidget(self._connection_dot)
        self._qbit_status = QtWidgets.QLabel("Checking qBittorrent\u2026")
        self._qbit_status.setObjectName("downloadConnectionText")
        connection_layout.addWidget(self._qbit_status)
        connection_layout.addStretch(1)
        self._settings_btn = QtWidgets.QPushButton("Connection settings")
        self._settings_btn.setObjectName("linkButton")
        self._settings_btn.clicked.connect(self._open_settings)
        connection_layout.addWidget(self._settings_btn)
        self._queue_panel.body_layout.addWidget(connection_row)

        # Toolbar: search + status tabs
        toolbar = QtWidgets.QFrame()
        toolbar.setObjectName("downloadToolbar")
        toolbar_layout = QtWidgets.QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 8, 0, 8)
        toolbar_layout.setSpacing(10)
        self._search = QtWidgets.QLineEdit()
        self._search.setObjectName("downloadSearch")
        self._search.setPlaceholderText("Search downloads\u2026")
        self._search.setClearButtonEnabled(True)
        toolbar_layout.addWidget(self._search, 1)
        self._segments = SegmentedControl([
            ("all", "All"),
            ("active", "Active"),
            ("queued", "Queued"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        ])
        toolbar_layout.addWidget(self._segments)
        self._queue_panel.body_layout.addWidget(toolbar)

        # Table view
        self._view = QtWidgets.QTableView()
        self._view.setObjectName("downloadsTable")
        self._view.setModel(self._proxy)
        self._view.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._view.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._view.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._view.setAlternatingRowColors(True)
        self._view.setSortingEnabled(True)
        self._view.setShowGrid(False)
        self._view.verticalHeader().hide()
        self._view.verticalHeader().setDefaultSectionSize(46)
        self._view.setItemDelegateForColumn(0, DisplayDelegate(self._view))
        self._progress_delegate = ProgressDelegate(self._view)
        self._view.setItemDelegateForColumn(2, self._progress_delegate)
        self._action_delegate = ActionDelegate(self._view)
        self._view.setItemDelegateForColumn(7, self._action_delegate)
        self._action_delegate.action_triggered.connect(self._on_action)
        header = self._view.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.resizeSection(0, 120)
        header.resizeSection(2, 130)
        header.resizeSection(3, 100)
        header.resizeSection(4, 82)
        header.resizeSection(6, 220)

        # Bottom tab panel (replaces old bottom splitter)
        self._bottom_tabs = QtWidgets.QTabWidget()
        self._bottom_tabs.setObjectName("downloadBottomTabs")
        self._bottom_tabs.setFixedHeight(220)
        self._bottom_tabs.tabBar().setObjectName("bottomTabBar")

        self._speed_chart = SpeedChart()
        self._bottom_tabs.addTab(self._speed_chart, "Throughput")

        activity_tab = QtWidgets.QWidget()
        activity_tab_layout = QtWidgets.QVBoxLayout(activity_tab)
        activity_tab_layout.setContentsMargins(0, 0, 0, 0)
        activity_tab_layout.setSpacing(0)
        activity_header_row = QtWidgets.QHBoxLayout()
        activity_title = QtWidgets.QLabel("Recent activity")
        activity_title.setObjectName("panelTitle")
        activity_header_row.addWidget(activity_title)
        activity_header_row.addStretch(1)
        self._activity_list = ActivityList(max_items=50)
        self._clear_activity_btn = QtWidgets.QPushButton("Clear")
        self._clear_activity_btn.setObjectName("linkButton")
        self._clear_activity_btn.clicked.connect(self._activity_list.clear)
        activity_header_row.addWidget(self._clear_activity_btn)
        activity_tab_layout.addLayout(activity_header_row)
        activity_tab_layout.addWidget(self._activity_list)
        self._bottom_tabs.addTab(activity_tab, "Activity")

        # Workspace: table stacked above bottom tabs
        workspace = QtWidgets.QWidget()
        workspace_layout = QtWidgets.QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(6)
        workspace_layout.addWidget(self._view, 1)
        workspace_layout.addWidget(self._bottom_tabs)

        # Inspector
        self._inspector = DownloadInspector()
        self._inspector.pause_requested.connect(self._pause_record)
        self._inspector.resume_requested.connect(self._resume_record)
        self._inspector.retry_requested.connect(self._retry_record)
        self._inspector.remove_requested.connect(self._remove_record)
        self._inspector.open_folder_requested.connect(self._open_folder)

        # ResponsiveWorkspace — navigator collapsed (0 width)
        self._nav_placeholder = QtWidgets.QWidget()
        self._rworkspace = ResponsiveWorkspace(
            self._nav_placeholder, workspace, self._inspector,
        )
        self._rworkspace._splitter.setSizes([0, 960, 340])
        self._queue_panel.body_layout.addWidget(self._rworkspace, 1)

        # Summary bar
        self._summary = QtWidgets.QFrame()
        self._summary.setObjectName("downloadSummaryBar")
        summary_layout = QtWidgets.QHBoxLayout(self._summary)
        summary_layout.setContentsMargins(0, 8, 0, 8)
        self._range_label = QtWidgets.QLabel("0 downloads")
        self._range_label.setObjectName("downloadSummaryText")
        summary_layout.addWidget(self._range_label)
        self._error_summary = QtWidgets.QLabel("")
        self._error_summary.setObjectName("downloadErrorSummary")
        self._error_summary.setVisible(False)
        summary_layout.addWidget(self._error_summary)
        summary_layout.addStretch(1)
        self._selected_label = QtWidgets.QLabel("0 selected")
        self._selected_label.setObjectName("downloadSummaryText")
        summary_layout.addWidget(self._selected_label)
        self._speed_label = QtWidgets.QLabel("0 B/s down")
        self._speed_label.setObjectName("downloadSummarySpeed")
        summary_layout.addWidget(self._speed_label)
        self._queue_panel.body_layout.addWidget(self._summary)

        layout.addWidget(self._queue_panel, 1)
        return widget

    def _wire_signals(self) -> None:
        self._search.textChanged.connect(self._proxy.set_text)
        self._segments.current_changed.connect(self._on_status_filter)
        self._pause_all_btn.clicked.connect(self._pause_all)
        self._resume_all_btn.clicked.connect(self._resume_all)
        self._cancel_selected_btn.clicked.connect(self._cancel_selected)
        self._view.selectionModel().selectionChanged.connect(
            self._on_selection_changed
        )
        self._view.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._view.customContextMenuRequested.connect(self._show_context_menu)
        self._app_state.qbit_state_changed.connect(self._on_qbit_state_changed)
        self._app_state.queue_changed.connect(self._refresh_from_controller)

        wm = getattr(self._app_state, "worker_manager", None)
        if wm is not None and hasattr(wm, "downloads_changed"):
            wm.downloads_changed.connect(self._refresh_from_controller)

        if self._controller is not None:
            self._controller.activity_event.connect(self._on_activity_event)
            self._controller.queue_changed.connect(self._refresh_from_controller)
            self._controller.runtime_changed.connect(self._on_runtime_changed)

        self._pending_qbit_state = self._app_state.qbit_state

    def _resolve_controller(self) -> None:
        shell = self.window()
        if (
            hasattr(shell, "download_controller")
            and shell.download_controller is not None
        ):
            self._controller = shell.download_controller

    def _get_controller(self) -> DownloadController | None:
        if self._controller is None:
            self._resolve_controller()
        return self._controller

    def _refresh_from_controller(self) -> None:
        controller = self._get_controller()
        if controller is not None:
            try:
                queue = controller.get_queue()
            except Exception as exc:
                log.warning("Failed to refresh download queue", exc_info=True)
                self._notifications.error("Queue unavailable", str(exc))
                return
        else:
            wm = getattr(self._app_state, "worker_manager", None)
            if wm is not None and hasattr(wm, "_downloads"):
                queue = wm._downloads
            else:
                return

        records = []
        for index, dl in enumerate(queue):
            if hasattr(dl, "filename"):
                record = DownloadRecord(
                    id=getattr(dl, "id", index + 1),
                    queue_id=getattr(dl, "queue_id", str(getattr(dl, "id", index + 1))),
                    file_id=getattr(dl, "file_id", None) or index + 1,
                    filename=dl.filename,
                    url=getattr(dl, "url", ""),
                    status=dl.status,
                    torrent_name=getattr(dl, "torrent_name", "") or dl.filename,
                )
            else:
                record = DownloadRecord(
                    id=getattr(dl, "id", index + 1),
                    queue_id=getattr(dl, "id", str(index + 1)),
                    file_id=getattr(dl, "file_id", None) or index + 1,
                    filename=getattr(dl, "filename", ""),
                    url="",
                    status=dl.status,
                )
            records.append(record)

        self._model.set_records(records)
        if records:
            self._content_state.setCurrentIndex(1)
        else:
            self._content_state.setCurrentIndex(0)

    def _load_library_items(
        self, file_ids: list[int]
    ) -> dict[int, object]:
        if not file_ids:
            return {}
        try:
            db = self._get_minerva_db()
        except Exception:
            log.debug("Could not open index database", exc_info=True)
            return {}
        try:
            return {
                item.id: item
                for item in db.get_files_by_ids(file_ids)
            }
        except Exception:
            log.debug(
                "Could not enrich queue with library metadata", exc_info=True
            )
            return {}

    def _get_minerva_db(self) -> MinervaDB:
        """Return a cached :class:`MinervaDB`; reopen if ``index_path`` changed.

        Opening a SQLite handle on every queue refresh was the dominant
        UI-thread cost in the Downloads page's hot path. The handle is
        cheap to keep alive for the page lifetime; we only reopen when the
        configured index path changes (rare, user-driven via Settings).
        """
        settings_path = self._settings.value(
            "index_path", str(DEFAULT_INDEX_PATH), str
        )
        if self._minerva_db is None or self._minerva_db_path != settings_path:
            self._minerva_db = MinervaDB(settings_path)
            self._minerva_db_path = settings_path
        return self._minerva_db

    def _on_runtime_changed(self, runtimes: list[DownloadRuntime]) -> None:
        runtime_map = {runtime.record_id: runtime for runtime in runtimes}
        changed_rows: list[int] = []
        for row in range(self._model.rowCount()):
            record = self._model.record_at(row)
            if record is None or record.queue_id not in runtime_map:
                continue
            runtime = runtime_map[record.queue_id]
            record.progress = runtime.progress
            record.speed = runtime.download_speed
            record.upload_speed = runtime.upload_speed
            record.eta_seconds = runtime.eta
            record.peers = runtime.peers
            record.seeds = runtime.seeds
            record.ratio = runtime.ratio
            record.save_path = runtime.save_path
            old_torrent_name = record.torrent_name
            record.torrent_name = runtime.torrent_name or record.torrent_name
            if record.torrent_name != old_torrent_name:
                # Keep the filter haystack in sync with the new torrent
                # name. This is the only field that drives haystack
                # mutation at runtime.
                record.haystack = " ".join(
                    (
                        record.filename,
                        record.destination,
                        record.torrent_name,
                        record.collection,
                        record.system,
                    )
                ).casefold()
            changed_rows.append(row)
        # Emit one ``dataChanged`` per actually-changed row instead of a
        # single full-table blast. The view repaints only those rows, and
        # the filter proxy only re-evaluates the changed rows. Roles are
        # restricted to ``[DisplayRole, UserRole]`` so the view does not
        # refetch check-state or tooltip data.
        if changed_rows:
            last_col = self._model.columnCount() - 1
            roles = [
                QtCore.Qt.ItemDataRole.DisplayRole,
                QtCore.Qt.ItemDataRole.UserRole,
            ]
            for row in changed_rows:
                top_left = self._model.index(row, 0)
                bottom_right = self._model.index(row, last_col)
                self._model.dataChanged.emit(top_left, bottom_right, roles)
        total_down = sum(runtime.download_speed for runtime in runtimes)
        total_up = sum(runtime.upload_speed for runtime in runtimes)
        self._speed_chart.add_data_point(total_down, total_up)
        self._speed_label.setText(f"{format_speed(total_down)} down")
        # Skip the aggregate dashboard work if total speed hasn't
        # changed — no aggregate-bearing field can have moved, so the
        # counts and subtitles are still valid.
        if total_down != self._last_total_down:
            self._last_total_down = total_down
            self._update_dashboard()

    def _update_dashboard(self) -> None:
        records = [
            self._model.record_at(row) for row in range(self._model.rowCount())
        ]
        records = [record for record in records if record is not None]
        active_states = {
            DownloadStatus.STARTING,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.PAUSED,
            DownloadStatus.SEEDING,
        }
        active = sum(record.status in active_states for record in records)
        completed = sum(
            record.status == DownloadStatus.COMPLETED for record in records
        )
        failed = sum(
            record.status == DownloadStatus.FAILED for record in records
        )
        queued = sum(
            record.status == DownloadStatus.QUEUED for record in records
        )
        total_down = sum(record.speed for record in records)
        total_up = sum(record.upload_speed for record in records)
        cancelled = sum(
            record.status == DownloadStatus.CANCELLED for record in records
        )

        # ── KPI strip ───────────────────────────────────────────────────
        self._active_metric.set_value(str(active))
        self._active_metric.set_subtitle(
            f"{format_speed(total_down)} down"
            if active else "No active transfers"
        )
        self._down_speed_metric.set_value(
            format_speed(total_down) if total_down > 0 else "0 B/s"
        )
        self._down_speed_metric.set_subtitle(
            "Active throughput" if total_down > 0 else "Total throughput"
        )
        self._up_speed_metric.set_value(
            format_speed(total_up) if total_up > 0 else "0 B/s"
        )
        self._up_speed_metric.set_subtitle(
            "Seeding" if total_up > 0 else "Total seeding"
        )
        self._queued_metric.set_value(str(queued))
        self._queued_metric.set_subtitle(
            "Waiting items" if queued else "No queued downloads"
        )

        # ── Segment counts ──────────────────────────────────────────────
        counts = {
            "all": len(records),
            "active": active,
            "queued": queued,
            "completed": completed,
            "failed": failed + cancelled,
        }
        self._segments.set_counts(counts)
        self._queue_panel.set_count(self._proxy.rowCount())
        self._range_label.setText(
            f"Showing {self._proxy.rowCount()} of {len(records)} downloads"
        )
        self._selected_label.setText(
            f"{len(self._selected_queue_ids())} selected"
        )

        # ── Error summary grouping ──────────────────────────────────────
        failed_records = [r for r in records if r.status == DownloadStatus.FAILED]
        if failed_records:
            err_cats: dict[str, int] = {}
            for r in failed_records:
                err = (r.error_message or "").lower()
                if any(kw in err for kw in ("missing", "not found", "source")):
                    cat = "missing source"
                elif any(kw in err for kw in ("qbit", "torrent")):
                    cat = "qBittorrent errors"
                elif any(kw in err for kw in ("destination", "path", "conflict")):
                    cat = "destination conflicts"
                else:
                    cat = "other"
                err_cats[cat] = err_cats.get(cat, 0) + 1
            parts = [f"{v} {k}" for k, v in err_cats.items()]
            self._error_summary.setText(
                f"{len(failed_records)} failed: {', '.join(parts)}"
            )
            self._error_summary.setVisible(True)
        else:
            self._error_summary.setVisible(False)

        # ── Action button states ────────────────────────────────────────
        self._pause_all_btn.setEnabled(
            any(record.status in active_states for record in records)
        )
        self._resume_all_btn.setEnabled(
            any(
                record.status in {DownloadStatus.QUEUED, DownloadStatus.PAUSED}
                for record in records
            )
        )
        self._cancel_selected_btn.setEnabled(
            bool(self._selected_queue_ids())
        )
        self._sync_inspector_if_changed()

    def _apply_smart_default_filter(self, records: list) -> None:
        """Switch to Active or Failed tab on first load when applicable."""
        active_states = {
            DownloadStatus.STARTING,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.PAUSED,
            DownloadStatus.SEEDING,
        }
        active = sum(r.status in active_states for r in records)
        failed = sum(r.status == DownloadStatus.FAILED for r in records)
        if active:
            target = "active"
        elif failed:
            target = "failed"
        else:
            return
        self._segments.set_current(target)
        self._proxy.set_status(target)
        self._update_dashboard()

    def _on_status_filter(self, key: str) -> None:
        self._user_set_filter = True
        self._proxy.set_status(key)
        self._settings.setValue("downloads/filter", key)
        self._update_dashboard()

    def _on_selection_changed(self) -> None:
        self._update_dashboard()

    def _selected_queue_ids(self) -> list[str]:
        result: list[str] = []
        if not hasattr(self, "_view"):
            return result
        for proxy_index in self._view.selectionModel().selectedRows():
            source = self._proxy.mapToSource(proxy_index)
            record = self._model.record_at(source.row())
            if record is not None:
                result.append(record.queue_id)
        return result

    def _selected_record(self) -> DownloadRecord | None:
        selected = self._view.selectionModel().selectedRows()
        if selected:
            return self._model.record_at(
                self._proxy.mapToSource(selected[0]).row()
            )
        active_states = {
            DownloadStatus.STARTING,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.SEEDING,
        }
        for row in range(self._model.rowCount()):
            record = self._model.record_at(row)
            if record is not None and record.status in active_states:
                return record
        return self._model.record_at(0)

    def _sync_inspector(self) -> None:
        record = self._selected_record()
        if record is None:
            self._inspector.clear()
            return
        item = self._library_items.get(record.file_id or -1)
        cover = self._cover_provider.resolve(item) if item is not None else None
        self._inspector.set_record(record, cover)

    def _sync_inspector_if_changed(self) -> None:
        """Call :meth:`_sync_inspector` only when the selected record changed.

        ``_update_dashboard`` runs on every runtime tick. The inspector sync
        triggers a cover-art resolve which can hit the disk; we only want
        to pay that cost when the user actually selected a different row.
        """
        record = self._selected_record()
        record_id = record.queue_id if record is not None else None
        if record_id == self._inspector_record_id:
            return
        self._inspector_record_id = record_id
        self._sync_inspector()

    def _restore_selection(self, queue_ids: list[str]) -> None:
        if not queue_ids:
            if self._proxy.rowCount():
                self._view.selectRow(0)
            return
        selection = self._view.selectionModel()
        for source_row in range(self._model.rowCount()):
            record = self._model.record_at(source_row)
            if record is None or record.queue_id not in queue_ids:
                continue
            proxy = self._proxy.mapFromSource(
                self._model.index(source_row, 0)
            )
            if proxy.isValid():
                selection.select(
                    proxy,
                    QtCore.QItemSelectionModel.SelectionFlag.Select
                    | QtCore.QItemSelectionModel.SelectionFlag.Rows,
                )

    def _pause_all(self) -> None:
        controller = self._get_controller()
        if controller is not None:
            controller.pause_all()

    def _resume_all(self) -> None:
        controller = self._get_controller()
        if controller is not None:
            controller.resume_all()

    def _cancel_selected(self) -> None:
        ids = self._selected_queue_ids()
        if not ids:
            return
        if not self._notifications.confirm(
            "Remove selected downloads?",
            f"Remove {len(ids)} queue entries? Downloaded files will be kept.",
        ):
            return
        controller = self._get_controller()
        if controller is not None:
            controller.remove_many(ids, delete_files=False)

    def _pause_record(self, record_id: str) -> None:
        controller = self._get_controller()
        if controller is not None:
            controller.pause(record_id)

    def _resume_record(self, record_id: str) -> None:
        controller = self._get_controller()
        if controller is not None:
            controller.resume(record_id)

    def _retry_record(self, record_id: str) -> None:
        controller = self._get_controller()
        if controller is not None:
            controller.retry(record_id)

    def _remove_record(self, record_id: str) -> None:
        if not self._notifications.confirm(
            "Remove from queue?", "The downloaded file will be kept."
        ):
            return
        controller = self._get_controller()
        if controller is not None:
            controller.remove(record_id, delete_files=False)

    def _open_folder(self, value: str) -> None:
        if not value:
            return
        path = Path(value).expanduser()
        folder = path if path.is_dir() else path.parent
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(folder))
        )

    def _show_context_menu(self, position: QtCore.QPoint) -> None:
        record = self._selected_record()
        if record is None:
            return
        menu = QtWidgets.QMenu(self)
        if record.status in {
            DownloadStatus.STARTING,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.SEEDING,
        }:
            menu.addAction(
                Icons.pause(),
                "Pause",
                lambda: self._pause_record(record.queue_id),
            )
        elif record.status in {DownloadStatus.QUEUED, DownloadStatus.PAUSED}:
            menu.addAction(
                Icons.play(),
                "Resume",
                lambda: self._resume_record(record.queue_id),
            )
        if record.status == DownloadStatus.FAILED:
            menu.addAction(
                Icons.retry(),
                "Retry",
                lambda: self._retry_record(record.queue_id),
            )
        menu.addAction(
            Icons.folder_open(),
            "Open folder",
            lambda: self._open_folder(
                record.destination or record.save_path
            ),
        )
        menu.addSeparator()
        menu.addAction(
            Icons.trash(),
            "Remove from queue",
            lambda: self._remove_record(record.queue_id),
        )
        menu.exec(self._view.viewport().mapToGlobal(position))

    def _on_activity_event(self, category: str, message: str) -> None:
        self._activity_list.add_event(
            category, message, time.strftime("%H:%M:%S")
        )

    def _on_action(self, proxy_index: QtCore.QModelIndex, action: str) -> None:
        source_index = self._proxy.mapToSource(proxy_index)
        record = self._model.record_at(source_index.row())
        if record is None:
            return
        wm = getattr(self._app_state, "worker_manager", None)
        if wm is not None and hasattr(wm, "pause"):
            if action == "pause":
                wm.pause(record.id)
            elif action == "resume":
                wm.resume(record.id)
            elif action == "remove":
                wm.remove(record.id)
            return
        controller = self._get_controller()
        if controller is not None:
            if action == "pause":
                controller.pause(record.queue_id)
            elif action == "resume":
                controller.resume(record.queue_id)
            elif action == "remove":
                controller.remove(record.queue_id, delete_files=False)

    def _on_qbit_state_changed(self, connected: object) -> None:
        is_connected = bool(connected)
        self._connection_dot.setText("\u25cf")
        self._connection_dot.setProperty("connected", is_connected)
        self._connection_dot.style().unpolish(self._connection_dot)
        self._connection_dot.style().polish(self._connection_dot)
        self._qbit_status.setText(
            "qBittorrent connected"
            if is_connected
            else "qBittorrent disconnected"
        )

    def _open_library(self) -> None:
        shell = self.window()
        if hasattr(shell, "show_page"):
            shell.show_page(PageId.LIBRARY)

    def _open_settings(self) -> None:
        shell = self.window()
        if hasattr(shell, "show_page"):
            shell.show_page(PageId.SETTINGS)

    def _restore_layout(self) -> None:
        filter_key = self._settings.value("downloads/filter", None, str)
        if filter_key is not None:
            self._segments.set_current(filter_key)
            self._proxy.set_status(filter_key)
            self._user_set_filter = True
        ws = getattr(self, "_rworkspace", None)
        if ws is not None:
            value = self._settings.value("downloads/workspace_splitter")
            if isinstance(value, list) and value:
                ws._splitter.setSizes([int(part) for part in value])
        tab_index = self._settings.value("downloads/bottom_tab", 0, int)
        if hasattr(self, "_bottom_tabs"):
            self._bottom_tabs.setCurrentIndex(tab_index)
        header_state = self._settings.value("downloads/header_state")
        if header_state and hasattr(self, "_view"):
            self._view.horizontalHeader().restoreState(header_state)

    def _save_layout(self) -> None:
        self._settings.setValue(
            "downloads/workspace_splitter", self._rworkspace._splitter.sizes()
        )
        self._settings.setValue(
            "downloads/bottom_tab", self._bottom_tabs.currentIndex()
        )
        self._settings.setValue(
            "downloads/header_state",
            self._view.horizontalHeader().saveState(),
        )

    def activate(self) -> None:
        self._refresh_from_controller()
        if hasattr(self, "_pending_qbit_state"):
            self._on_qbit_state_changed(self._pending_qbit_state)
            del self._pending_qbit_state

    def deactivate(self) -> None:
        self._save_layout()

    def prepare_close(self) -> None:
        self._save_layout()
