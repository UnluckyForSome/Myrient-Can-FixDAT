from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PyQt6 import QtCore

from minerva.domain.reports import ReportOutcome, ReportSummary, ReviewEntry
from minerva.services.report_acquisition import ReportAcquisitionService
from minerva_state import MinervaState

log = logging.getLogger(__name__)


class ReportStore(QtCore.QObject):
    """Observable store for reports and their review entries.

    Every mutation that touches ``reports`` or ``report_entries`` goes
    through this store so listeners can react to granular signals instead
    of polling the database.
    """

    report_updated = QtCore.pyqtSignal(str)
    report_deleted = QtCore.pyqtSignal(str)
    entries_updated = QtCore.pyqtSignal(str)
    outcomes_updated = QtCore.pyqtSignal()

    def __init__(self, parent: QtCore.QObject | None = None, state: MinervaState | None = None) -> None:
        super().__init__(parent)
        self._state = state or MinervaState()

    def list_reports(self) -> list[ReportSummary]:
        return self._state.list_reports()

    def get_report(self, report_id: str) -> ReportSummary | None:
        return self._state.get_report(report_id)

    def get_entries(self, report_id: str) -> list[ReviewEntry]:
        return self._state.get_entries(report_id)

    def get_report_by_path(self, path: str | Path) -> ReportSummary | None:
        return self._state.get_report_by_path(path)

    def compute_outcome(self, report_id: str) -> ReportOutcome:
        return ReportAcquisitionService().compute_outcome(report_id)

    def save_report(self, report: ReportSummary) -> None:
        self._state.save_report(report)
        self.report_updated.emit(report.id)

    def update_report(self, report_id: str, **updates: Any) -> None:
        self._state.update_report(report_id, **updates)
        self.report_updated.emit(report_id)

    def delete_report(self, report_id: str) -> None:
        self._state.delete_report(report_id)
        self.report_deleted.emit(report_id)

    def replace_entries(self, report_id: str, entries: list[ReviewEntry]) -> None:
        self._state.replace_entries(report_id, entries)
        self.entries_updated.emit(report_id)

    def update_entry_decision(
        self,
        report_id: str,
        entry_id: str,
        decision: str,
        selected_file_id: int | None = None,
    ) -> None:
        self._state.update_entry_decision(entry_id, decision, selected_file_id)
        self.entries_updated.emit(report_id)

    def update_entry_decisions(self, report_id: str, updates: list) -> None:
        if not updates:
            return
        self._state.update_entry_decisions(updates)
        self.entries_updated.emit(report_id)

    def add_event(self, kind: str, message: str) -> None:
        self._state.add_event(kind, message)
