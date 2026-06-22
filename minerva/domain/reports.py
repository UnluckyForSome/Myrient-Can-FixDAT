"""
Domain types for fix-reports and their review entries.

Supersedes ``minerva.app.legacy_data.QueueItem`` with a richer schema
that includes collection/system metadata, fuzzy-matching statistics, and
a per-entry review workflow.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path


class ResolutionState(enum.Enum):
    READY = "ready"                     # safe exact / strong unique match — auto-accept
    REVIEW_REQUIRED = "review_required" # multiple plausible candidates
    NOT_FOUND = "not_found"             # no indexed source contains it
    IGNORED = "ignored"                 # user explicitly excluded


@dataclass(frozen=True)
class MatchPolicy:
    auto_accept_exact: bool = True
    fuzzy_min_confidence: float = 0.96
    fuzzy_min_margin: float = 0.08
    require_same_system: bool = True
    require_same_collection: bool = True


@dataclass(frozen=True)
class AcquisitionSummary:
    ready: int = 0
    review_required: int = 0
    not_found: int = 0
    ignored: int = 0

    @property
    def obtainable(self) -> int:
        return self.ready


@dataclass(frozen=True)
class QueueResult:
    added: int            # records added to the download queue
    skipped_active: int   # already in active/queued state
    skipped_complete: int # already completed
    skipped_missing: int  # not_found entries skipped


@dataclass(frozen=True)
class ReportScope:
    collection: str | None
    system: str | None


class ScopeInferenceRequired(Exception):
    """Raised when scope cannot be inferred from the report file.

    Carries candidate (collection, system) pairs so the UI can prompt.
    """

    def __init__(self, candidates: list[tuple[str, str, int]]) -> None:
        self.candidates = candidates
        super().__init__(f"Could not infer report scope from {len(candidates)} candidates")


class ReportOutcome(str, enum.Enum):
    """Outcome of the triage eligibility check for a report."""

    ACTIONABLE = "actionable"                # ≥1 eligible READY entry
    NEEDS_REVIEW = "needs_review"            # entries exist but ambiguous
    NO_SOURCE_MATCHES = "no_source_matches"  # zero candidates
    FILTERED_OUT = "filtered_out"            # candidates exist, none fit policy
    ALREADY_SATISFIED = "already_satisfied"  # all matched entries already downloaded
    EMPTY = "empty"                          # zero missing entries / parse failed
    ERROR = "error"


@dataclass
class ReportSummary:
    """Summary of a single fix-report imported into the application.

    Each ``ReportSummary`` corresponds to one DAT file (or RomVault CSV)
    that was matched against the Minerva torrent index.  The report
    lifecycle is tracked via the *status* field.

    ``ready_count`` + ``review_required_count`` + ``not_found_count`` always
    equals *requested_count*.

    Attributes
    ----------
    id:
        UUID or slug unique to this report.
    path:
        Filesystem path of the imported DAT/CSV file.
    name:
        Display name (typically ``DatInfo.name`` or the file stem).
    collection:
        Inferred collection (e.g. ``"No-Intro"``, ``"Redump"``).
    system:
        Inferred system (e.g. ``"Nintendo - Game Boy Color"``).
    imported_at:
        ISO-8601 timestamp of when the report was first imported.
    requested_count:
        Total number of rom entries in the source DAT.
    ready_count:
        Number of entries classified as READY (auto-accept).
    review_required_count:
        Number of entries that need human review.
    not_found_count:
        Number of entries with zero matches.
    status:
        Lifecycle status: ``"draft"`` → ``"reviewed"`` → ``"archived"``.
    safe_match_count:
        Number of entries with a safe (exact/confident) match.
    ambiguous_match_count:
        Number of entries with an ambiguous match.
    eligible_count:
        Number of entries eligible for download after applying policy.
    eligible_bytes:
        Total bytes of eligible entries.
    already_present_count:
        Number of entries already present on disk.
    already_queued_count:
        Number of entries already in the download queue.
    excluded_by_size_count:
        Number of entries excluded by size limits.
    outcome:
        Triage outcome (one of :class:`ReportOutcome` values).
    """

    id: str
    path: str
    name: str
    collection: str | None = None
    system: str | None = None
    imported_at: str = ""
    requested_count: int = 0
    # New primary fields (replacing matched/fuzzy/unmatched)
    ready_count: int = 0
    review_required_count: int = 0
    not_found_count: int = 0
    status: str = "draft"
    # Legacy aliases — kept for database backward compat
    matched_count: int = 0
    fuzzy_count: int = 0
    unmatched_count: int = 0
    # Triage fields (computed, not persisted)
    safe_match_count: int = 0
    ambiguous_match_count: int = 0
    eligible_count: int = 0
    eligible_bytes: int = 0
    already_present_count: int = 0
    already_queued_count: int = 0
    excluded_by_size_count: int = 0
    outcome: str = ""

    def __post_init__(self) -> None:
        """Synchronise legacy alias fields with new primary fields.

        When loading from the database the old column names are populated
        while the new fields are at their default (0).  We copy old → new,
        then mirror back so both sets stay in sync.
        """
        # Old → new: database rows set matched_count, fuzzy_count, unmatched_count
        if self.ready_count == 0 and self.matched_count > 0:
            self.ready_count = self.matched_count
        if self.review_required_count == 0 and self.fuzzy_count > 0:
            self.review_required_count = self.fuzzy_count
        if self.not_found_count == 0 and self.unmatched_count > 0:
            self.not_found_count = self.unmatched_count
        # New → old: keep legacy fields in sync
        self.matched_count = self.ready_count
        self.fuzzy_count = self.review_required_count
        self.unmatched_count = self.not_found_count


# ── Acquisition planner types ─────────────────────────────────────────────

class SelectionStrategy(str, enum.Enum):
    SMALLEST_FIRST = "smallest_first"
    LARGEST_FIRST = "largest_first"
    REPORT_ORDER = "report_order"
    CONFIDENCE_FIRST = "confidence_first"
    AVAILABILITY_FIRST = "availability_first"


@dataclass(frozen=True, slots=True)
class AcquisitionConstraints:
    max_file_bytes: int | None = None
    max_total_bytes: int | None = None
    max_file_count: int | None = None
    reserve_free_bytes: int = 50 * 1024 ** 3
    strategy: SelectionStrategy = SelectionStrategy.SMALLEST_FIRST

    collections: frozenset[str] = frozenset()
    systems: frozenset[str] = frozenset()
    regions: frozenset[str] = frozenset()
    extensions: frozenset[str] = frozenset()

    include_automatic_matches: bool = True
    include_reviewed_matches: bool = True
    require_seeded_source: bool = False


@dataclass(frozen=True, slots=True)
class PlannedFile:
    report_entry_id: str
    file_id: int
    size: int
    torrent_name: str
    destination: Path


@dataclass(frozen=True, slots=True)
class DeferredFile:
    report_entry_id: str
    file_id: int
    size: int
    reason: str


@dataclass(frozen=True, slots=True)
class VolumeEstimate:
    path: Path
    available_bytes: int
    committed_bytes: int
    newly_required_bytes: int
    reserve_bytes: int
    fits: bool


@dataclass(frozen=True, slots=True)
class AcquisitionPlan:
    selected: tuple[PlannedFile, ...]
    deferred: tuple[DeferredFile, ...]
    volumes: tuple[VolumeEstimate, ...]
    selected_bytes: int
    estimated_transfer_bytes: int
    report_id: str
    report_name: str = ""


@dataclass
class ReviewEntry:
    """A single rom entry from a fix-report, with its match decision.

    Each ``ReviewEntry`` corresponds to one ``DatEntry`` from the
    original DAT file.  The user reviews these entries and decides
    which file from the index (if any) to select for download —
    either accepting the automatic suggestion or picking manually.

    Attributes
    ----------
    id:
        UUID or slug unique to this review entry.
    report_id:
        Foreign key — the ``ReportSummary.id`` this entry belongs to.
    ordinal:
        Zero-based position within the report's entry list.
    filename:
        Original rom filename from the DAT entry.
    size:
        Expected file size in bytes.
    automatic_file_id:
        The ``files.id`` of the best automatic match, or ``None``.
    automatic_method:
        Which tier produced the match: ``"exact"``, ``"fts5"``,
        ``"trigram"``, ``"keyword"``, or ``None``.
    automatic_confidence:
        Match confidence score (0.0 – 1.0), or ``None``.
    resolution:
        Classification from the margin-based classifier.
    decision:
        User's decision: ``"pending"``, ``"accept"``, ``"reject"``,
        ``"fuzzy"``.
    selected_file_id:
        The ``files.id`` the user selected (when different from the
        automatic suggestion or after manual override).
    """

    id: str
    report_id: str
    ordinal: int
    filename: str
    size: int
    automatic_file_id: int | None = None
    automatic_method: str | None = None
    automatic_confidence: float | None = None
    resolution: ResolutionState = ResolutionState.REVIEW_REQUIRED
    decision: str = "pending"
    selected_file_id: int | None = None
