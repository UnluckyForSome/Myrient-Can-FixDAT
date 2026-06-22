# Patch 0015b — Hotfix: remove broken `apply_tokens` / `apply_density` protocol

**Status:** ready to apply
**Risk:** very low (pure deletion; closes an active crash path)
**LOC budget:** ≤ 40 changed lines across 9 files
**Predecessor:** none
**Successor:** `0016-shared-visual-vocabulary.md`

---

## Why this exists

`shell.py:160-165` calls `apply_tokens(self._tokens)` and `apply_density(self._density)` on every child widget of every constructed page whenever the user changes appearance. Eight widget files declare these methods as bodies that **reference an unbound local name** (the function takes `tokens` as a parameter, but the body references a free `density` and a free `tokens`):

```python
# filter_chip.py:32-35 — broken
def apply_tokens(self, tokens: ThemeTokens) -> None:
    self._tokens = tokens
    self._density = density  # ← NameError at runtime
```

Same shape, same bug, in 7 other files. Today, the crash is latent because:

* Changing density/accent in Settings is rare.
* Each broken method overrides nothing real (its body only mutates private fields that nothing else reads).

The next time anyone adds a non-trivial body to one of these methods — or the user actually toggles appearance in Settings — every page crashes with `NameError: name 'density' is not defined`.

This is not a polish item. It is a crash bug being masked by emptiness.

---

## What to change

### 1. Delete the broken `apply_tokens` / `apply_density` methods on these widgets

For each file: remove the method AND the `# ── Protocol methods ──` divider line directly above it (where present). Do not add anything. The shell's `hasattr` walk will simply skip widgets that no longer expose the method.

| File | Method to remove | Lines |
| --- | --- | --- |
| `minerva/ui/widgets/filter_chip.py` | `apply_tokens` | 32-35 (incl. divider 30) |
| `minerva/ui/widgets/page_header.py` | `apply_tokens` | 78-81 (incl. divider 76) |
| `minerva/ui/widgets/section_card.py` | `apply_tokens` | 81-84 (incl. divider 79) |
| `minerva/ui/widgets/empty_state.py` | `apply_tokens` | 125-128 (incl. divider 123) |
| `minerva/ui/widgets/pagination_bar.py` | `apply_tokens` | 140-143 (incl. divider 138) |
| `minerva/ui/widgets/activity_list.py` | `apply_tokens` | 145-148 (incl. divider 143) |
| `minerva/ui/widgets/path_picker.py` | `apply_tokens` | 72-75 (incl. divider 70) |
| `minerva/ui/widgets/search_toolbar.py` | `apply_tokens` | 174-177 (incl. divider 172) |

**Note**: only `apply_tokens` is broken on these 8 files — none of them define `apply_density`. That matches the bug shape: someone wrote a partial "protocol" implementation, copied a template, and forgot to bind the parameter.

`DetailsPanel` also has a broken method (`details_panel.py:76-80`) but the file is **unused** anywhere in the codebase. Defer its removal to `0016` (which removes the whole file). Do **not** touch it in this patch.

### 2. Cascade: update `tag_flow.py` to stop propagating

`tag_flow.py:116-124` propagates `apply_tokens` / `apply_density` to each child `FilterChip`. Once `FilterChip.apply_tokens` is gone, the propagation becomes an `AttributeError`.

Change the two methods to keep their own state only:

```python
# tag_flow.py:116-124 — replace
def apply_tokens(self, tokens: ThemeTokens) -> None:
    self._tokens = tokens
    for chip in self._chips:
        chip.apply_tokens(tokens)        # ← delete this line

def apply_density(self, density: Density) -> None:
    self._density = density
    for chip in self._chips:
        chip.apply_density(density)     # ← delete this line
```

The chip appearance is fully driven by QSS (`FilterChip` setObjectNames itself), so dropping the runtime call is safe.

### 3. No changes to `shell.py`

The `hasattr` walk in `shell.py:160-165` is correct. Once the broken methods are deleted, the walk cleanly skips them. Do not touch the shell in this patch.

### 4. No changes to `app_sidebar.py`

`app_sidebar.py:235-274` only propagates to `SidebarRow` (typed) and uses `setStyleSheet` for the rest. Removing broken methods on other widgets does not affect the sidebar.

### 5. No changes to `minerva/ui/widgets/__init__.py`

The barrel re-exports widget classes, not protocol methods. Nothing to remove.

---

## Verification

### Before patching

```bash
# Show the exact crash the patch closes
python -c "
import sys
sys.path.insert(0, '.')
import ast
for path in ['minerva/ui/widgets/filter_chip.py']:
    tree = ast.parse(open(path).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'apply_tokens':
            args = {a.arg for a in node.args.args}
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id not in args and sub.id != 'self':
                    if isinstance(sub.ctx, ast.Load):
                        print(f'{path}:{sub.lineno} unbound ref: {sub.id}')
"
```

Expected: lists `density` for `filter_chip.py` (and the other 7 widgets when run across all 8).

### After patching

```bash
# Same script — must print nothing for any of the 8 widgets
python -c "<script above>"

# Whole test suite must pass
PYTHONPATH=. ./.venv/bin/pytest tests/ -x -q

# Manual: launch app, change density in Settings, change accent.
# Page rendering must not raise. Sidebar recolor must work.
./minerva.sh
```

### Smoke test for the cascade

```bash
# This is what the shell actually does on every appearance change:
PYTHONPATH=. python -c "
from PyQt6 import QtWidgets
import sys
app = QtWidgets.QApplication(sys.argv)
from minerva.ui.widgets.tag_flow import TagFlow
from minerva.ui.widgets.filter_chip import FilterChip
from minerva.ui.theme import ThemeTokens
from minerva.ui.density import Density
tf = TagFlow()
tf.add_chip('test', 'Test')
tf.apply_tokens(ThemeTokens.for_accent('blue'))
tf.apply_density(Density.standard())
print('OK')
"
```

Must print `OK`.

---

## Definition of done

* The 8 listed `apply_tokens` methods are gone.
* `tag_flow.apply_tokens` and `tag_flow.apply_density` no longer call `chip.apply_*`.
* `pytest tests/` passes.
* `DetailsPanel.apply_tokens` is still present and broken (deferred to `0016`).
* No file outside the 9 listed above is modified.
* Commit is a single atomic change with message: `fix(ui): remove broken apply_tokens protocol that NameErrors on appearance change`.
* `git log --oneline` shows this as a clean hotfix on top of HEAD, before any `0016` work.

---

## Out of scope (handled by 0016)

* Removing `DetailsPanel` entirely.
* Removing `apply_tokens` from `MetricCard`, `StatusBadge`, `BusyOverlay`, `SpeedChart`, `NotificationBanner`, `InspectorPanel`, `ReportNavigator` (these are real implementations that do work).
* Adding `apply_tokens` discipline to the new shared primitives (`SurfacePanel`, `PropertyList`, etc.).
* The shell's `hasattr` walk is preserved as-is.

---

## Rollback

Single `git revert` of the hotfix commit restores the broken behavior. No migration concerns: the deleted methods stored no real state.
