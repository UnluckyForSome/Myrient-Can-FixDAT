"""
Path picker — text field with browse button.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6 import QtCore, QtWidgets

from minerva.ui.theme import ThemeTokens
from minerva.ui.density import Density


class PathPicker(QtWidgets.QWidget):
    """A labelled path input with a browse button.

    Signals:
        path_changed(str): emitted when the user picks a new path.
    """

    path_changed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        label: str = "",
        default: str = "",
        tokens: ThemeTokens = ThemeTokens(),
        density: Density = Density.COMPACT,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._density = density

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if label:
            lbl = QtWidgets.QLabel(label)
            lbl.setObjectName("mutedLabel")
            layout.addWidget(lbl)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)

        self.path_edit = QtWidgets.QLineEdit(default)
        self.path_edit.setPlaceholderText("Select a folder…")
        row.addWidget(self.path_edit, 1)

        self.browse_btn = QtWidgets.QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._browse)
        row.addWidget(self.browse_btn)

        layout.addLayout(row)

    def _browse(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose folder", self.path_edit.text()
        )
        if folder:
            self.path_edit.setText(folder)
            self.path_changed.emit(folder)

    def path(self) -> str:
        return self.path_edit.text()

    def set_path(self, path: str) -> None:
        self.path_edit.setText(path)


