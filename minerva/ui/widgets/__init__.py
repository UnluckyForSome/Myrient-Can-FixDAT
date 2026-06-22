"""
Shared widget primitives for the Minerva design system.

Only foundational primitives are re-exported here. Page-specific widgets
(InspectorPanel, LibraryInspector, CollectionInspector, DownloadInspector,
ReportNavigator, CollectionNavigator, etc.) must be imported directly from
their module.
"""

from minerva.ui.widgets.action_group import ActionGroup
from minerva.ui.widgets.activity_list import ActivityList
from minerva.ui.widgets.busy_overlay import BusyOverlay
from minerva.ui.widgets.content_state import ContentState
from minerva.ui.widgets.cover_art import CoverLabel, CoverProvider
from minerva.ui.widgets.empty_state import EmptyState
from minerva.ui.widgets.facet_list import FacetList
from minerva.ui.widgets.filter_chip import FilterChip
from minerva.ui.widgets.inspector_scaffold import InspectorScaffold
from minerva.ui.widgets.metric_card import MetricCard, MetricKind
from minerva.ui.widgets.metric_strip import MetricStrip
from minerva.ui.widgets.notification_banner import NotificationBanner
from minerva.ui.widgets.page_header import PageHeader
from minerva.ui.widgets.pagination_bar import PaginationBar
from minerva.ui.widgets.panel_header import PanelHeader
from minerva.ui.widgets.path_picker import PathPicker
from minerva.ui.widgets.property_list import PropertyList
from minerva.ui.widgets.responsive_workspace import ResponsiveWorkspace
from minerva.ui.widgets.search_toolbar import SearchToolbar
from minerva.ui.widgets.section_card import SectionCard
from minerva.ui.widgets.segmented_control import SegmentedControl
from minerva.ui.widgets.status_badge import BadgeKind, StatusBadge
from minerva.ui.widgets.surface_panel import SurfacePanel
from minerva.ui.widgets.tag_flow import TagFlow

__all__ = [
    "ActionGroup",
    "ActivityList",
    "BadgeKind",
    "BusyOverlay",
    "ContentState",
    "CoverLabel",
    "CoverProvider",
    "EmptyState",
    "FacetList",
    "FilterChip",
    "InspectorScaffold",
    "MetricCard",
    "MetricKind",
    "MetricStrip",
    "NotificationBanner",
    "PageHeader",
    "PaginationBar",
    "PanelHeader",
    "PathPicker",
    "PropertyList",
    "ResponsiveWorkspace",
    "SearchToolbar",
    "SectionCard",
    "SegmentedControl",
    "StatusBadge",
    "SurfacePanel",
    "TagFlow",
]
