"""Category-based Settings dashboard matching the application mockup."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6 import QtCore, QtWidgets
from superqt import QToggleSwitch

from minerva.app.app_state import AppState
from minerva.app.pages.base import BasePage
from minerva.app.task_runner import TaskRunner
from minerva.domain.settings import AccentName, SettingsDraft, ThemeName
from minerva.ui.density import DENSITY_SETTINGS_KEY, Density
from minerva.ui.icons import Icons
from minerva.ui.widgets.content_state import ContentState
from minerva.ui.widgets.notification_banner import NotificationBanner
from minerva.ui.widgets.page_header import PageHeader
from minerva.ui.widgets.path_picker import PathPicker
from minerva.ui.widgets.status_badge import BadgeKind, StatusBadge
from minerva.ui.widgets.surface_panel import SurfacePanel

log = logging.getLogger(__name__)


def _connection_task(url: str, username: str, password: str) -> str:
    from minerva_qbit import QBittorrentClient

    client = QBittorrentClient(url, username, password)
    client.login()
    return client.test_connection()


class SettingsPage(BasePage):
    """Persistent settings editor with dirty-state protection and live preview."""

    CATEGORIES = ("General", "Downloads", "qBittorrent", "Library", "Sources", "Appearance", "Advanced")

    def __init__(
        self,
        app_state: AppState,
        settings_org: str = "MinervaFixDAT",
        settings_app: str = "MinervaGUI",
    ) -> None:
        super().__init__(app_state)
        self._settings = QtCore.QSettings(settings_org, settings_app)
        self._pool = QtCore.QThreadPool.globalInstance()
        self._draft = SettingsDraft()
        self._dirty = False
        self._loading = False
        self._load_draft()

        self._header = PageHeader(
            "Settings",
            "Configure downloads, indexing, qBittorrent, and application behavior.",
        )

        self._category_list = QtWidgets.QListWidget()
        self._category_list.setObjectName("settingsCategories")
        self._category_list.setFixedWidth(190)
        icons = {
            "General": Icons.settings(),
            "Downloads": Icons.download(),
            "qBittorrent": Icons.queue(),
            "Library": Icons.library(),
            "Sources": Icons.external(),
            "Appearance": Icons.image(),
            "Advanced": Icons.database(),
        }
        for category in self.CATEGORIES:
            self._category_list.addItem(QtWidgets.QListWidgetItem(icons[category], category))
        self._category_list.currentRowChanged.connect(self._stack_category_changed)

        self._pages = QtWidgets.QStackedWidget()
        self._pages.addWidget(self._build_general_page())
        self._pages.addWidget(self._build_downloads_page())
        self._pages.addWidget(self._build_qbit_page())
        self._pages.addWidget(self._build_library_page())
        self._pages.addWidget(self._build_sources_page())
        self._pages.addWidget(self._build_appearance_page())
        self._pages.addWidget(self._build_advanced_page())

        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)
        body.addWidget(self._category_list)
        body.addWidget(self._pages, 1)

        self._restore_btn = QtWidgets.QPushButton(Icons.refresh(), "Restore defaults")
        self._restore_btn.clicked.connect(self._restore_defaults)
        self._cancel_btn = QtWidgets.QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._save_btn = QtWidgets.QPushButton(Icons.save(), "Save changes")
        self._save_btn.setObjectName("primaryButton")
        self._save_btn.clicked.connect(self._on_save)
        footer = QtWidgets.QHBoxLayout()
        footer.addWidget(self._restore_btn)
        footer.addStretch(1)
        footer.addWidget(self._cancel_btn)
        footer.addWidget(self._save_btn)

        # Wrap body + footer in a content widget for ContentState
        content_widget = QtWidgets.QWidget()
        content_layout_outer = QtWidgets.QVBoxLayout(content_widget)
        content_layout_outer.setContentsMargins(0, 0, 0, 0)
        content_layout_outer.addLayout(body, 1)
        content_layout_outer.addLayout(footer)

        self._state = ContentState()
        self._state.set_content(content_widget)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(14)
        root.addWidget(self._header)
        root.addWidget(self._state, 1)

        self._connect_dirty_signals()
        self._apply_draft_to_form()
        self._category_list.setCurrentRow(1)
        self._set_dirty(False)

    # ── Page builders ───────────────────────────────────────────────────

    @staticmethod
    def _scroll_page(card: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(card)
        return scroll

    def _build_general_page(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        notifications = SurfacePanel("Application behavior", icon=Icons.settings())
        self._notifications_toggle = QToggleSwitch("Show desktop and in-app notifications")
        self._open_destination_toggle = QToggleSwitch("Open destination when a download finishes")
        notifications.body_layout.addWidget(self._notifications_toggle)
        notifications.body_layout.addWidget(self._open_destination_toggle)
        layout.addWidget(notifications)
        layout.addStretch(1)
        return self._scroll_page(container)

    def _build_downloads_page(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        card = SurfacePanel("Downloads", icon=Icons.download())
        form = QtWidgets.QFormLayout()
        self._download_method = QtWidgets.QComboBox()
        self._download_method.addItem("qBittorrent", "qbit")
        form.addRow("Download method", self._download_method)
        self._output_picker = PathPicker("", parent=self)
        form.addRow("Output directory", self._output_picker)
        self._keep_seeding = QToggleSwitch("Keep completed torrents seeding")
        self._hardlinks = QToggleSwitch("Create hardlinks in library")
        self._preserve_partial = QToggleSwitch("Preserve partial downloads")
        form.addRow("", self._keep_seeding)
        form.addRow("", self._hardlinks)
        form.addRow("", self._preserve_partial)
        self._max_concurrent = QtWidgets.QSpinBox()
        self._max_concurrent.setRange(1, 50)
        form.addRow("Max concurrent torrents", self._max_concurrent)
        self._timeout = QtWidgets.QSpinBox()
        self._timeout.setRange(30, 86400)
        self._timeout.setSuffix(" sec")
        form.addRow("Timeout per batch", self._timeout)
        card.body_layout.addLayout(form)
        layout.addWidget(card)
        layout.addStretch(1)
        return self._scroll_page(container)

    def _build_qbit_page(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        card = SurfacePanel("qBittorrent connection", icon=Icons.queue())
        form = QtWidgets.QFormLayout()
        self._qbit_url = QtWidgets.QLineEdit()
        self._qbit_url.setPlaceholderText("http://127.0.0.1:8080")
        self._qbit_user = QtWidgets.QLineEdit()
        self._qbit_password = QtWidgets.QLineEdit()
        self._qbit_password.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        form.addRow("Connection URL", self._qbit_url)
        form.addRow("Username", self._qbit_user)
        form.addRow("Password", self._qbit_password)
        connection_row = QtWidgets.QHBoxLayout()
        self._test_btn = QtWidgets.QPushButton(Icons.queue(), "Test connection")
        self._test_btn.setObjectName("primaryButton")
        self._test_btn.clicked.connect(self._on_test_connection)
        self._connection_badge = StatusBadge("Not tested", BadgeKind.NEUTRAL)
        connection_row.addWidget(self._test_btn)
        connection_row.addWidget(self._connection_badge)
        connection_row.addStretch(1)
        form.addRow("", connection_row)
        card.body_layout.addLayout(form)
        layout.addWidget(card)
        layout.addStretch(1)
        return self._scroll_page(container)

    def _build_library_page(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        card = SurfacePanel("Library and index", icon=Icons.library())
        form = QtWidgets.QFormLayout()
        self._torrent_picker = PathPicker("", parent=self)
        self._index_edit = QtWidgets.QLineEdit()
        self._index_browse = QtWidgets.QPushButton("Browse\u2026")
        self._index_browse.clicked.connect(self._browse_index)
        index_row = QtWidgets.QHBoxLayout()
        index_row.addWidget(self._index_edit, 1)
        index_row.addWidget(self._index_browse)
        self._cover_picker = PathPicker("", parent=self)
        form.addRow("Torrent source directory", self._torrent_picker)
        form.addRow("Index database", index_row)
        form.addRow("Cover directory", self._cover_picker)
        card.body_layout.addLayout(form)
        layout.addWidget(card)
        layout.addStretch(1)
        return self._scroll_page(container)

    def _build_sources_page(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)

        card = SurfacePanel("CDRomance / RetroGameTalk", icon=Icons.external())
        card.body_layout.addWidget(
            QtWidgets.QLabel(
                "Browse and download from the game repository directly within the app. "
                "Log in using the embedded browser, then search and download without "
                "leaving Minerva."
            )
        )
        form = QtWidgets.QFormLayout()
        self._source_url = QtWidgets.QLineEdit()
        self._source_url.setPlaceholderText("https://cdromance.org")
        form.addRow("Site URL", self._source_url)

        self._source_open_btn = QtWidgets.QPushButton(Icons.external(), "Open repo in embedded browser")
        self._source_open_btn.setObjectName("primaryButton")
        self._source_open_btn.clicked.connect(self._on_source_open)
        card.body_layout.addLayout(form)
        card.body_layout.addWidget(self._source_open_btn)
        layout.addWidget(card)
        layout.addStretch(1)
        return self._scroll_page(container)

    def _build_appearance_page(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        card = SurfacePanel("Appearance", icon=Icons.image())
        form = QtWidgets.QFormLayout()
        self._theme = QtWidgets.QComboBox()
        self._theme.addItem("Dark", ThemeName.DARK)
        self._density = QtWidgets.QComboBox()
        for density in Density:
            self._density.addItem(density.value.title(), density.value)
        self._accent = QtWidgets.QComboBox()
        for label, value in (("Blue", AccentName.BLUE), ("Purple", AccentName.PURPLE), ("Green", AccentName.GREEN)):
            self._accent.addItem(label, value)
        form.addRow("Theme", self._theme)
        form.addRow("Density", self._density)
        form.addRow("Accent color", self._accent)
        card.body_layout.addLayout(form)
        self._preview = QtWidgets.QFrame()
        self._preview.setObjectName("appearancePreview")
        self._preview.setMinimumHeight(150)
        preview_layout = QtWidgets.QHBoxLayout(self._preview)
        sidebar = QtWidgets.QFrame()
        sidebar.setFixedWidth(50)
        sidebar.setObjectName("previewSidebar")
        content = QtWidgets.QVBoxLayout()
        content.addWidget(QtWidgets.QLabel("Preview"))
        preview_button = QtWidgets.QPushButton("Primary action")
        preview_button.setObjectName("primaryButton")
        content.addWidget(preview_button)
        content.addStretch(1)
        preview_layout.addWidget(sidebar)
        preview_layout.addLayout(content, 1)
        card.body_layout.addWidget(self._preview)
        layout.addWidget(card)
        layout.addStretch(1)
        return self._scroll_page(container)

    def _build_advanced_page(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        card = SurfacePanel("Migration and diagnostics", icon=Icons.database())
        migrate = QtWidgets.QPushButton("Migrate legacy settings")
        migrate.clicked.connect(self._on_migrate_legacy)
        open_config = QtWidgets.QPushButton(Icons.folder_open(), "Open settings location")
        open_config.clicked.connect(self._open_settings_location)
        card.body_layout.addWidget(migrate)
        card.body_layout.addWidget(open_config)
        layout.addWidget(card)
        layout.addStretch(1)
        return self._scroll_page(container)

    # ── Draft lifecycle ─────────────────────────────────────────────────

    def _load_draft(self) -> None:
        s = self._settings
        self._draft = SettingsDraft(
            qbit_url=s.value("qbit_url", "http://localhost:8080", str),
            qbit_username=s.value("qbit_user", "admin", str),
            qbit_password=s.value("qbit_pass", "", str),
            output_directory=Path(s.value("output_dir", "downloads", str)),
            torrent_directory=Path(s.value("torrent_dir", "torrents/Minerva Myrient - 1050 torrents", str)),
            index_path=Path(s.value("index_path", "torrents/minerva_index.db", str)),
            cover_directory=Path(s.value("cover_dir", "covers", str)),
            keep_seeding=s.value("keep_seeding", True, bool),
            create_hardlinks=s.value("create_hardlinks", True, bool),
            preserve_partial=s.value("preserve_partial", True, bool),
            open_destination=s.value("open_destination", False, bool),
            notifications=s.value("notifications", True, bool),
            max_concurrent=int(s.value("max_concurrent", 6, int)),
            timeout_seconds=int(s.value("timeout_seconds", 1800, int)),
            density=Density(s.value(DENSITY_SETTINGS_KEY, Density.COMPACT.value, str)),
            theme=s.value("ui/theme", ThemeName.DARK, str),
            accent=s.value("ui/accent", AccentName.BLUE, str),
        )

    def _apply_draft_to_form(self) -> None:
        self._loading = True
        draft = self._draft
        self._output_picker.set_path(str(draft.output_directory))
        self._torrent_picker.set_path(str(draft.torrent_directory))
        self._index_edit.setText(str(draft.index_path))
        self._cover_picker.set_path(str(draft.cover_directory))
        self._qbit_url.setText(draft.qbit_url)
        self._qbit_user.setText(draft.qbit_username)
        self._qbit_password.setText(draft.qbit_password)
        self._keep_seeding.setChecked(draft.keep_seeding)
        self._hardlinks.setChecked(draft.create_hardlinks)
        self._preserve_partial.setChecked(draft.preserve_partial)
        self._open_destination_toggle.setChecked(draft.open_destination)
        self._notifications_toggle.setChecked(draft.notifications)
        self._max_concurrent.setValue(draft.max_concurrent)
        self._timeout.setValue(draft.timeout_seconds)
        self._density.setCurrentIndex(max(0, self._density.findData(draft.density.value)))
        self._theme.setCurrentIndex(max(0, self._theme.findData(draft.theme)))
        self._accent.setCurrentIndex(max(0, self._accent.findData(draft.accent)))
        self._source_url.setText(self._settings.value("source_url", "", str))
        self._loading = False

    def _form_to_draft(self) -> SettingsDraft:
        return SettingsDraft(
            qbit_url=self._qbit_url.text().strip(),
            qbit_username=self._qbit_user.text().strip(),
            qbit_password=self._qbit_password.text(),
            output_directory=Path(self._output_picker.path().strip() or "downloads"),
            torrent_directory=Path(self._torrent_picker.path().strip()),
            index_path=Path(self._index_edit.text().strip()),
            cover_directory=Path(self._cover_picker.path().strip() or "covers"),
            keep_seeding=self._keep_seeding.isChecked(),
            create_hardlinks=self._hardlinks.isChecked(),
            preserve_partial=self._preserve_partial.isChecked(),
            open_destination=self._open_destination_toggle.isChecked(),
            notifications=self._notifications_toggle.isChecked(),
            max_concurrent=self._max_concurrent.value(),
            timeout_seconds=self._timeout.value(),
            density=Density(self._density.currentData()),
            theme=self._theme.currentData(),
            accent=self._accent.currentData(),
        )

    def _connect_dirty_signals(self) -> None:
        for edit in (self._qbit_url, self._qbit_user, self._qbit_password, self._index_edit, self._output_picker.path_edit, self._torrent_picker.path_edit, self._cover_picker.path_edit):
            edit.textChanged.connect(self._on_form_changed)
        for combo in (self._theme, self._density, self._accent, self._download_method):
            combo.currentIndexChanged.connect(self._on_form_changed)
        for spin in (self._max_concurrent, self._timeout):
            spin.valueChanged.connect(self._on_form_changed)
        for toggle in (self._keep_seeding, self._hardlinks, self._preserve_partial, self._open_destination_toggle, self._notifications_toggle):
            toggle.toggled.connect(self._on_form_changed)
        self._density.currentIndexChanged.connect(self._preview_appearance)
        self._accent.currentIndexChanged.connect(self._preview_appearance)

    def _on_form_changed(self, *_args) -> None:
        if not self._loading:
            self._set_dirty(True)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self._save_btn.setEnabled(dirty)
        self._cancel_btn.setEnabled(dirty)
        self._header.set_subtitle(
            "Configure downloads, indexing, qBittorrent, and application behavior."
            + ("  ·  Unsaved changes" if dirty else "")
        )

    def _validate(self, draft: SettingsDraft) -> list[str]:
        errors: list[str] = []
        if not draft.qbit_url.startswith(("http://", "https://")):
            errors.append("qBittorrent URL must start with http:// or https://")
        if not str(draft.torrent_directory):
            errors.append("Torrent source directory is required")
        if not str(draft.index_path):
            errors.append("Index database path is required")
        for path, label in ((draft.output_directory, "Output directory"), (draft.cover_directory, "Cover directory")):
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                errors.append(f"{label} cannot be created: {exc}")
        return errors

    def _persist_draft(self) -> None:
        draft = self._draft
        values = {
            "qbit_url": draft.qbit_url,
            "qbit_user": draft.qbit_username,
            "qbit_pass": draft.qbit_password,
            "output_dir": str(draft.output_directory),
            "torrent_dir": str(draft.torrent_directory),
            "index_path": str(draft.index_path),
            "cover_dir": str(draft.cover_directory),
            "keep_seeding": draft.keep_seeding,
            "create_hardlinks": draft.create_hardlinks,
            "preserve_partial": draft.preserve_partial,
            "open_destination": draft.open_destination,
            "notifications": draft.notifications,
            "max_concurrent": draft.max_concurrent,
            "timeout_seconds": draft.timeout_seconds,
            DENSITY_SETTINGS_KEY: draft.density.value,
            "ui/theme": draft.theme,
            "ui/accent": draft.accent,
            "source_url": self._source_url.text().strip(),
        }
        for key, value in values.items():
            self._settings.setValue(key, value)
        self._settings.sync()

    def _on_save(self) -> None:
        draft = self._form_to_draft()
        errors = self._validate(draft)
        if errors:
            NotificationBanner.show_error(self, "Validation failed", "\n".join(errors), duration=7000)
            return
        self._draft = draft
        self._persist_draft()
        shell = self.window()
        if hasattr(shell, "apply_appearance"):
            shell.apply_appearance(draft.density, draft.accent)
        if hasattr(shell, "reload_download_controller"):
            shell.reload_download_controller()
        self._set_dirty(False)
        NotificationBanner.show_success(self, "Settings saved")

    def _on_cancel(self) -> None:
        self._load_draft()
        self._apply_draft_to_form()
        self._set_dirty(False)
        shell = self.window()
        if hasattr(shell, "apply_appearance"):
            shell.apply_appearance(self._draft.density, self._draft.accent)

    def can_deactivate(self) -> bool:
        if not self._dirty:
            return True
        reply = QtWidgets.QMessageBox.question(
            self,
            "Unsaved settings",
            "Discard unsaved settings changes?",
            QtWidgets.QMessageBox.StandardButton.Discard | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel,
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Discard:
            self._on_cancel()
            return True
        return False

    # ── Actions ─────────────────────────────────────────────────────────

    def _on_test_connection(self) -> None:
        url = self._qbit_url.text().strip()
        if not url.startswith(("http://", "https://")):
            NotificationBanner.show_error(self, "Invalid URL", "Enter a valid HTTP(S) qBittorrent URL")
            return
        self._test_btn.setEnabled(False)
        self._test_btn.setText("Testing…")
        task = TaskRunner(_connection_task, url, self._qbit_user.text().strip(), self._qbit_password.text())
        task.signals.result.connect(self._connection_success)
        task.signals.error.connect(self._connection_failed)
        self._pool.start(task)

    def _connection_success(self, version: object) -> None:
        self._test_btn.setEnabled(True)
        self._test_btn.setText("Test connection")
        self._connection_badge.setText(f"Connected · {version}")
        self._connection_badge.set_kind(BadgeKind.SUCCESS)

    def _connection_failed(self, details: str) -> None:
        self._test_btn.setEnabled(True)
        self._test_btn.setText("Test connection")
        self._connection_badge.setText("Connection failed")
        self._connection_badge.set_kind(BadgeKind.ERROR)
        NotificationBanner.show_error(self, "Connection failed", details)

    def _preview_appearance(self, *_args) -> None:
        if self._loading:
            return
        shell = self.window()
        if hasattr(shell, "apply_appearance"):
            shell.apply_appearance(Density(self._density.currentData()), self._accent.currentData())

    def _restore_defaults(self) -> None:
        self._draft = SettingsDraft()
        self._apply_draft_to_form()
        self._set_dirty(True)
        self._preview_appearance()

    def _browse_index(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Select index database", self._index_edit.text(), "SQLite database (*.db)")
        if path:
            self._index_edit.setText(path)

    def _stack_category_changed(self, row: int) -> None:
        if row >= 0:
            self._pages.setCurrentIndex(row)

    def _on_migrate_legacy(self) -> None:
        old = QtCore.QSettings("MinervaFixDAT", "MinervaGUI")
        migrated = 0
        for key in ("qbit_url", "qbit_user", "qbit_pass", "output_dir"):
            if old.contains(key):
                self._settings.setValue(key, old.value(key))
                migrated += 1
        self._settings.sync()
        self._load_draft()
        self._apply_draft_to_form()
        NotificationBanner.show_success(self, "Migration complete", f"Migrated {migrated} setting(s)")

    def _on_source_open(self) -> None:
        from PyQt6 import QtGui

        url = self._source_url.text().strip() or "https://cdromance.org"
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))

        try:
            from minerva.ui.widgets.repo_browser import _HAS_WEBENGINE, RepoDialog
            if _HAS_WEBENGINE:
                dialog = RepoDialog(url, self)
                dialog.exec()
        except ImportError:
            pass

    def _open_settings_location(self) -> None:
        from PyQt6 import QtGui

        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(Path(self._settings.fileName()).parent)))


