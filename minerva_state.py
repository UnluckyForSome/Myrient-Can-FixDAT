"""
Minerva Application-State Database — Persistent application state.
==================================================================

Persists fix-report summaries, review entries, the download queue, and
activity events in a dedicated SQLite database.  This replaces the legacy
JSON-based persistence (``saved_queue.json``) with a relational model
that supports cascading deletes, referential integrity, and proper
transactional safety.

Schema
------
Four tables: ``reports``, ``report_entries``, ``download_queue``,
``activity_events``.  Schema is auto-created on first use.

Thread-safety
-------------
Each thread should create its own ``MinervaState`` instance.  SQLite
serialises writes at the file level, so concurrent reads are safe.

Style
-----
Follows ``minerva_db.MinervaDB`` conventions: ``conn()`` context
manager, Python ``logging`` (no ``print``), ``pathlib.Path``,
``from __future__ import annotations``.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from minerva.domain.collections import ReferenceDat
from minerva.domain.downloads import QueueRecord
from minerva.domain.reports import ReportSummary, ResolutionState, ReviewEntry

log = logging.getLogger(__name__)

# ── Schema ────────────────────────────────────────────────────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    collection TEXT,
    system TEXT,
    imported_at TEXT NOT NULL,
    requested_count INTEGER NOT NULL,
    matched_count INTEGER NOT NULL DEFAULT 0,
    fuzzy_count INTEGER NOT NULL DEFAULT 0,
    unmatched_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft'
);

CREATE TABLE IF NOT EXISTS report_entries (
    id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    filename TEXT NOT NULL,
    size INTEGER NOT NULL,
    automatic_file_id INTEGER,
    automatic_method TEXT,
    automatic_confidence REAL,
    decision TEXT NOT NULL DEFAULT 'pending',
    selected_file_id INTEGER,
    FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_report_entries_report
    ON report_entries(report_id);


CREATE TABLE IF NOT EXISTS reference_dats (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    collection TEXT,
    system TEXT,
    entry_count INTEGER NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reference_dats_scope
    ON reference_dats(collection, system);

CREATE TABLE IF NOT EXISTS download_queue (
    id TEXT PRIMARY KEY,
    file_id INTEGER NOT NULL,
    report_entry_id TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    qbit_hash TEXT,
    destination TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_download_queue_status
    ON download_queue(status);

CREATE TABLE IF NOT EXISTS activity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_activity_events_created
    ON activity_events(created_at DESC);
"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    """Return a compact lowercase hex UUID suitable as a primary key."""
    return uuid.uuid4().hex


def _row_to_report(row: sqlite3.Row) -> ReportSummary:
    """Convert a ``reports`` row to a ``ReportSummary`` dataclass."""
    return ReportSummary(
        id=row["id"],
        path=row["path"],
        name=row["name"],
        collection=row["collection"],
        system=row["system"],
        imported_at=row["imported_at"],
        requested_count=row["requested_count"],
        matched_count=row["matched_count"],
        fuzzy_count=row["fuzzy_count"],
        unmatched_count=row["unmatched_count"],
        status=row["status"],
    )


def _row_to_entry(row: sqlite3.Row) -> ReviewEntry:
    """Convert a ``report_entries`` row to a ``ReviewEntry`` dataclass.

    ``resolution`` is inferred from ``decision`` since the database
    schema does not have a dedicated ``resolution`` column.
    """
    decision = row["decision"]
    if decision == "accept":
        resolution = ResolutionState.READY
    elif decision == "reject":
        resolution = ResolutionState.NOT_FOUND
    else:
        resolution = ResolutionState.REVIEW_REQUIRED
    return ReviewEntry(
        id=row["id"],
        report_id=row["report_id"],
        ordinal=row["ordinal"],
        filename=row["filename"],
        size=row["size"],
        automatic_file_id=row["automatic_file_id"],
        automatic_method=row["automatic_method"],
        automatic_confidence=row["automatic_confidence"],
        decision=decision,
        resolution=resolution,
        selected_file_id=row["selected_file_id"],
    )



def _row_to_reference_dat(row: sqlite3.Row) -> ReferenceDat:
    """Convert a ``reference_dats`` row to ``ReferenceDat``."""
    return ReferenceDat(
        id=row["id"],
        path=row["path"],
        name=row["name"],
        collection=row["collection"],
        system=row["system"],
        entry_count=row["entry_count"],
        imported_at=row["imported_at"],
    )

def _row_to_queue_record(row: sqlite3.Row) -> QueueRecord:
    """Convert a ``download_queue`` row to a ``QueueRecord`` dataclass."""
    return QueueRecord(
        id=row["id"],
        file_id=row["file_id"],
        report_entry_id=row["report_entry_id"],
        status=row["status"],
        qbit_hash=row["qbit_hash"],
        destination=row["destination"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── Main interface ─────────────────────────────────────────────────────────────

class MinervaState:
    """Persistent application-state database.

    Manages four state tables — reports, report entries, download queue,
    and activity events — with referential integrity and cascading deletes.

    Parameters
    ----------
    db_path:
        Filesystem path for the SQLite database.  Defaults to
        ``data/minerva_state.db`` under the current working directory.

    Raises
    ------
    sqlite3.OperationalError:
        If the database cannot be opened or the schema cannot be applied.
    """

    def __init__(self, db_path: str | Path = "data/minerva_state.db") -> None:
        self._path = str(db_path)
        self._apply_schema()
        log.debug("MinervaState initialised: %s", db_path)

    # ── Connection management (same pattern as MinervaDB) ─────────────────

    def conn(self) -> sqlite3.Connection:
        """Open and return a new database connection.

        The returned ``sqlite3.Connection`` can be used as a context
        manager::

            with state.conn() as c:
                c.execute("SELECT ...")

        On exit the context manager commits the transaction, or rolls
        back on exception.  The connection is **not** cached — each call
        creates a fresh connection (which is cheap with SQLite and
        avoids thread-safety issues).

        Enables ``WAL`` mode, ``FOREIGN_KEYS`` enforcement, and a
        4 MB page cache.
        """
        c = sqlite3.connect(self._path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode = WAL")
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("PRAGMA cache_size = -4000000")
        c.execute("PRAGMA temp_store = MEMORY")
        return c

    def _apply_schema(self) -> None:
        """Create tables and indexes if they do not already exist."""
        with self.conn() as c:
            c.executescript(SCHEMA_SQL)
        log.debug("Schema applied")

    # ── Reports ───────────────────────────────────────────────────────────

    def save_report(self, report: ReportSummary) -> None:
        """Insert a new ``ReportSummary`` into the database.

        Args:
            report: The report to persist.  Its ``id`` field must be
                unique; an existing report with the same id will cause
                an ``IntegrityError``.

        Raises:
            sqlite3.IntegrityError: If a report with the same ``id`` or
                ``path`` already exists.
        """
        with self.conn() as c:
            c.execute(
                """
                INSERT INTO reports
                    (id, path, name, collection, system, imported_at,
                     requested_count, matched_count, fuzzy_count,
                     unmatched_count, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.id,
                    report.path,
                    report.name,
                    report.collection,
                    report.system,
                    report.imported_at,
                    report.requested_count,
                    report.matched_count,
                    report.fuzzy_count,
                    report.unmatched_count,
                    report.status,
                ),
            )
        log.debug("Saved report %s (%s)", report.id, report.name)

    def update_report(self, report_id: str, **updates: Any) -> None:
        """Update fields of an existing report.

        Example::

            state.update_report("abc123", matched_count=42, status="reviewed")

        Only the supplied keyword arguments are changed.  The report
        must already exist (``report_id`` is validated via ``rowcount``
        and a warning is logged if no row is matched).

        Args:
            report_id: The ``id`` of the report to update.
            **updates: Column-value pairs to set.
        """
        if not updates:
            return
        columns = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [report_id]
        with self.conn() as c:
            cur = c.execute(
                f"UPDATE reports SET {columns} WHERE id = ?",
                params,
            )
            if cur.rowcount == 0:
                log.warning("update_report: no report found with id %s", report_id)
            else:
                log.debug("Updated report %s (%d field(s))", report_id, len(updates))

    def get_report(self, report_id: str) -> ReportSummary | None:
        """Fetch a single report by its id.

        Returns:
            The ``ReportSummary``, or ``None`` if no report matches.
        """
        with self.conn() as c:
            row = c.execute(
                "SELECT * FROM reports WHERE id = ?", (report_id,),
            ).fetchone()
        return _row_to_report(row) if row is not None else None

    def list_reports(self) -> list[ReportSummary]:
        """Return all reports, ordered by ``imported_at`` descending."""
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM reports ORDER BY imported_at DESC",
            ).fetchall()
        return [_row_to_report(r) for r in rows]

    def delete_report(self, report_id: str) -> None:
        """Delete a report and its cascaded entries.

        The ``ON DELETE CASCADE`` foreign key on ``report_entries``
        automatically removes all entries that belong to this report.

        Args:
            report_id: The ``id`` of the report to delete.
        """
        with self.conn() as c:
            cur = c.execute("DELETE FROM reports WHERE id = ?", (report_id,))
            if cur.rowcount == 0:
                log.warning("delete_report: no report found with id %s", report_id)
            else:
                log.debug("Deleted report %s", report_id)

    # ── Report entries ────────────────────────────────────────────────────

    def save_entries(self, entries: list[ReviewEntry]) -> None:
        """Insert a batch of ``ReviewEntry`` records.

        All entries are inserted in a single transaction for performance.
        If any entry has a duplicate ``id`` the entire batch is rolled
        back and an ``IntegrityError`` is raised.

        Args:
            entries: The review entries to persist.

        Raises:
            sqlite3.IntegrityError: If any entry id already exists.
        """
        with self.conn() as c:
            c.executemany(
                """
                INSERT INTO report_entries
                    (id, report_id, ordinal, filename, size,
                     automatic_file_id, automatic_method,
                     automatic_confidence, decision, selected_file_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        e.id,
                        e.report_id,
                        e.ordinal,
                        e.filename,
                        e.size,
                        e.automatic_file_id,
                        e.automatic_method,
                        e.automatic_confidence,
                        e.decision,
                        e.selected_file_id,
                    )
                    for e in entries
                ],
            )
        log.debug("Saved %d entry/ies for report %s", len(entries), entries[0].report_id if entries else "(none)")

    def get_entries(self, report_id: str) -> list[ReviewEntry]:
        """Return all entries for a given report, ordered by ordinal.

        Args:
            report_id: The report whose entries to fetch.

        Returns:
            List of ``ReviewEntry`` objects (empty if the report has
            no entries or does not exist).
        """
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM report_entries WHERE report_id = ? ORDER BY ordinal",
                (report_id,),
            ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def update_entry_decision(
        self,
        entry_id: str,
        decision: str,
        selected_file_id: int | None = None,
    ) -> None:
        """Update the user's decision for a single review entry.

        This is the primary mutator on ``report_entries`` — called when
        the user accepts, rejects, or changes their selection during
        review.

        Args:
            entry_id: The ``id`` of the review entry.
            decision: New decision value (``"pending"``, ``"accept"``,
                ``"reject"``, or ``"fuzzy"``).
            selected_file_id: Optional ``files.id`` override.  Pass
                ``None`` to leave the existing selection unchanged.
        """
        with self.conn() as c:
            if selected_file_id is not None:
                cur = c.execute(
                    "UPDATE report_entries SET decision = ?, selected_file_id = ? WHERE id = ?",
                    (decision, selected_file_id, entry_id),
                )
            else:
                cur = c.execute(
                    "UPDATE report_entries SET decision = ? WHERE id = ?",
                    (decision, entry_id),
                )
            if cur.rowcount == 0:
                log.warning("update_entry_decision: no entry found with id %s", entry_id)
            else:
                log.debug("Updated entry %s → decision=%s", entry_id, decision)

    def get_report_by_path(self, path: str | Path) -> ReportSummary | None:
        """Return the report imported from *path*, if any."""
        with self.conn() as c:
            row = c.execute(
                "SELECT * FROM reports WHERE path = ?",
                (str(Path(path)),),
            ).fetchone()
        return _row_to_report(row) if row is not None else None

    def replace_entries(self, report_id: str, entries: list[ReviewEntry]) -> None:
        """Atomically replace every review entry belonging to *report_id*."""
        with self.conn() as c:
            c.execute(
                "DELETE FROM report_entries WHERE report_id = ?",
                (report_id,),
            )
            c.executemany(
                """
                INSERT INTO report_entries
                    (id, report_id, ordinal, filename, size,
                     automatic_file_id, automatic_method,
                     automatic_confidence, decision, selected_file_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        entry.id,
                        entry.report_id,
                        entry.ordinal,
                        entry.filename,
                        entry.size,
                        entry.automatic_file_id,
                        entry.automatic_method,
                        entry.automatic_confidence,
                        entry.decision,
                        entry.selected_file_id,
                    )
                    for entry in entries
                ],
            )

    def update_entry_decisions(
        self,
        updates: list[tuple[str, str, int | None]],
    ) -> None:
        """Apply decision updates in one transaction."""
        with self.conn() as c:
            c.executemany(
                "UPDATE report_entries "
                "SET decision = ?, selected_file_id = ? WHERE id = ?",
                [(decision, file_id, entry_id) for entry_id, decision, file_id in updates],
            )

    # ── Reference DATs ───────────────────────────────────────────────────

    def save_reference_dat(self, reference: ReferenceDat) -> None:
        """Insert or replace an expected-count reference DAT."""
        with self.conn() as c:
            c.execute(
                """
                INSERT INTO reference_dats
                    (id, path, name, collection, system, entry_count, imported_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name = excluded.name,
                    collection = excluded.collection,
                    system = excluded.system,
                    entry_count = excluded.entry_count,
                    imported_at = excluded.imported_at
                """,
                (
                    reference.id,
                    reference.path,
                    reference.name,
                    reference.collection,
                    reference.system,
                    reference.entry_count,
                    reference.imported_at,
                ),
            )

    def list_reference_dats(self) -> list[ReferenceDat]:
        """Return imported reference DATs, newest first."""
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM reference_dats ORDER BY imported_at DESC"
            ).fetchall()
        return [_row_to_reference_dat(row) for row in rows]

    def delete_reference_dat(self, reference_id: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM reference_dats WHERE id = ?", (reference_id,))

    def expected_counts(self) -> dict[tuple[str, str], int]:
        """Return expected file counts keyed by collection/system."""
        with self.conn() as c:
            rows = c.execute(
                """
                SELECT COALESCE(collection, '') AS collection,
                       COALESCE(system, '') AS system,
                       MAX(entry_count) AS entry_count
                FROM reference_dats
                GROUP BY collection, system
                """
            ).fetchall()
        return {
            (row["collection"], row["system"]): row["entry_count"]
            for row in rows
        }

    # ── Download queue ────────────────────────────────────────────────────

    def save_queue_record(self, record: QueueRecord) -> None:
        """Insert a new queue record.

        Args:
            record: The queue record to persist.  Its ``id`` must be
                unique.

        Raises:
            sqlite3.IntegrityError: If a record with the same ``id``
                already exists.
        """
        with self.conn() as c:
            c.execute(
                """
                INSERT INTO download_queue
                    (id, file_id, report_entry_id, status, qbit_hash,
                     destination, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.file_id,
                    record.report_entry_id,
                    record.status,
                    record.qbit_hash,
                    record.destination,
                    record.error,
                    record.created_at,
                    record.updated_at,
                ),
            )
        log.debug("Saved queue record %s (file_id=%d)", record.id, record.file_id)

    def update_queue_record(self, record_id: str, **updates: Any) -> None:
        """Update fields of an existing queue record.

        If ``status`` is among the updates, ``updated_at`` is
        automatically set to the current time.

        Example::

            state.update_queue_record("q789", status="downloading")

        Args:
            record_id: The ``id`` of the queue record.
            **updates: Column-value pairs to set.
        """
        if not updates:
            return

        # Auto-set updated_at when status changes
        if "status" in updates:
            updates = {**updates, "updated_at": _now_iso()}
        elif "updated_at" not in updates:
            updates = {**updates, "updated_at": _now_iso()}

        columns = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [record_id]
        with self.conn() as c:
            cur = c.execute(
                f"UPDATE download_queue SET {columns} WHERE id = ?",
                params,
            )
            if cur.rowcount == 0:
                log.warning(
                    "update_queue_record: no record found with id %s", record_id,
                )
            else:
                log.debug("Updated queue record %s (%d field(s))", record_id, len(updates))

    def list_queue(self) -> list[QueueRecord]:
        """Return all queue records, ordered by ``created_at`` descending.

        Returns:
            List of ``QueueRecord`` objects (empty if the queue is empty).
        """
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM download_queue ORDER BY created_at DESC",
            ).fetchall()
        return [_row_to_queue_record(r) for r in rows]

    def get_queue_record(self, record_id: str) -> QueueRecord | None:
        with self.conn() as c:
            row = c.execute(
                "SELECT * FROM download_queue WHERE id = ?",
                (record_id,),
            ).fetchone()
        return _row_to_queue_record(row) if row is not None else None

    def find_queue_for_file(self, file_id: int) -> list[QueueRecord]:
        """Return queue records for a library file, newest first."""
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM download_queue WHERE file_id = ? "
                "ORDER BY created_at DESC",
                (file_id,),
            ).fetchall()
        return [_row_to_queue_record(row) for row in rows]

    def delete_queue_record(self, record_id: str) -> None:
        """Remove a single record from the download queue.

        Args:
            record_id: The ``id`` of the queue record to delete.
        """
        with self.conn() as c:
            cur = c.execute(
                "DELETE FROM download_queue WHERE id = ?", (record_id,),
            )
            if cur.rowcount == 0:
                log.warning(
                    "delete_queue_record: no record found with id %s", record_id,
                )
            else:
                log.debug("Deleted queue record %s", record_id)

    # ── Activity events ───────────────────────────────────────────────────

    def add_event(self, category: str, message: str) -> None:
        """Append an activity event.

        Events are auto-incremented and timestamped — ``id`` and
        ``created_at`` are set internally.

        Args:
            category: Event category (e.g. ``"download"``, ``"match"``,
                ``"review"``, ``"error"``).
            message: Human-readable description of the event.
        """
        with self.conn() as c:
            c.execute(
                "INSERT INTO activity_events (category, message, created_at) VALUES (?, ?, ?)",
                (category, message, _now_iso()),
            )
        log.debug("Event [%s]: %s", category, message)

    def get_events(self, limit: int = 200) -> list[dict]:
        """Return the most recent activity events.

        Results are ordered by ``created_at`` descending (most recent
        first).

        Args:
            limit: Maximum number of events to return (default 200).

        Returns:
            List of dicts with keys ``id``, ``category``, ``message``,
            ``created_at``.
        """
        with self.conn() as c:
            rows = c.execute(
                "SELECT id, category, message, created_at "
                "FROM activity_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "category": r["category"],
                "message": r["message"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
