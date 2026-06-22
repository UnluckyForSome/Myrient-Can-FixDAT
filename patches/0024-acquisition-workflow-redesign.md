# Patch 0024 — Acquisition workflow redesign (single PR)

**Status:** ready to extend
**Risk:** high (touches matching, planning, queueing, two pages, two new services)
**LOC budget:** ≤ 3500 changed lines (acceptable: this is a workflow redesign, not a polish pass)
**Base commit:** `8c6669b` (the latest fix commit)
**Successor:** visual polish on the new Reports / Match Review / planner UI

This is a **workflow redesign**, not a polish pass. The user explicitly collapsed the originally-planned 3-PR sequence into a single atomic change and then expanded it further with a planner + triage inbox. The previous (interrupted) delegation has already laid the foundation: new `ReportAcquisitionService`, `ResolutionState`, `MatchPolicy`, `AcquisitionSummary`, `QueueResult`, scope inference, margin-based classifier, `replace_entries()`, Reports page redesign skeleton, Match Review reduced to exceptions.

This brief extends that work to add:
- The acquisition planner with disk capacity, file size budgets, reserve, max files
- Storage accounting across seed and output filesystems
- Report triage at the DAT level (actionable inbox, not historical list)
- AcquisitionConstraints / AcquisitionPlan / PlannedFile / DeferredFile / VolumeEstimate
- Selection strategies (smallest first default)
- Filterable / presetable limits panel

---

# Part A — Foundation (already drafted by the previous delegation)

## A.1 New domain types in `minerva/domain/reports.py`

```python
class ResolutionState(enum.Enum):
    READY = "ready"            # safe exact / strong unique match — auto-accept
    REVIEW_REQUIRED = "review_required"  # multiple plausible candidates
    NOT_FOUND = "not_found"    # no indexed source contains it
    IGNORED = "ignored"        # user explicitly excluded

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
    added: int
    skipped_active: int
    skipped_complete: int
    skipped_missing: int

@dataclass(frozen=True)
class ReportScope:
    collection: str | None
    system: str | None

class ScopeInferenceRequired(Exception):
    def __init__(self, candidates: list[tuple[str, str, int]]) -> None:
        self.candidates = candidates
```

`ReportSummary` adds (computed in Python from existing columns, no schema change):
- `safe_match_count: int = 0`
- `ambiguous_match_count: int = 0`
- `eligible_count: int = 0`
- `eligible_bytes: int = 0`
- `already_present_count: int = 0`
- `already_queued_count: int = 0`
- `excluded_by_size_count: int = 0`
- `outcome: str = "unknown"` — one of `ACTIONABLE`, `NEEDS_REVIEW`, `NO_SOURCE_MATCHES`, `FILTERED_OUT`, `ALREADY_SATISFIED`, `EMPTY`, `ERROR`

`ReviewEntry` adds `resolution: ResolutionState = ResolutionState.REVIEW_REQUIRED`. The `decision` field stays for backward compat.

## A.2 `ReportAcquisitionService` (in `minerva/services/report_acquisition.py`)

- `import_report(path, scope=None) -> ReportSummary` — parse, infer scope, persist.
- `match_report(report_id, policy=None) -> AcquisitionSummary` — reclassify, persist via `replace_entries`.
- `queue_ready(report_id, include_reviewed=True) -> QueueResult` — build queue excluding active/completed and `NOT_FOUND`.
- `rematch_report(report_id) -> AcquisitionSummary` — same as `match_report` with bumped generation.

Scope inference: CSV columns, path/filename regex, candidate distribution. Raise `ScopeInferenceRequired` if all fail.

Margin-based classification: best + second-best candidates, classify by `(best.confidence, margin, system/collection)`. Cross-system candidates never auto-accept.

# Part B — The acquisition planner (NEW)

## B.1 New planner service in `minerva/services/acquisition_planner.py`

The planner produces a concrete `AcquisitionPlan` from a report + constraints. It does NOT mutate state — it only computes.

### Domain types

```python
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class SelectionStrategy(str, Enum):
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
    reserve_free_bytes: int = 50 * 1024**3
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
    reason: str  # "exceeds 4 GB limit", "exceeds remaining budget", "already queued", "ambiguous", ...


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
```

### `AcquisitionPlanner`

```python
class AcquisitionPlanner:
    def __init__(
        self,
        *,
        state: MinervaState,
        download_controller: DownloadController | None = None,
        settings: QSettings | None = None,
    ) -> None: ...

    def build_plan(
        self,
        report_id: str,
        constraints: AcquisitionConstraints,
    ) -> AcquisitionPlan: ...

    def explain_deferrals(self, plan: AcquisitionPlan) -> dict[str, int]: ...
```

The planner:

1. Resolves the seed directory (`settings.value("qbit/save_path")`) and output directory (`settings.value("downloads/output_dir")`).
2. Probes each with `shutil.disk_usage`.
3. Detects whether the two paths are on the same filesystem (compare `os.stat(...).st_dev` after resolving both).
4. Tests hardlink feasibility once (try `os.link` on a temp file in the seed dir pointing at a temp file in the output dir, fall back to copy).
5. Queries the download controller for `committed_bytes` (active + queued + partial) per filesystem.
6. Loads the report's READY entries (and REVIEW_REQUIRED entries with `decision='accept'`) from `MinervaState`.
7. For each candidate, applies the constraints (max_file_bytes, collections, systems, regions, extensions).
8. Sorts by strategy (default: smallest first).
9. Walks the sorted list, adding to the plan until the limiting filesystem is full:
   - `usable_budget = min(max_total_bytes or ∞, available - reserve - existing_commitment)`
   - If same filesystem AND hardlink works: charge `size` once.
   - Otherwise: charge `size` to BOTH the seed volume and the output volume.
10. Returns the `AcquisitionPlan` with per-volume estimates.

`AcquisitionPlan` volumes are computed from the resolved seed/output paths plus the committed bytes.

## B.2 `queue_plan` on `ReportAcquisitionService`

```python
def queue_plan(self, plan: AcquisitionPlan) -> QueueResult:
    """Atomically add every PlannedFile to the download queue.

    The plan is the exact set of records queued — no re-running of
    filters or scope inference at queue time.
    """
```

Iterate `plan.selected`, build download records via the existing controller path, return a `QueueResult` summary.

## B.3 Reports page — planner UI

The Reports page replaces the simple "Download N obtainable ROMs" button with an **Acquisition plan** block that shows the planner output, then the primary action.

```
PlayStation 2 — RomVault missing report

Available                 1,284 files · 1.74 TB
Needs review                 12 files · 18.6 GB
Not found                    37 files
Already queued/downloaded    86 files · 92.4 GB

Destination
/media/roms/PlayStation 2

Space available             612 GB
Space reserved              100 GB
Usable budget               512 GB

Download plan
842 files · 509 GB

Seed volume         ROM volume
/mnt/downloads      /media/roms
720 GB available    1.8 TB available
509 GB required     0 GB additional (hardlink)
211 GB remaining    1.8 TB remaining

[ Download 842 files ]    [ Adjust selection ]
```

The "Adjust selection" button opens a panel with the constraints:

```
Acquisition limits

Maximum file size     [ 4 GB           ▼]
Maximum total size    [ 500 GB         ▼]
Leave free            [ 100 GB         ▼]
Maximum files         [ Unlimited      ▼]
Priority              [ Smallest first ▼]

Collections           [ All            ▼]
Systems               [ All            ▼]
Regions               [ All            ▼]

842 files selected · 509 GB
442 postponed · 1.23 TB

Postponed because:
318 exceed remaining budget
94 exceed the 4 GB file limit
30 are already queued

[ Download 842 files ]  [ Cancel ]
```

The plan rebuilds on every constraint change. The "Download" button is enabled only when `plan.volumes[0].fits` and `plan.volumes[1].fits` (i.e., the plan fits on both filesystems).

If the plan does NOT fit, the warning shows:

```
⚠ This plan does not fit on the ROM library volume.
```

## B.4 Quick filters

Above the planner summary, a row of quick-filter chips:

```
[ Under 1 GB ] [ Under 4 GB ] [ Disc images ] [ Cartridge ROMs ]
[ Exact matches ] [ Not queued ] [ Seeded sources ]
```

Clicking a chip adjusts the constraints. "Under 1 GB" sets `max_file_bytes = 1 GB`, "Exact matches" sets `include_reviewed_matches = False`, etc.

## B.5 Persistent presets

Saved in `QSettings` under `acquisition/presets/<name>` as JSON `AcquisitionConstraints`. A dropdown in the planner lets the user select a preset; selecting a preset applies the constraints and rebuilds the plan.

Default preset on first run:
```python
AcquisitionConstraints(
    max_file_bytes=None,
    max_total_bytes=None,
    max_file_count=None,
    reserve_free_bytes=max(50 GB, 5% of seed volume),
    strategy=SelectionStrategy.SMALLEST_FIRST,
    include_automatic_matches=True,
    include_reviewed_matches=False,  # ambiguous matches excluded by default
    require_seeded_source=False,
)
```

The disk probe runs on every report — presets don't cache free-space values.

# Part C — Report-triage inbox (NEW)

## C.1 New outcome enum in `minerva/domain/reports.py`

```python
class ReportOutcome(str, Enum):
    ACTIONABLE = "actionable"            # ≥1 eligible READY entry
    NEEDS_REVIEW = "needs_review"        # entries exist but ambiguous
    NO_SOURCE_MATCHES = "no_source_matches"  # zero candidates
    FILTERED_OUT = "filtered_out"        # candidates exist, none fit policy
    ALREADY_SATISFIED = "already_satisfied"  # all matched entries already downloaded
    EMPTY = "empty"                      # zero missing entries / parse failed
    ERROR = "error"
```

`ReportSummary.outcome` is one of these. Computed at match time and on every policy change.

## C.2 Compute outcome in `ReportAcquisitionService`

After `match_report` runs, compute:

```python
def compute_outcome(
    self, report_id: str, constraints: AcquisitionConstraints
) -> ReportOutcome:
    entries = state.get_entries(report_id)
    safe = [e for e in entries if e.resolution == ResolutionState.READY]
    ambiguous = [e for e in entries if e.resolution == ResolutionState.REVIEW_REQUIRED]
    not_found = [e for e in entries if e.resolution == ResolutionState.NOT_FOUND]
    eligible = filter_by_constraints(safe, constraints)
    if not eligible:
        if safe:
            return ReportOutcome.FILTERED_OUT
        if ambiguous:
            return ReportOutcome.NEEDS_REVIEW
        if not_found and not safe:
            return ReportOutcome.NO_SOURCE_MATCHES
        if self._all_already_present(report_id):
            return ReportOutcome.ALREADY_SATISFIED
        return ReportOutcome.EMPTY
    return ReportOutcome.ACTIONABLE
```

Eligible counts populate `ReportSummary.eligible_count` and `eligible_bytes`.

## C.3 Reports page — triage inbox

The Reports page is reorganised as an actionable-results inbox:

```
Fix missing ROMs

Eligibility: files up to 4 GB · exact/safe matches · exclude queued

23 actionable reports
1,842 obtainable files · 286 GB

[ Download all actionable ]   [ Change eligibility ]

────────────────────────────────────────────────────────────

Nintendo - Game Boy Advance
418 obtainable · 7.3 GB · 92% available
[ Download ]

Sega Mega Drive
127 obtainable · 824 MB · 74% available
[ Download ]

Sony PlayStation 2
36 obtainable · 186.0 GB · 8% available
[ Download ]

────────────────────────────────────────────────────────────

▸ 8 reports need review
▸ 91 reports have no indexed matches
▸ 14 reports were excluded by current limits
▸ 6 reports have nothing new to download
```

The default view is filtered to `outcome == ACTIONABLE`. The collapsed sections at the bottom expand to show:

- `NEEDS_REVIEW` — list of reports with `ambiguous_match_count > 0`
- `NO_SOURCE_MATCHES` — reports with all `not_found`
- `FILTERED_OUT` — reports whose candidates all exceed current policy
- `ALREADY_SATISFIED` — reports where everything is downloaded

The eligibility panel (compact, at the top):

```
Eligibility

Maximum individual file size   [ 4 GB        ▼]
Minimum obtainable files       [ 1           ▼]
Minimum obtainable data        [ 0 MB        ▼]
Include ambiguous matches      [ No          ▼]
Exclude already queued         [ Yes         ▼]
```

Changing any of these rebuilds the actionable list immediately. Reports that fall out of actionability move to the appropriate collapsed section.

## C.4 Sort

Default sort on the actionable list:
1. Most obtainable files first
2. Then highest availability percentage
3. Then smallest total bytes (lowest cost first)

Optional "Best value" sort: `obtainable_file_count / obtainable_bytes` — cartridge collections ahead of optical discs.

# Part D — Files

## New files
- `minerva/services/acquisition_planner.py`
- `tests/test_acquisition_planner.py`
- `tests/test_report_triage.py` (or fold into test_report_acquisition_service.py)

## Modified files (extend what's already drafted)
- `minerva/domain/reports.py` — add `ReportOutcome`, planner types
- `minerva/services/report_acquisition.py` — add `compute_outcome`, `queue_plan`
- `minerva/app/pages/reports.py` — planner UI, triage inbox, eligibility panel
- `minerva/app/pages/match_review.py` — already reduced; verify planner link
- `minerva_db.py` — extend with filesystem probe helpers and `get_two_best_candidates`
- `minerva_state.py` — add queries for eligible/already_present/already_queued counts per report

## Not modified
- QSS, theme tokens, library/downloads/collections/settings pages

# Part E — Tests

## New tests
- `AcquisitionPlanner`:
  - `test_max_file_size_excludes_oversized_files`
  - `test_total_budget_never_exceeded`
  - `test_reserve_preserved`
  - `test_smallest_first_maximizes_count`
  - `test_existing_queued_reduces_budget`
  - `test_partial_data_not_double_counted`
  - `test_same_filesystem_hardlink_charges_once`
  - `test_cross_filesystem_charges_twice`
  - `test_copy_fallback_cannot_overfill_output`
  - `test_multiple_reports_share_global_budget`
  - `test_cancelled_queued_releases_reservation`
  - `test_plan_matches_queued_file_ids`
  - `test_deferred_files_remain_in_pool`

- Triage:
  - `test_outcome_actionable_when_eligible`
  - `test_outcome_filtered_out_when_size_limit_excludes_all`
  - `test_outcome_no_source_matches_when_zero_candidates`
  - `test_outcome_already_satisfied`
  - `test_outcome_needs_review_when_only_ambiguous`
  - `test_eligible_count_changes_with_policy`

- Reports page:
  - `test_actionable_section_lists_actionable_reports`
  - `test_needs_review_section_collapsed_by_default`
  - `test_eligibility_panel_recomputes_actionable_list`

# Part F — Commit

Single commit:
```
feat(acquisition): replace review detour with planner + triage inbox

Adds ReportAcquisitionService and AcquisitionPlanner. Reports become an
actionable-results inbox: each report carries an outcome (ACTIONABLE,
NEEDS_REVIEW, NO_SOURCE_MATCHES, FILTERED_OUT, ALREADY_SATISFIED,
EMPTY, ERROR) and eligible counts. The planner produces a concrete
AcquisitionPlan with per-volume estimates that respect reserve,
budget, and hardlink/copy assumptions. The "Download N obtainable
ROMs" primary action consumes the plan, not a re-derived set. Match
Review is reduced to ambiguous entries only.
```

No AI/Co-Authored-By. No push. No PR.

# Part G — Verification

```bash
# New tests
PYTHONPATH=. ./.venv/bin/pytest tests/test_report_acquisition_service.py tests/test_acquisition_planner.py -q

# Updated tests
PYTHONPATH=. ./.venv/bin/pytest tests/test_reports_page.py tests/test_match_review.py tests/test_report_triage.py -q

# Full suite (pre-existing ignores)
PYTHONPATH=. ./.venv/bin/pytest tests/ -q --ignore=tests/test_match_review.py --ignore=tests/test_match_scoring.py --ignore=tests/test_new_implementations.py --ignore=tests/test_delegates.py --ignore=tests/test_record_model.py -k "not test_e2e_sidebar and not test_download_delegates and not test_column_count"
```

Manual:
1. Import a report → eligibility panel appears → planner summary shows disk budgets → "Download N files" button.
2. Change the maximum file size → plan rebuilds, button updates.
3. Expand "needs review" → ambiguous reports are listed.
4. Open a needs-review report → Match Review loads only the ambiguous entries.
5. Resolve all ambiguous entries → "Review complete" screen → download button works.
6. Cancel a queued item → its reservation is released; the planner re-fills the budget.
