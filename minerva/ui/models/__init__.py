"""
Re-exports for the model/view primitives package.

Public API
----------
*   ``ColumnSpec`` — immutable column descriptor.
*   ``RecordListModel`` — generic ``QAbstractTableModel`` with column specs.
*   ``DownloadTableModel`` — typed ``RecordListModel`` for ``DownloadRecord``.
*   ``DisplayDelegate`` — ``QStyledItemDelegate`` with ``str()`` fallback.
*   ``SizeDelegate`` — ``QStyledItemDelegate`` for binary byte sizes.
*   ``CheckboxDelegate`` — ``QStyledItemDelegate`` with click-to-toggle.
*   ``TagPillDelegate`` — delegate for rendering tag pills.
"""

from __future__ import annotations

from minerva.ui.models.delegates import (
    CheckboxDelegate,
    DisplayDelegate,
    SizeDelegate,
    TagPillDelegate,
)
from minerva.ui.models.download_model import (
    DownloadRecord,
    DownloadStatus,
    DownloadTableModel,
)
from minerva.ui.models.record_model import (
    ColumnSpec,
    RecordListModel,
)

__all__ = [
    "CheckboxDelegate",
    "ColumnSpec",
    "DisplayDelegate",
    "DownloadRecord",
    "DownloadStatus",
    "DownloadTableModel",
    "RecordListModel",
    "SizeDelegate",
    "TagPillDelegate",
]
