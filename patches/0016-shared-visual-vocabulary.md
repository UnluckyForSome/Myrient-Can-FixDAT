# Patch 0016 — Foundation cleanup and shared visual vocabulary

**Status:** ready to apply after `0015b` lands
**Risk:** medium (touches every page's render path; no behavior change for end-users, but lots of internal churn)
**LOC budget:** ≤ 800 changed lines (split into 0016a / 0016b if it exceeds 600)
**Predecessor:** `0015b-hotfix-remove-broken-apply-tokens.md`
**Successor:** `0017a-reports-overhaul.md`, `0017b-match-review-overhaul.md`

This patch is **infrastructure only**. It adds shared primitives, removes dead code, and normalizes the QSS layout. It does **not** change any page's visual appearance or feature set. Visual changes start in `0017a`.

---

## 1. Goals

* Eliminate duplicate inspector scaffolding across `LibraryInspector`, `CollectionInspector`, `DownloadInspector`, `InspectorPanel`.
* Eliminate the duplicated `_ElidedValue` class (currently exists in `library_inspector.py:16` and `collection_inspector.py:14` with near-identical bodies).
* Establish one canonical "panel + header + count + actions" composition pattern via `SurfacePanel`.
* Establish one canonical "loading / empty / error / content" stack via `ContentState`.
* Establish one canonical metadata row pattern via `PropertyList`.
* Establish one canonical responsive three-pane composition via `ResponsiveWorkspace`.
* Split the QSS into coherent layers and remove the dead `DetailsPanel` widget.
* Make the `widgets/__init__.py` barrel smaller — it should only re-export foundational primitives, not page-specific inspectors.

---

## 2. New shared primitives

All files under `minerva/ui/widgets/`. Each primitive is small (≤ 200 lines) and has a clear contract.

### 2.1 `surface_panel.py`

A single containing surface that replaces the repeated hand-built `QFrame` + `QLabel` header + layout blocks.

```python
class SurfacePanel(QtWidgets.QFrame):
    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        icon: QtGui.QIcon | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None: ...

    # Body layout the caller appends to:
    body_layout: QtWidgets.QLayout  # a QVBoxLayout pre-installed

    # Header actions slot (toolbar on the right of the title):
    header_actions: QtWidgets.QHBoxLayout  # pre-installed, may be empty

    # Optional badge that appears next to the title:
    def set_count(self, n: int) -> None: ...
    def clear_count(self) -> None: ...
```

QSS object name: `surfacePanel` (with `surfacePanelRaised` modifier for raised variant).

Replaces the panel-header pattern in `ReportsPage._build_results_panel`, `LibraryPage._build_results_panel`, `CollectionsPage._build_systems_panel`, `DownloadsPage._build_queue_panel`, `MatchReviewPage._build_review_panel`.

### 2.2 `panel_header.py`

Pure header row (title + subtitle + icon + count badge + actions). Used internally by `SurfacePanel` but also exposed for cases where the caller wants only a header (e.g. inside an existing frame).

```python
class PanelHeader(QtWidgets.QWidget):
    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        icon: QtGui.QIcon | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None: ...

    def set_title(self, text: str) -> None: ...
    def set_subtitle(self, text: str) -> None: ...
    def set_count(self, n: int | None) -> None: ...   # None hides the badge
    actions_layout: QtWidgets.QHBoxLayout  # for caller to add buttons
```

### 2.3 `property_list.py`

Reusable key/value list with middle-elision, tooltips, optional copy, and selectable values. Replaces both private `_ElidedValue` classes.

```python
class PropertyList(QtWidgets.QWidget):
    def __init__(
        self,
        rows: Sequence[tuple[str, str]] = (),
        *,
        copy_values: bool = False,
        parent: QtWidgets.QWidget | None = None,
    ) -> None: ...

    def set_rows(self, rows: Sequence[tuple[str, str]]) -> None: ...
    def set_row(self, key: str, value: str) -> None: ...
    def clear(self) -> None: ...
```

* Label column: fixed minimum width 96 px, right-aligned, `text_muted` color.
* Value column: `Expanding` size policy, `ElideMiddle`, full text in tooltip, `TextSelectableByMouse` always on.
* `copy_values=True` adds a small copy icon button to the right of each value.

QSS object name: `propertyList`, with `propertyListLabel` and `propertyListValue` for child styling.

### 2.4 `inspector_scaffold.py`

A shell that specialised inspectors compose inside, instead of re-implementing the same layout.

```python
class InspectorScaffold(QtWidgets.QFrame):
    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        parent: QtWidgets.QWidget | None = None,
    ) -> None: ...

    hero_layout: QtWidgets.QLayout    # top hero slot (cover, title block)
    status_layout: QtWidgets.QLayout  # status badge row
    body_layout: QtWidgets.QLayout    # scrollable body (PropertyList, TagFlow, etc.)
    actions_layout: QtWidgets.QLayout # sticky bottom action area
```

`InspectorPanel`, `LibraryInspector`, `CollectionInspector`, `DownloadInspector` all become thin compositions of `InspectorScaffold + PropertyList + StatusBadge + ActionGroup`.

### 2.5 `content_state.py`

Replaces the per-page `QStackedWidget` of `loading / empty / error / content` widgets.

```python
class ContentState(QtWidgets.QStackedWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None: ...

    def set_loading(self, message: str = "") -> None: ...
    def set_empty(self, widget: QtWidgets.QWidget) -> None: ...
    def set_error(self, message: str, retry: Callable[[], None] | None = None) -> None: ...
    def set_content(self, widget: QtWidgets.QWidget) -> None: ...
```

Built-in loading uses `BusyOverlay` over the previous content. Built-in empty uses `EmptyState` with the caller-supplied widget as the icon/label. Built-in error uses a `NotificationBanner`-like message with an optional retry button.

### 2.6 `action_group.py`

Standardises the "primary + secondary + destructive" button stack with consistent spacing and enabled/disabled policy.

```python
class ActionGroup(QtWidgets.QWidget):
    Primary = 0
    Secondary = 1
    Destructive = 2

    def __init__(
        self,
        actions: Sequence[tuple[str, Callable[[], None], int]] = (),
        parent: QtWidgets.QWidget | None = None,
    ) -> None: ...

    def set_actions(self, actions: Sequence[tuple[str, Callable[[], None], int]]) -> None: ...
    def set_enabled(self, role: int, enabled: bool) -> None: ...
```

QSS object names: `actionGroupPrimary`, `actionGroupSecondary`, `actionGroupDestructive` for the buttons it creates.

### 2.7 `metric_strip.py`

Owns the responsive grid of `MetricCard`s. At narrow widths it switches from `1×N` to `2×(N/2)`.

```python
class MetricStrip(QtWidgets.QWidget):
    def __init__(
        self,
        cards: Sequence[MetricCard] = (),
        parent: QtWidgets.QWidget | None = None,
    ) -> None: ...

    def set_cards(self, cards: Sequence[MetricCard]) -> None: ...
    def add_card(self, card: MetricCard) -> None: ...
```

Break-point: below 900 px parent width, switch to 2-column grid. The strip is otherwise just a horizontal `QHBoxLayout` with `Stretch` between cards.

### 2.8 `responsive_workspace.py`

Pure layout helper. Knows three named slots (`"navigator"`, `"workspace"`, `"inspector"`) and three breakpoints, but nothing about what they contain.

```python
class ResponsiveWorkspace(QtWidgets.QWidget):
    WIDE = "wide"        # parent width >= 1500
    MEDIUM = "medium"    # 1150 <= parent width < 1500
    COMPACT = "compact"  # parent width < 1150

    NAVIGATOR_PREFERRED = 280
    NAVIGATOR_MIN = 240
    INSPECTOR_PREFERRED = 340
    INSPECTOR_MIN = 300
    WORKSPACE_MIN = 650

    def __init__(
        self,
        navigator: QtWidgets.QWidget,
        workspace: QtWidgets.QWidget,
        inspector: QtWidgets.QWidget,
        parent: QtWidgets.QWidget | None = None,
    ) -> None: ...

    def set_mode(self, mode: str) -> None: ...
    def current_mode(self) -> str: ...
    def set_inspector_visible(self, visible: bool) -> None: ...
    def set_navigator_visible(self, visible: bool) -> None: ...
```

In `WIDE` mode: `[navigator | workspace | inspector]` via a `QSplitter`, with the recommended widths as `setSizes`.

In `MEDIUM` mode: inspector is hidden by default; a toolbar button toggles it as a right-edge drawer overlay. Navigator remains visible.

In `COMPACT` mode: only `workspace` is visible. Navigator opens from a left-edge drawer toggle. Inspector opens from a right-edge drawer toggle. The two drawers are mutually exclusive.

The `set_inspector_visible` / `set_navigator_visible` API lets a page's `PageHeader` drive drawer state from its toolbar buttons without coupling the workspace helper to page semantics.

---

## 3. New QSS layout

Move from:

```
minerva/ui/qss/
  base.qss            # 1 monolithic file with everything
  library.qss
  downloads.qss
  collections.qss
```

To:

```
minerva/ui/qss/
  base.qss            # only global resets, palette, common typography
  layout.qss          # page-level margins, splitters, sizing
  controls.qss        # buttons, inputs, checkboxes, radios
  tables.qss          # QTableView, QTreeView, QHeaderView
  navigation.qss      # sidebar, segmented control, breadcrumbs
  cards.qss           # metric card, status badge, section card
  panels.qss          # NEW: surface panel, panel header, content state
  inspectors.qss      # NEW: inspector scaffold, property list
  actions.qss         # NEW: action group buttons
  states.qss          # NEW: loading / empty / error treatments
  library.qss         # page-specific overrides (kept, reduced)
  downloads.qss       # page-specific overrides (kept, reduced)
  collections.qss     # page-specific overrides (kept, reduced)
```

**Rule**: page-specific QSS must override a class name introduced in the shared layers, not invent new selectors. New visual rules belong in `panels.qss`, `inspectors.qss`, `actions.qss`, or `states.qss`.

`loader.py` is updated to concatenate the new files in this order:

```
base → layout → controls → tables → navigation → cards → panels →
inspectors → actions → states → {library | downloads | collections}
```

---

## 4. New semantic tokens

Extend `minerva/ui/theme/tokens.py` `ThemeTokens` with:

```python
# Existing
background, surface, surface_raised, surface_alt, border, border_strong,
text, text_muted, text_subtle, accent, accent_hover

# New — required by StatusBadge, MetricCard, Banner, Pill semantics
success_fg, success_bg, success_border
warning_fg, warning_bg, warning_border
error_fg, error_bg, error_border
info_fg, info_bg, info_border
purple_fg, purple_bg, purple_border
```

`StatusBadge` and `MetricCard` MUST read from these tokens, not from any ad-hoc color constants. Any widget that needs a new color must add a token, not hardcode.

---

## 5. Refactors

### 5.1 `LibraryInspector`

* Replace the private `_ElidedValue` (lines 16-42) with `PropertyList`.
* Compose inside `InspectorScaffold`.
* Cover hero stays in `hero_layout`; tag list stays in `body_layout`; primary/secondary action buttons go through `ActionGroup`.
* Drop `setObjectName("libraryInspectorValue")`; use `propertyListValue`.

### 5.2 `CollectionInspector`

* Replace the private `_ElidedValue` (lines 14-40) with `PropertyList`.
* Compose inside `InspectorScaffold`.
* Same body composition pattern as `LibraryInspector`.

### 5.3 `DownloadInspector`

* No private `_ElidedValue` to remove, but it hand-rolls the same `QFrame` + header + body + action stack.
* Compose inside `InspectorScaffold`. Use `PropertyList` for speed/peers/ratio/destination. Use `StatusBadge` for status.

### 5.4 `InspectorPanel`

* Re-export of generic inspector scaffold. Reduce to either a thin convenience subclass of `InspectorScaffold` or a backward-compat shim that re-exports `InspectorScaffold`. If shim, mark `@deprecated` and remove in `0017a`.

### 5.5 Remove `details_panel.py`

* No usage anywhere in `minerva/` or `tests/` (verified).
* Delete the file.
* Remove from `minerva/ui/widgets/__init__.py`.

### 5.6 Trim `widgets/__init__.py`

The barrel must only re-export **foundational** primitives:

```python
# Keep
PageHeader, MetricCard, MetricKind, StatusBadge, BadgeKind,
SegmentedControl, FilterChip, PathPicker, BusyOverlay, NotificationBanner,
EmptyState, PaginationBar, SearchToolbar, TagFlow, SectionCard,
ActivityList, CoverLabel, CoverProvider, FacetList,
# New
SurfacePanel, PanelHeader, PropertyList, InspectorScaffold,
ContentState, ActionGroup, MetricStrip, ResponsiveWorkspace
```

Remove from the barrel (import directly from the module instead):

```python
# Remove
InspectorPanel, InspectorSection,            # use InspectorScaffold
ReportNavigator, ReportListModel,           # page-specific
LibraryInspector, LibrarySummaryBar,         # page-specific
CollectionNavigator, CollectionListModel,    # page-specific
CollectionInspector,                        # page-specific
IndexDiagnosticCard,                        # page-specific
DetailsPanel, Section,                      # removed entirely
```

Update every page's import to point at the specific module.

### 5.7 Page refactor (mechanical, not visual)

Each of the 5 pages must:

1. Replace its hand-built panel-header blocks with `SurfacePanel`.
2. Replace its `QStackedWidget` of state widgets with `ContentState`.
3. Use `ResponsiveWorkspace` for the three-pane composition (or a documented exception with rationale in a comment).

The five pages do **not** change visually in this patch — only the construction code is rewritten to use the new primitives. Visual polish lands in `0017a` onward.

---

## 6. Files

### Add (8 new widget files)

```
minerva/ui/widgets/surface_panel.py
minerva/ui/widgets/panel_header.py
minerva/ui/widgets/property_list.py
minerva/ui/widgets/inspector_scaffold.py
minerva/ui/widgets/content_state.py
minerva/ui/widgets/action_group.py
minerva/ui/widgets/metric_strip.py
minerva/ui/widgets/responsive_workspace.py
```

### Add (4 new QSS files)

```
minerva/ui/qss/panels.qss
minerva/ui/qss/inspectors.qss
minerva/ui/qss/actions.qss
minerva/ui/qss/states.qss
```

### Add (extended theme)

```
minerva/ui/theme/tokens.py   # extend ThemeTokens with semantic surface tokens
```

### Modify

```
minerva/ui/qss/loader.py                           # include new QSS files
minerva/ui/widgets/__init__.py                     # trim the barrel
minerva/ui/widgets/inspector_panel.py              # become shim or remove
minerva/ui/widgets/library_inspector.py            # use PropertyList + InspectorScaffold
minerva/ui/widgets/collection_inspector.py         # use PropertyList + InspectorScaffold
minerva/ui/widgets/download_inspector.py           # use InspectorScaffold + PropertyList
minerva/app/pages/reports.py                       # use SurfacePanel + ContentState + ResponsiveWorkspace
minerva/app/pages/library.py                       # use SurfacePanel + ContentState + ResponsiveWorkspace
minerva/app/pages/downloads.py                     # use SurfacePanel + ContentState + ResponsiveWorkspace
minerva/app/pages/collections.py                   # use SurfacePanel + ContentState + ResponsiveWorkspace
minerva/app/pages/match_review.py                  # use SurfacePanel + ContentState + ResponsiveWorkspace
minerva/app/pages/settings.py                      # use SurfacePanel + ContentState
```

### Delete

```
minerva/ui/widgets/details_panel.py
```

(plus its 2 imports in `widgets/__init__.py`)

---

## 7. Definition of done

* `grep -rn "_ElidedValue" minerva/` returns zero matches.
* `grep -rn "DetailsPanel" minerva/` returns zero matches.
* `grep -rn "QStackedWidget" minerva/app/pages/` returns matches only where pages legitimately need stacking unrelated to state (none expected).
* Every page imports its specialised widgets directly from the module, not from `widgets/__init__.py`.
* All new QSS files are loaded by `loader.py`; `loader.py` order matches section 3.
* `ThemeTokens` has all 21 named tokens (4 base + 4 surfaces + 9 status + 4 neutrals… verify count in the file).
* `pytest tests/` passes.
* Launching the app and visiting every page shows **the same** visual layout as before this patch — only the construction code is reorganised.
* Commit message: `refactor(ui): introduce shared visual primitives and split QSS layers`. If the diff exceeds 600 lines, split into `0016a-shared-primitives` (adds the 8 files) and `0016b-page-migration` (rewires pages to use them).

---

## 8. Out of scope

* Visual redesign of any page (lands in `0017a` onward).
* Responsive breakpoint tuning beyond the three defaults (later patches can adjust per page).
* New icons. The `Icons` registry is unchanged.
* Removing the `apply_tokens` / `apply_density` protocol from widgets that still genuinely need it (`MetricCard`, `StatusBadge`, `BusyOverlay`, `SpeedChart`, `NotificationBanner`, `InspectorPanel`/`InspectorScaffold`).
* Library query performance. That is `0018`.

---

## 9. Rollback

Two `git revert` commands (one per split commit if split) restore the previous construction code. The new primitive files become dead code but cause no runtime effect. No data migration.
