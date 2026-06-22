"""
``ColumnSpec``, ``RecordListModel[T]``, and ``QueueItemRecordModel``.

*   ``ColumnSpec`` — frozen dataclass describing a single table column
    (header text, accessor callable, optional format function, sort and
    tooltip roles, checkbox flag).  Immutable and hashable per Decision 1.
*   ``RecordListModel[T]`` — ``QAbstractTableModel`` subclass driven by a
    list of ``ColumnSpec`` values.  Stores an internal snapshot of the
    record list (Decision 3).  Mutators emit proper
    ``begin/end{Reset,InsertRows,RemoveRows}`` and ``dataChanged`` signals.
*   ``QueueItemRecordModel`` — type alias for ``RecordListModel[QueueItem]``
    pre-configured with the 6 columns needed by ``ReportsPage``.
"""

from __future__ import annotations

import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from PyQt6 import QtCore
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt



if typing.TYPE_CHECKING:
    from collections.abc import Sequence

T = TypeVar("T")


# ── ColumnSpec ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ColumnSpec(Generic[T]):
    """Immutable descriptor for a single table column.

    Parameters
    ----------
    header
        Column header text (shown in the horizontal header).
    accessor
        Callable that extracts the cell value from a record *T*.
    format_fn
        Optional callable that formats the raw value for display.
        ``None`` means the raw value is returned as-is for the
        ``DisplayRole``; the view's delegate (e.g. ``SizeDelegate``)
        is responsible for final formatting.
    sort_role
        Item data role used by ``SortFilterProxy.lessThan``
        (default ``UserRole`` — raw value for locale-free sorting).
    tooltip_role
        Item data role used for tooltip text
        (default ``ToolTipRole``).
    is_checkbox
        If ``True`` the column is rendered as a checkable indicator.
    """

    header: str
    accessor: Callable[[T], Any]
    format_fn: Callable[[Any], str] | None = None
    sort_role: int = Qt.ItemDataRole.UserRole
    tooltip_role: int = Qt.ItemDataRole.ToolTipRole
    is_checkbox: bool = False


# ── RecordListModel[T] ────────────────────────────────────────────────────────


class RecordListModel(QAbstractTableModel, Generic[T]):
    """Generic table model backed by a ``list[T]`` and a ``list[ColumnSpec]``.

    Takes a **snapshot copy** of the record list at construction and on
    every ``set_records()`` call (Decision 3).  Mutating the original list
    after passing it to the model has no effect until ``set_records()`` or
    ``update_record()`` is called explicitly.

    Signals
    -------
    ``modelReset`` — ``set_records()``
    ``rowsInserted`` — ``append_record()``
    ``rowsRemoved`` — ``remove_record()``
    ``dataChanged`` — ``update_record()`` and ``setData()`` (checkbox toggle)
    """

    def __init__(
        self,
        records: list[T],
        columns: list[ColumnSpec[T]],
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._columns: list[ColumnSpec[T]] = columns
        self._records: list[T] = list(records)  # snapshot copy
        self._check_states: dict[int, Qt.CheckState] = {}

    @property
    def column_specs(self) -> list[ColumnSpec[T]]:
        """Expose column specs so ``SortFilterProxy`` can read ``sort_role``."""
        return self._columns

    # ── QAbstractItemModel interface ──────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the number of records."""
        if parent.isValid():
            return 0
        return len(self._records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the number of column specs."""
        if parent.isValid():
            return 0
        return len(self._columns)

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Return data for *index* according to *role*.

        Role dispatch
        -------------
        *   ``DisplayRole`` — formatted via ``format_fn`` if present, else
            raw accessor value.
        *   ``UserRole`` — raw accessor value (for sorting).
        *   ``ToolTipRole`` — ``str()`` of the accessor value.
        *   ``CheckStateRole`` — current check state for checkbox columns.
        """
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._records):
            return None
        if col < 0 or col >= len(self._columns):
            return None

        spec = self._columns[col]
        raw = spec.accessor(self._records[row])

        if role == Qt.ItemDataRole.DisplayRole:
            if spec.format_fn is not None:
                return spec.format_fn(raw)
            return raw

        if role == Qt.ItemDataRole.UserRole:
            return raw

        if role == Qt.ItemDataRole.ToolTipRole:
            return str(raw) if raw is not None else ""

        if role == Qt.ItemDataRole.CheckStateRole:
            if spec.is_checkbox:
                return self._check_states.get(row, Qt.CheckState.Unchecked)
            return None

        return None

    def setData(
        self,
        index: QModelIndex,
        value: Any,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        """Set data (currently only ``CheckStateRole`` for checkbox columns).

        Returns ``True`` if the data was accepted.
        """
        if not index.isValid():
            return False
        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._records):
            return False
        if col < 0 or col >= len(self._columns):
            return False

        if role == Qt.ItemDataRole.CheckStateRole:
            spec = self._columns[col]
            if spec.is_checkbox:
                self._check_states[row] = Qt.CheckState(value)
                self.dataChanged.emit(index, index, [role])
                return True
        return False

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> str | None:
        """Return the column header text for ``DisplayRole``."""
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < len(self._columns)
        ):
            return self._columns[section].header
        return super().headerData(section, orientation, role)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """Return item flags; checkbox columns get ``ItemIsUserCheckable``."""
        flags = super().flags(index)
        if index.isValid():
            col = index.column()
            if 0 <= col < len(self._columns) and self._columns[col].is_checkbox:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    # ── Public mutators ───────────────────────────────────────────────────

    def set_records(self, records: list[T]) -> None:
        """Replace all records (``beginResetModel`` / ``endResetModel``)."""
        self.beginResetModel()
        self._records = list(records)
        self._check_states.clear()
        self.endResetModel()

    def append_record(self, record: T) -> None:
        """Append one record (``beginInsertRows`` / ``endInsertRows``)."""
        row = len(self._records)
        self.beginInsertRows(QModelIndex(), row, row)
        self._records.append(record)
        self.endInsertRows()

    def remove_record(self, row: int) -> None:
        """Remove the record at *row* (``beginRemoveRows`` / ``endRemoveRows``).

        Shifts check states down for rows after the removed one.
        """
        if row < 0 or row >= len(self._records):
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._records[row]
        # Clean up check state for the removed row
        self._check_states.pop(row, None)
        # Shift check states for rows after the removed one
        shifted: dict[int, Qt.CheckState] = {}
        for r, state in self._check_states.items():
            if r >= row:
                shifted[r - 1] = state
            else:
                shifted[r] = state
        self._check_states = shifted
        self.endRemoveRows()

    def update_record(self, row: int, record: T) -> None:
        """Replace the record at *row* and emit ``dataChanged``.

        The signal covers all columns of the updated row.
        """
        if row < 0 or row >= len(self._records):
            return
        self._records[row] = record
        last_col = len(self._columns) - 1
        top_left = self.index(row, 0)
        bottom_right = self.index(row, last_col)
        self.dataChanged.emit(top_left, bottom_right)

    @property
    def records(self) -> list[T]:
        """Return a copy of the current record list."""
        return list(self._records)


# ── QueueItem convenience alias ────────────────────────────────────────────

from minerva.app.legacy_data import QueueItem

_QUEUE_COLUMNS: list[ColumnSpec[QueueItem]] = [
    ColumnSpec(header="Name", accessor=lambda r: r.name),
    ColumnSpec(header="Entries", accessor=lambda r: r.entries_count, format_fn=lambda v: f"{v:,}"),
    ColumnSpec(header="Matched", accessor=lambda r: r.matched_count, format_fn=lambda v: f"{v:,}"),
    ColumnSpec(header="Unmatched", accessor=lambda r: r.unmatched_count, format_fn=lambda v: f"{v:,}"),
    ColumnSpec(header="Size", accessor=lambda r: r.matched_size),
    ColumnSpec(header="✓", accessor=lambda r: r.matched_count > 0, is_checkbox=True),
]

QueueItemRecordModel = RecordListModel[QueueItem]

