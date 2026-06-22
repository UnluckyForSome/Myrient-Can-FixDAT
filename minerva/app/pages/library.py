"""Polished faceted browser for the indexed torrent library."""

from __future__ import annotations

import enum
import logging
import time
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QModelIndex, QPoint, Qt
from superqt import QToggleSwitch

from minerva.app.app_state import AppState
from minerva.app.pages.base import BasePage
from minerva.app.task_runner import TaskRunner
from minerva.domain.library import LibraryFacets, LibraryItem, LibraryQuery
from minerva.ui.icons import Icons
from minerva.ui.models.delegates import (
    CheckboxDelegate,
    DisplayDelegate,
    SizeDelegate,
    TagPillDelegate,
)
from minerva.ui.models.record_model import ColumnSpec, RecordListModel
from minerva.ui.widgets.content_state import ContentState
from minerva.ui.widgets.cover_art import CoverProvider
from minerva.ui.widgets.empty_state import EmptyState
from minerva.ui.widgets.facet_list import FacetList
from minerva.ui.widgets.library_inspector import LibraryInspector
from minerva.ui.widgets.library_summary import LibrarySummaryBar
from minerva.ui.widgets.notification_banner import NotificationBanner
from minerva.ui.widgets.page_header import PageHeader
from minerva.ui.widgets.pagination_bar import PaginationBar
from minerva.ui.widgets.responsive_workspace import ResponsiveWorkspace
from minerva.ui.widgets.search_toolbar import SearchToolbar
from minerva.ui.widgets.tag_flow import TagFlow
from minerva_db import MinervaDB
from minerva_state import MinervaState

log = logging.getLogger(__name__)


class PageState(enum.Enum):
    PRE_INDEX = "pre_index"
    EMPTY = "empty"
    LOADING = "loading"
    RESULTS = "results"
    ERROR = "error"


def _source_label(item: LibraryItem) -> str:
    name = Path(item.source_torrent).stem
    for prefix in ("Minerva_Myrient - ", "Minerva Myrient - "):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


_LIBRARY_COLUMNS: list[ColumnSpec[LibraryItem]] = [
    ColumnSpec(header="", accessor=lambda item: False, is_checkbox=True),
    ColumnSpec(header="Game", accessor=lambda item: item.stem),
    ColumnSpec(header="Collection", accessor=lambda item: item.collection),
    ColumnSpec(header="System", accessor=lambda item: item.system or "Unknown"),
    ColumnSpec(header="Size", accessor=lambda item: item.size),
    ColumnSpec(header="Source", accessor=_source_label),
    ColumnSpec(
        header="Tags",
        accessor=lambda item: tuple(dict.fromkeys((*item.regions, *item.tags))),
        format_fn=lambda values: ", ".join(values),
    ),
]
LibraryTableModel = RecordListModel[LibraryItem]

_SORT_FIELDS = {1: "stem", 2: "collection", 3: "system", 4: "size"}


class LibraryPage(BasePage):
    """SQL-paginated library browser with polished facets and inspector."""

    def __init__(self, app_state: AppState) -> None:
        super().__init__(app_state)
        self.setObjectName("pageSurface")
        self._pool = QtCore.QThreadPool.globalInstance()
        self._generation = 0
        self._page = 0
        self._sort_field = "stem"
        self._descending = False
        self._current_item: LibraryItem | None = None
        self._db: MinervaDB | None = None
        self._settings = QtCore.QSettings("MinervaFixDAT", "MinervaGUI")
        try:
            self._db = MinervaDB()
        except Exception:
            log.warning("Library index unavailable", exc_info=True)

        self._cover_provider = CoverProvider(self._settings.value("cover_dir", "covers", str))
        self._model = LibraryTableModel([], _LIBRARY_COLUMNS, self)
        self._build_table()
        self._build_header()
        self._build_filter_toolbar()
        self._build_workspace()
        self._build_states()
        self._build_root_layout()

        self._app_state.index_state_changed.connect(lambda _value: self.refresh())
        self._app_state.selected_count_changed.connect(self._on_selected_count_changed)
        self._set_state(PageState.RESULTS)
        QtCore.QTimer.singleShot(0, lambda: self._search_now(reset_page=True))

    def _build_table(self) -> None:
        self._view = QtWidgets.QTableView(self)
        self._view.setObjectName("libraryTable")
        self._view.setModel(self._model)
        self._view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self._view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self._view.setAlternatingRowColors(False)
        self._view.setShowGrid(False)
        self._view.setWordWrap(False)
        self._view.verticalHeader().hide()
        self._view.verticalHeader().setDefaultSectionSize(42)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)
        self._view.selectionModel().selectionChanged.connect(self._on_row_selected)
        self._view.setItemDelegate(DisplayDelegate(self._view))
        self._view.setItemDelegateForColumn(0, CheckboxDelegate(self._view))
        self._view.setItemDelegateForColumn(4, SizeDelegate(self._view))
        self._view.setItemDelegateForColumn(6, TagPillDelegate(self._view))
        self._view.horizontalHeader().sortIndicatorChanged.connect(self._on_sort_changed)
        self._view.setSortingEnabled(True)
        header = self._view.horizontalHeader()
        header.setHighlightSections(False)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for column, width in {0: 42, 2: 110, 3: 190, 4: 88, 5: 150, 6: 210}.items():
            header.resizeSection(column, width)
        self._model.dataChanged.connect(self._on_checks_changed)

        QtGui.QShortcut(
            QtGui.QKeySequence.StandardKey.Copy, self._view,
            self._copy_selected_cell,
        )

    def _build_header(self) -> None:
        self._header = PageHeader(
            "Library",
            "Search the indexed collection, refine results, and stage games for download.",
        )
        self._export_btn = self._header.add_action("Export DAT", Icons.file())
        self._queue_btn = self._header.add_action("Add to queue", Icons.add(), primary=True)
        self._open_btn = self._header.add_action("Open file", Icons.folder_open())
        self._export_btn.clicked.connect(self._export_selected_dat)
        self._queue_btn.clicked.connect(self._queue_selected)
        self._open_btn.clicked.connect(self._open_selected_file)
        self._export_btn.setEnabled(False)
        self._queue_btn.setEnabled(False)
        self._open_btn.setEnabled(False)

    def _build_filter_toolbar(self) -> None:
        self._search = SearchToolbar(
            show_collection_filter=True,
            show_system_filter=True,
            placeholder="Search titles, filenames, systems\u2026",
            parent=self,
        )
        self._populate_combos()
        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self._search_now)
        self._search._search_input.textChanged.connect(lambda: self._search_timer.start())
        self._search.search_triggered.connect(lambda _text: self._search_now(reset_page=True))
        self._search.filter_changed.connect(lambda _name, _value: self._filters_changed())

        self._selected_only = QToggleSwitch("Selected only")
        self._selected_only.setObjectName("selectedOnlyToggle")
        self._selected_only.toggled.connect(lambda _checked: self._search_now(reset_page=True))

        self._clear_filters_btn = QtWidgets.QPushButton(Icons.close(), "Clear")
        self._clear_filters_btn.setObjectName("subtleButton")
        self._clear_filters_btn.clicked.connect(self._clear_all_filters)

        self._toolbar = QtWidgets.QFrame()
        self._toolbar.setObjectName("libraryToolbar")
        toolbar_layout = QtWidgets.QHBoxLayout(self._toolbar)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        toolbar_layout.setSpacing(10)
        toolbar_layout.addWidget(self._search, 1)
        toolbar_layout.addWidget(self._selected_only)
        toolbar_layout.addWidget(self._clear_filters_btn)

        self._active_filters = TagFlow(self)
        self._active_filters.setObjectName("activeLibraryFilters")
        self._active_filters.tag_toggled.connect(self._on_active_filter_toggled)
        self._active_filters.setVisible(False)
        self._summary_bar = LibrarySummaryBar(self)

    def _build_workspace(self) -> None:
        self._region_facets = FacetList("Region")
        self._category_facets = FacetList("Category")
        self._tag_facets = FacetList("Tags")
        for facets in (self._region_facets, self._category_facets, self._tag_facets):
            facets.selection_changed.connect(self._facets_changed)

        facet_panel = QtWidgets.QFrame()
        facet_panel.setObjectName("facetPanel")
        facet_panel.setMinimumWidth(240)
        facet_panel.setMaximumWidth(300)
        facet_layout = QtWidgets.QVBoxLayout(facet_panel)
        facet_layout.setContentsMargins(14, 14, 14, 14)
        facet_layout.setSpacing(10)
        facet_header = QtWidgets.QHBoxLayout()
        facet_title = QtWidgets.QLabel("Refine library")
        facet_title.setObjectName("sectionTitle")
        facet_header.addWidget(facet_title)
        facet_header.addStretch(1)
        facet_clear = QtWidgets.QToolButton()
        facet_clear.setObjectName("iconButton")
        facet_clear.setIcon(Icons.close())
        facet_clear.setToolTip("Clear facet filters")
        facet_clear.clicked.connect(self._clear_facets)
        facet_header.addWidget(facet_clear)
        facet_layout.addLayout(facet_header)

        divider = QtWidgets.QFrame()
        divider.setObjectName("separator")
        divider.setFixedHeight(1)
        facet_layout.addWidget(divider)

        facet_content = QtWidgets.QWidget()
        facet_content_layout = QtWidgets.QVBoxLayout(facet_content)
        facet_content_layout.setContentsMargins(0, 0, 0, 0)
        facet_content_layout.setSpacing(12)
        facet_content_layout.addWidget(self._region_facets)
        facet_content_layout.addWidget(self._category_facets)
        facet_content_layout.addWidget(self._tag_facets)
        facet_content_layout.addStretch(1)
        facet_scroll = QtWidgets.QScrollArea()
        facet_scroll.setObjectName("facetScroll")
        facet_scroll.setWidgetResizable(True)
        facet_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        facet_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        facet_scroll.setWidget(facet_content)
        facet_layout.addWidget(facet_scroll, 1)

        self._pagination = PaginationBar(page_size=50)
        self._pagination.setObjectName("libraryPagination")
        self._pagination.page_changed.connect(self._on_page_changed)
        self._pagination.page_size_changed.connect(lambda _size: self._search_now(reset_page=True))

        # ── Workspace panel ─────────────────────────────────────────────
        workspace = QtWidgets.QFrame()
        workspace.setObjectName("workspacePanel")
        workspace_layout = QtWidgets.QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        table_heading = QtWidgets.QFrame()
        table_heading.setObjectName("libraryResultsHeader")
        heading_layout = QtWidgets.QHBoxLayout(table_heading)
        heading_layout.setContentsMargins(14, 10, 14, 10)
        heading_layout.setSpacing(8)
        title = QtWidgets.QLabel("Library results")
        title.setObjectName("sectionTitle")
        heading_layout.addWidget(title)
        self._scope_label = QtWidgets.QLabel("All collections \xb7 All systems")
        self._scope_label.setObjectName("mutedLabel")
        heading_layout.addWidget(self._scope_label)
        heading_layout.addStretch(1)
        self._results_count = QtWidgets.QLabel("0 results")
        self._results_count.setObjectName("panelCount")
        heading_layout.addWidget(self._results_count)
        workspace_layout.addWidget(table_heading)
        workspace_layout.addWidget(self._view, 1)
        workspace_layout.addWidget(self._pagination)

        self._inspector = LibraryInspector(self)
        self._inspector.queue_requested.connect(self._queue_current)
        self._inspector.dat_requested.connect(self._export_current_dat)
        self._inspector.copy_requested.connect(self._copy_current_path)
        self._inspector.open_requested.connect(self._open_selected_file)

        # ── Responsive workspace ────────────────────────────────────────
        self._rworkspace = ResponsiveWorkspace(
            facet_panel, workspace, self._inspector,
        )

        self._results_widget = QtWidgets.QWidget()
        results_layout = QtWidgets.QVBoxLayout(self._results_widget)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.addWidget(self._rworkspace)

    def _build_states(self) -> None:
        self._pre_index_state = EmptyState(
            icon=Icons.collections(),
            title="Library index unavailable",
            description="Build or select an index from Collections before browsing games.",
        )
        self._empty_state = EmptyState(
            icon=Icons.search(),
            title="No games found",
            description="Try a broader search or clear one of the active filters.",
            action_text="Clear filters",
        )
        self._empty_state.action_clicked.connect(self._clear_all_filters)

        self._error_state = EmptyState(
            icon=Icons.status_error(),
            title="Library search failed",
            description="The index could not be queried.",
            action_text="Retry",
        )
        self._error_state.action_clicked.connect(lambda: self._search_now(reset_page=False))

        self._state = ContentState()

    def _build_root_layout(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)
        root.addWidget(self._header)
        root.addWidget(self._toolbar)
        root.addWidget(self._active_filters)
        root.addWidget(self._summary_bar)
        root.addWidget(self._state, 1)

    def _set_state(self, state: PageState) -> None:
        if state == PageState.PRE_INDEX:
            self._state.set_empty(self._pre_index_state)
        elif state == PageState.EMPTY:
            self._state.set_empty(self._empty_state)
        elif state == PageState.LOADING:
            self._state.set_loading("Searching the index\u2026")
        elif state == PageState.ERROR:
            self._state.set_error("")
        elif state == PageState.RESULTS:
            self._state.set_content(self._results_widget)

    def activate(self) -> None:
        self._on_selected_count_changed(len(self._selected_file_ids()))

    def prepare_close(self) -> None:
        sizes = self._rworkspace._splitter.sizes() if hasattr(self, "_rworkspace") else None
        if sizes:
            self._settings.setValue("library/splitter_sizes", sizes)
        self._settings.setValue("library/header_state", self._view.horizontalHeader().saveState())
        self._settings.setValue("library/search", self._search.search_text())
        self._settings.setValue("library/collection", self._search.collection())
        self._settings.setValue("library/system", self._search.system())
        self._settings.setValue("library/selected_only", self._selected_only.isChecked())

    def _restore_page_state(self) -> None:
        # Splitter sizes restored from ResponsiveWorkspace or settings
        pass

    def refresh(self) -> None:
        try:
            self._db = MinervaDB()
            self._populate_combos()
            self._search_now(reset_page=False)
        except Exception as exc:
            self._error_state.set_description(str(exc))
            self._set_state(PageState.ERROR)

    def _populate_combos(self) -> None:
        if self._db is None:
            return
        try:
            collection = self._search.collection() if hasattr(self, "_search") else ""
            self._search.set_collections(self._db.get_collections())
            if collection:
                self._search.set_collection(collection)
            self._populate_systems_for_collection()
        except Exception:
            log.warning("Failed to populate library filters", exc_info=True)

    def _populate_systems_for_collection(self) -> None:
        if self._db is None:
            return
        current_system = self._search.system()
        self._search.set_systems(self._db.get_systems(self._search.collection() or None))
        if current_system:
            self._search.set_system(current_system)

    def _filters_changed(self) -> None:
        self._populate_systems_for_collection()
        self._update_active_filters()
        self._search_now(reset_page=True)

    def _facets_changed(self) -> None:
        self._update_active_filters()
        self._search_now(reset_page=True)

    def _clear_facets(self) -> None:
        for facets in (self._region_facets, self._category_facets, self._tag_facets):
            facets.blockSignals(True)
            facets.clear_selection()
            facets.blockSignals(False)
        self._update_active_filters()
        self._search_now(reset_page=True)

    def _clear_all_filters(self) -> None:
        self._search_timer.stop()
        self._search.clear()
        self._selected_only.setChecked(False)
        for facets in (self._region_facets, self._category_facets, self._tag_facets):
            facets.blockSignals(True)
            facets.clear_selection()
            facets.blockSignals(False)
        self._active_filters.set_tags([])
        self._active_filters.setVisible(False)
        self._search_now(reset_page=True)

    def _selected_file_ids(self) -> tuple[int, ...]:
        values: list[int] = []
        for key in self._app_state.selected_game_ids:
            if key.startswith("library:"):
                try:
                    values.append(int(key.split(":", 1)[1]))
                except ValueError:
                    continue
        return tuple(sorted(set(values)))

    def _build_query(self) -> LibraryQuery:
        return LibraryQuery(
            text=self._search.search_text().strip(),
            collection=self._search.collection(),
            system=self._search.system(),
            tags=frozenset(self._tag_facets.selected_values()),
            regions=frozenset(self._region_facets.selected_values()),
            categories=frozenset(self._category_facets.selected_values()),
            selected_only=self._selected_only.isChecked(),
            file_ids=self._selected_file_ids() if self._selected_only.isChecked() else (),
            offset=self._page * self._pagination.page_size(),
            limit=self._pagination.page_size(),
            sort_field=self._sort_field,
            descending=self._descending,
        )

    def _search_now(self, reset_page: bool = False) -> None:
        if self._db is None:
            self._set_state(PageState.PRE_INDEX)
            return
        if reset_page:
            self._page = 0
        self._generation += 1
        generation = self._generation
        self._set_state(PageState.LOADING)
        task = TaskRunner(self._search_task, generation, self._build_query())
        task.signals.result.connect(self._on_search_result)
        task.signals.error.connect(lambda details, gen=generation: self._on_search_error(gen, details))
        self._pool.start(task)

    @staticmethod
    def _search_task(
        generation: int,
        query: LibraryQuery,
    ) -> tuple[int, list[LibraryItem], int, LibraryFacets, float]:
        started = time.perf_counter()
        db = MinervaDB()
        items, total = db.search_library(query)
        facets = db.get_library_facets(query)
        return generation, items, total, facets, (time.perf_counter() - started) * 1000

    def _on_search_result(self, payload: object) -> None:
        generation, items, total, facets, elapsed_ms = payload  # type: ignore[misc]
        if generation != self._generation:
            return
        self._model.set_records(items)
        selected = self._app_state.selected_game_ids
        for row, item in enumerate(items):
            if f"library:{item.id}" in selected:
                self._model.setData(
                    self._model.index(row, 0),
                    Qt.CheckState.Checked,
                    Qt.ItemDataRole.CheckStateRole,
                )
        self._pagination.configure(total, self._page)
        self._region_facets.set_facets(facets.regions, self._region_facets.selected_values())
        self._category_facets.set_facets(facets.categories, self._category_facets.selected_values())
        self._tag_facets.set_facets(facets.tags[:30], self._tag_facets.selected_values())
        self._summary_bar.set_results(total, self._page, self._pagination.page_size(), elapsed_ms)
        self._summary_bar.set_selected(len(self._selected_file_ids()))
        self._results_count.setText(f"{total:,} results")
        collection = self._search.collection() or "All collections"
        system = self._search.system() or "All systems"
        self._scope_label.setText(f"{collection} \xb7 {system}")
        self._update_active_filters()
        self._set_state(PageState.RESULTS if items else PageState.EMPTY)
        if items:
            self._view.selectRow(0)
        else:
            self._set_current_item(None)

    def _on_search_error(self, generation: int, details: str) -> None:
        if generation != self._generation:
            return
        self._error_state.set_description(details)
        self._set_state(PageState.ERROR)

    def _on_page_changed(self, page: int) -> None:
        self._page = page
        self._search_now()

    def _on_sort_changed(self, column: int, order: Qt.SortOrder) -> None:
        if column not in _SORT_FIELDS:
            return
        self._sort_field = _SORT_FIELDS[column]
        self._descending = order == Qt.SortOrder.DescendingOrder
        self._search_now(reset_page=True)

    def _on_checks_changed(self, _top: QModelIndex, _bottom: QModelIndex) -> None:
        selected = set(self._app_state.selected_game_ids)
        for row, item in enumerate(self._model._records):
            key = f"library:{item.id}"
            selected.discard(key)
            if self._model._check_states.get(row) == Qt.CheckState.Checked:
                selected.add(key)
        self._app_state.set_selected(selected)

    def _on_selected_count_changed(self, _count: int) -> None:
        count = len(self._selected_file_ids())
        self._summary_bar.set_selected(count)
        self._queue_btn.setEnabled(count > 0)
        self._export_btn.setEnabled(count > 0)

    def _on_row_selected(self) -> None:
        rows = self._view.selectionModel().selectedRows()
        if not rows:
            self._set_current_item(None)
            return
        row = rows[0].row()
        self._set_current_item(
            self._model._records[row] if 0 <= row < len(self._model._records) else None
        )

    def _downloaded_path(self, item: LibraryItem) -> Path | None:
        records = MinervaState().find_queue_for_file(item.id)
        return next(
            (Path(record.destination) for record in records if Path(record.destination).exists()),
            None,
        )

    def _set_current_item(self, item: LibraryItem | None) -> None:
        self._current_item = item
        if item is None:
            self._inspector.clear()
            self._open_btn.setEnabled(False)
            return
        downloaded = self._downloaded_path(item) is not None
        self._inspector.set_item(
            item,
            self._cover_provider.resolve(item),
            downloaded=downloaded,
        )
        self._open_btn.setEnabled(downloaded)

    def _update_active_filters(self) -> None:
        filters: list[str] = []
        if self._search.search_text().strip():
            filters.append(f"Search: {self._search.search_text().strip()}")
        if self._search.collection():
            filters.append(f"Collection: {self._search.collection()}")
        if self._search.system():
            filters.append(f"System: {self._search.system()}")
        filters += [f"Region: {value}" for value in sorted(self._region_facets.selected_values())]
        filters += [f"Category: {value}" for value in sorted(self._category_facets.selected_values())]
        filters += [f"Tag: {value}" for value in sorted(self._tag_facets.selected_values())]
        if self._selected_only.isChecked():
            filters.append("Selected only")
        self._active_filters.set_tags(filters, set(filters))
        self._active_filters.setVisible(bool(filters))

    def _on_active_filter_toggled(self, label: str, checked: bool) -> None:
        if checked:
            return
        if label.startswith("Search: "):
            self._search.set_search_text("")
        elif label.startswith("Collection: "):
            self._search.set_collection("")
            self._populate_systems_for_collection()
        elif label.startswith("System: "):
            self._search.set_system("")
        elif label == "Selected only":
            self._selected_only.setChecked(False)
        else:
            prefix, _, value = label.partition(": ")
            target = {
                "Region": self._region_facets,
                "Category": self._category_facets,
                "Tag": self._tag_facets,
            }.get(prefix)
            if target is not None:
                target.uncheck_value(value)
        self._update_active_filters()
        self._search_now(reset_page=True)

    def _current_or_selected_items(self) -> list[LibraryItem]:
        ids = self._selected_file_ids()
        if not ids and self._current_item is not None:
            return [self._current_item]
        items = [item for item in self._model._records if item.id in ids]
        return items

    def _queue_selected(self) -> None:
        items = self._current_or_selected_items()
        if not items:
            return
        shell = self.window()
        controller = getattr(shell, "download_controller", None)
        if controller is None:
            NotificationBanner.show_error(
                self,
                "Downloads unavailable",
                "qBittorrent controller is not initialised",
            )
            return
        output_root = Path(self._settings.value("output_dir", "downloads", str))
        queue_items = [
            (item.id, str(output_root / item.collection / item.system / item.basename), None)
            for item in items
        ]
        controller.queue_items(queue_items)
        NotificationBanner.show_success(
            self, "Queued",
            f"{len(queue_items)} item(s) added to downloads",
        )

    def _queue_current(self) -> None:
        if self._current_item is not None:
            self._queue_selected()

    def _export_selected_dat(self) -> None:
        items = self._current_or_selected_items()
        self._export_items(items)

    def _export_current_dat(self) -> None:
        if self._current_item is not None:
            self._export_items([self._current_item])

    def _export_items(self, items: list[LibraryItem]) -> None:
        if not items or self._db is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export DAT", "minerva-selection.dat", "DAT files (*.dat)",
        )
        if not path:
            return
        rows = [{"stem": item.stem, "basename": item.basename, "size": item.size} for item in items]
        Path(path).write_text(
            self._db.build_synthetic_dat(rows, "Minerva selection"),
            encoding="utf-8",
        )
        NotificationBanner.show_success(self, "DAT exported", path)

    def _copy_current_path(self) -> None:
        if self._current_item:
            QtWidgets.QApplication.clipboard().setText(self._current_item.path_in_torrent)
            NotificationBanner.show_info(self, "Path copied", self._current_item.path_in_torrent)

    def _copy_selected_cell(self) -> None:
        index = self._view.currentIndex()
        if index.isValid():
            text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
            QtWidgets.QApplication.clipboard().setText(text)

    def _open_selected_file(self) -> None:
        item = self._current_item
        if item is None:
            return
        target = self._downloaded_path(item)
        if target is None:
            NotificationBanner.show_info(self, "Not downloaded", "Queue this item before opening it")
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(target)))

    def _on_context_menu(self, pos: QPoint) -> None:
        index = self._view.indexAt(pos)
        menu = QtWidgets.QMenu(self)
        if index.isValid():
            self._view.selectRow(index.row())
            menu.addAction(Icons.add(), "Add to queue", self._queue_current)
            menu.addAction(Icons.file(), "Generate DAT", self._export_current_dat)
            menu.addSeparator()
            menu.addAction(Icons.copy(), "Copy source path", self._copy_current_path)
            menu.addAction(Icons.folder_open(), "Open downloaded file", self._open_selected_file)
        else:
            menu.addAction(Icons.refresh(), "Refresh", self.refresh)
        menu.exec(self._view.viewport().mapToGlobal(pos))
