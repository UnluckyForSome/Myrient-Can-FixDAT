"""Content state — QStackedWidget with loading/empty/error/content states."""

from __future__ import annotations

from typing import Callable

from PyQt6 import QtCore, QtWidgets


class ContentState(QtWidgets.QStackedWidget):
    """A stacked widget that manages the four canonical page states.

    Replaces the per-page ``QStackedWidget`` of loading / empty / error /
    content widgets with a standardised interface.

    - ``set_loading``: shows a centered "Loading\u2026" label with an
      indeterminate progress bar.
    - ``set_empty``: shows the caller-supplied widget (typically an
      ``EmptyState`` instance).
    - ``set_error``: shows an error message with an optional retry button.
    - ``set_content``: shows the caller-supplied content widget.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        # Index 0 — loading
        self._loading = QtWidgets.QWidget()
        loading_layout = QtWidgets.QVBoxLayout(self._loading)
        loading_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._loading_label = QtWidgets.QLabel("Loading\u2026")
        self._loading_label.setObjectName("emptyStateTitle")
        loading_layout.addWidget(self._loading_label, 0, QtCore.Qt.AlignmentFlag.AlignCenter)
        self._loading_bar = QtWidgets.QProgressBar()
        self._loading_bar.setObjectName("contentStateLoadingBar")
        self._loading_bar.setRange(0, 0)
        self._loading_bar.setFixedWidth(220)
        loading_layout.addWidget(self._loading_bar, 0, QtCore.Qt.AlignmentFlag.AlignCenter)

        # Index 1 — empty (caller supplies the widget)
        self._empty = QtWidgets.QWidget()
        self._empty_layout = QtWidgets.QVBoxLayout(self._empty)
        self._empty_layout.setContentsMargins(0, 0, 0, 0)

        # Index 2 — error
        self._error = QtWidgets.QWidget()
        error_layout = QtWidgets.QVBoxLayout(self._error)
        error_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        error_layout.setSpacing(12)
        self._error_title = QtWidgets.QLabel("Something went wrong")
        self._error_title.setObjectName("emptyStateTitle")
        self._error_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        error_layout.addWidget(self._error_title)
        self._error_desc = QtWidgets.QLabel("")
        self._error_desc.setObjectName("emptyStateDescription")
        self._error_desc.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._error_desc.setWordWrap(True)
        error_layout.addWidget(self._error_desc)
        self._retry_btn = QtWidgets.QPushButton("Retry")
        self._retry_btn.setObjectName("accentButton")
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        btn_row.addWidget(self._retry_btn)
        error_layout.addLayout(btn_row)
        self._retry_callback: Callable[[], None] | None = None
        self._retry_btn.clicked.connect(self._on_retry)
        error_layout.addStretch(1)

        # Index 3 — content (caller supplies)
        self._content = QtWidgets.QWidget()
        self._content_layout = QtWidgets.QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)

        self.addWidget(self._loading)
        self.addWidget(self._empty)
        self.addWidget(self._error)
        self.addWidget(self._content)

    def set_loading(self, message: str = "") -> None:
        self._loading_label.setText(message or "Loading\u2026")
        self.setCurrentIndex(0)

    def set_empty(self, widget: QtWidgets.QWidget) -> None:
        while self._empty_layout.count():
            item = self._empty_layout.takeAt(0)
            w = item.widget()
            if w is not None and w is not widget:
                w.deleteLater()
        if self._empty_layout.indexOf(widget) < 0:
            self._empty_layout.addWidget(widget)
        self.setCurrentIndex(1)

    def set_error(self, message: str, retry: Callable[[], None] | None = None) -> None:
        self._error_desc.setText(message)
        self._retry_callback = retry
        self._retry_btn.setVisible(retry is not None)
        self.setCurrentIndex(2)

    def set_content(self, widget: QtWidgets.QWidget) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w is not None and w is not widget:
                w.deleteLater()
        if self._content_layout.indexOf(widget) < 0:
            self._content_layout.addWidget(widget)
        self.setCurrentIndex(3)

    def _on_retry(self) -> None:
        if self._retry_callback is not None:
            self._retry_callback()
