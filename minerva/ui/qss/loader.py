"""QSS loading with a defined cascade order.

Order (concatenated in this sequence):

    base → layout → controls → tables → navigation → cards →
    panels → inspectors → actions → states → {library | downloads | collections}

Page-specific QSS must override a class name introduced in the shared
layers, not invent new selectors.
"""

from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent

_SHARED_ORDER = [
    "base.qss",
    "layout.qss",
    "controls.qss",
    "tables.qss",
    "navigation.qss",
    "cards.qss",
    "panels.qss",
    "inspectors.qss",
    "actions.qss",
    "states.qss",
]

_PAGE_FILES: dict[str, str] = {
    "library": "library.qss",
    "downloads": "downloads.qss",
    "collections": "collections.qss",
}


def load_qss(page_name: str | None = None) -> str:
    """Load and concatenate QSS files in the canonical cascade order.

    Args:
        page_name: Optional page key (``"library"``, ``"downloads"``,
            ``"collections"``) to append page-specific overrides.
    """
    files: list[str] = list(_SHARED_ORDER)
    if page_name and page_name in _PAGE_FILES:
        files.append(_PAGE_FILES[page_name])

    parts: list[str] = []
    for name in files:
        path = _HERE / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def all_qss_files() -> list[str]:
    """Return the full ordered list of QSS filenames (for diagnostics)."""
    result: list[str] = list(_SHARED_ORDER)
    result.extend(_PAGE_FILES.values())
    return result
