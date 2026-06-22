"""Local cover-art resolution and a reusable cover label.

Minerva deliberately keeps cover loading offline and deterministic.  The
provider searches a user-configurable root for common naming layouts and
returns a generic gamepad placeholder when no image is available.
"""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from minerva.domain.library import LibraryItem
from minerva.ui.icons import Icons

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def _safe_name(value: str) -> str:
    value = re.sub(r"[<>:\\|?*\"]", "_", value).strip(" .")
    return re.sub(r"\s+", " ", value)


class CoverProvider:
    """Resolve local cover images without network access."""

    def __init__(self, root: str | Path = "covers") -> None:
        self.root = Path(root)

    def candidates(self, item: LibraryItem) -> list[Path]:
        system = _safe_name(item.system or "Unknown")
        collection = _safe_name(item.collection or "Unknown")
        names = {
            str(item.id),
            _safe_name(item.stem),
            _safe_name(Path(item.basename).stem),
        }
        directories = (
            self.root / collection / system,
            self.root / system,
            self.root / collection,
            self.root,
        )
        return [directory / f"{name}{ext}" for directory in directories for name in names for ext in _IMAGE_EXTENSIONS]

    def resolve(self, item: LibraryItem) -> Path | None:
        return next((path for path in self.candidates(item) if path.is_file()), None)


class CoverLabel(QtWidgets.QLabel):
    """Aspect-ratio-preserving cover preview with a graceful fallback."""

    def __init__(self, width: int = 180, height: int = 240, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("coverPreview")
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(width, height)
        self.setScaledContents(False)
        self.set_placeholder()

    def set_placeholder(self) -> None:
        self.setPixmap(Icons.app().pixmap(64, 64))
        self.setToolTip("No local cover found")

    def set_cover(self, path: str | Path | None) -> None:
        if not path:
            self.set_placeholder()
            return
        pixmap = QtGui.QPixmap(str(path))
        if pixmap.isNull():
            self.set_placeholder()
            return
        self.setPixmap(
            pixmap.scaled(
                self.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.setToolTip(str(path))
