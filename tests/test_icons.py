"""
Tests for Icons — all 14 factories return non-null QIcon.
"""

from __future__ import annotations

import inspect

import pytest
from PyQt6 import QtGui

from minerva.ui.icons import Icons


ICON_FACTORIES = sorted(
    name
    for name, _ in inspect.getmembers(Icons, predicate=inspect.ismethod)
    if not name.startswith("_")
)


def test_all_14_factories_return_qicon():
    """GIVEN the Icons class WHEN each factory method is called THEN
    it returns a non-null QIcon."""
    # Actually needs a running QApplication — skip the function test
    # and use the parametrized version below
    pass


@pytest.mark.parametrize("factory_name", ICON_FACTORIES)
def test_icon_factory_returns_non_null(qtbot, factory_name):
    """GIVEN the Icons class WHEN factory *factory_name* is called THEN
    it returns a non-null QIcon."""
    factory = getattr(Icons, factory_name)
    icon = factory()
    assert isinstance(icon, QtGui.QIcon)
    assert not icon.isNull(), f"{factory_name}() returned a null QIcon"


def test_icon_count():
    """GIVEN the Icons class THEN there are the expected number of
    factory methods (38 = 14 base + 8 navigation + 4 semantic status + 12 dashboard actions)."""
    assert len(ICON_FACTORIES) == 38, (
        f"Expected 38 icon factories, got {len(ICON_FACTORIES)}: "
        f"{sorted(ICON_FACTORIES)}"
    )
