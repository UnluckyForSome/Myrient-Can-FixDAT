"""
Page implementations for the Minerva app shell.
"""


from minerva.app.pages.base import BasePage
from minerva.app.pages.downloads import DownloadPageState, DownloadsPage
from minerva.app.pages.library import LibraryPage, PageState
from minerva.app.pages.reports import ReportsPage
from minerva.app.pages.settings import SettingsPage

__all__ = [
    "BasePage",
    "DownloadPageState",
    "DownloadsPage",
    "LibraryPage",
    "PageState",
    "ReportsPage",
    "SettingsPage",
]
