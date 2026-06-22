#!/usr/bin/env python3
"""
Myrient Can FixDAT

Identify and download missing ROMs from Myrient using IGIR reports or a fixdat.
Includes a Qt (PyQt5) GUI.

Requirements:
    pip install requests PyQt5

For building exe (optional):
    pip install pyinstaller
    See build/ directory for build scripts.
"""

from __future__ import annotations

# Standard library imports
import csv
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional, Tuple

# Third-party imports
import requests

# Qt imports
from PyQt5 import QtCore, QtGui, QtNetwork, QtWidgets  # type: ignore
from PyQt5.QtCore import QSettings

# Optional HTML parser (recommended). If missing, we fall back to a simpler regex parser.
try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:
    BeautifulSoup = None  # type: ignore


# ============================================================================
# CONSTANTS
# ============================================================================

# Settings keys for QSettings persistence
SETTING_DAT_FILE = "dat_file"
SETTING_ROMS_DIR = "roms_directory"
SETTING_DOWNLOADS_DIR = "downloads_directory"
SETTING_MYRIENT_URL = "myrient_base_url"
SETTING_USE_IGIR = "use_igir"
SETTING_CLEAN_ROMS = "clean_roms"

# File and path constants
DEFAULT_DAT_FALLBACK = "dat/psx.dat"
DEFAULT_MYRIENT_URL = "https://set.once.me/"
FIXDAT_FILE = "fixdat.dat"
IGIR_EXE_DEFAULT = "igir/igir.exe"
IGIR_REPO = "emmercm/igir"
IGIR_RELEASES_API = f"https://api.github.com/repos/{IGIR_REPO}/releases/latest"
DAT_CACHE_DIR = "dat"
NOT_REQUIRED_DIR = "NotRequired"

# File extensions and patterns
ROM_EXTENSIONS = (".zip", ".7z", ".rar")
DAT_EXTENSION = ".dat"
TMP_EXTENSION = ".tmp"

# Network and download constants
DEFAULT_TIMEOUT = 60
PROGRESS_UPDATE_INTERVAL = 0.2
CHUNK_SIZE = 1024 * 256  # 256KB
MAX_SIZE_DIFFERENCE = 1_048_576  # 1MB
HTTP_USER_AGENT = "MyrientCanFixDAT/1.0"

# UI constants
WINDOW_MIN_WIDTH = 1200
WINDOW_HEIGHT = 1000
TITLE_BAR_HEIGHT = 32
BUTTON_HEIGHT = 32
STATUS_INDICATOR_WIDTH = 24
LOG_FONT_SIZE = 11

# Progress constants
CONFIG_VALIDATION_PROGRESS = 1.0
CLEAN_COMPLETE_PROGRESS = 2.0
MISSING_GAMES_FOUND_PROGRESS = 18.0
MYRIENT_INDEX_DOWNLOADED_PROGRESS = 19.0
MATCHED_GAMES_PROGRESS = 20.0
DOWNLOAD_START_PROGRESS = 20.0
DOWNLOAD_COMPLETE_PROGRESS = 100.0

# Size formatting constants
SIZE_UNITS = ["B", "KB", "MB", "GB", "TB"]
SIZE_MULTIPLIERS = {
    "B": 1,
    "K": 1024, "KB": 1024,
    "M": 1024**2, "MB": 1024**2, "MIB": 1024**2,
    "G": 1024**3, "GB": 1024**3, "GIB": 1024**3,
    "T": 1024**4, "TB": 1024**4, "TIB": 1024**4,
}

# GitHub API constants
FRESH1G1R_REPO = "UnluckyForSome/Fresh1G1R"
DAILY_1G1R_PATH = "daily-1g1r-dat"
GITHUB_API_BASE = "https://api.github.com/repos"

# RetroAchievements DATs (Unofficial-RA-DATs)
RA_DAT_REPO = "UltraGodAzgorath/Unofficial-RA-DATs"
RA_DAT_PATH = "DATs/RetroAchievements (No Subfolders)"

# Collection types (for Myrient path inference)
COLLECTION_NO_INTRO = "No-Intro"
COLLECTION_REDUMP = "Redump"
COLLECTION_RETRO_ACHIEVEMENTS = "RetroAchievements"

# Error messages
ERROR_CONFIG_VALIDATION = "Configuration validation failed. Please check the log."
ERROR_IGIR_CLEAN_FAILED = "IGIR clean failed. Cannot proceed."
ERROR_MISSING_FIXDAT = "No games found in fixdat."
ERROR_MYRIENT_URL_MISSING = "Could not determine Myrient URL."
ERROR_MYRIENT_INDEX_FAILED = "Failed to fetch Myrient index."
ERROR_STOP_REQUESTED = "Downloads cancelled by user"


# ============================================================================
# GLOBALS / CONSTANTS
# ============================================================================

def _get_app_directory() -> Path:
    """Get the application directory - works for both script and PyInstaller exe.
    
    When running as a PyInstaller --onefile exe, __file__ points to a temp extraction
    directory. We need to use the exe's actual location for persistent files like
    dat/ and igir/.
    """
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle - use exe's directory
        return Path(sys.executable).parent.resolve()
    else:
        # Running as Python script - use script's directory
        return Path(__file__).parent.resolve()

SCRIPT_DIR = _get_app_directory()

APP_STYLESHEET = """
QWidget#titleBar {
    background-color: #1f2027;
}
QLabel#titleText {
    color: #e6e6eb;
    font-weight: 600;
}
QLabel#titleIcon {
    font-size: 14px;
}
QPushButton#titleButton, QPushButton#titleButtonClose {
    background-color: transparent;
    border: none;
    border-radius: 0;
    padding: 0;
    font-size: 14px;
    color: #e0e0e5;
}
QPushButton#titleButton:hover { background-color: #3b3d4a; }
QPushButton#titleButtonClose:hover { background-color: #e81123; color: #ffffff; }

QGroupBox {
    border: 1px solid #3c3c46;
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 14px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #c0c0d0;
}
QLabel { color: #e6e6eb; }

QCheckBox, QRadioButton { color: #e6e6eb; spacing: 6px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 2px solid #4a5265;
    border-radius: 3px;
    background-color: #18181f;
}
QCheckBox::indicator:hover { border-color: #5aa0ff; }
QCheckBox::indicator:checked {
    background-color: #5aa0ff;
    border-color: #7ab3ff;
}
QCheckBox::indicator:checked:hover {
    background-color: #6cb0ff;
    border-color: #8bc4ff;
}
QCheckBox:disabled { color: #666666; }
QCheckBox::indicator:disabled { border-color: #666666; background-color: #333333; }
QCheckBox::indicator:checked:disabled { background-color: #666666; border-color: #666666; }
QLabel:disabled { color: #666666; }

QLineEdit, QPlainTextEdit {
    background-color: #18181f;
    border: 1px solid #444454;
    border-radius: 4px;
    padding: 3px;
    color: #f0f0f5;
}
QLineEdit:focus, QPlainTextEdit:focus { border-color: #5aa0ff; }

QPushButton {
    background-color: #2f3645;
    border: 1px solid #4a5265;
    border-radius: 4px;
    padding: 5px 14px;
    color: #f0f0f5;
}
QPushButton:hover { background-color: #3a4356; }
QPushButton:pressed { background-color: #252a36; }

QPushButton#primaryRunButton {
    background-color: #5aa0ff;
    border: 1px solid #7ab3ff;
    color: #0b1020;
    font-weight: 600;
    padding: 6px 18px;
}
QPushButton#primaryRunButton:hover { background-color: #6cb0ff; }
QPushButton#primaryRunButton:pressed { background-color: #4a8fe0; }

QPushButton#stopButton {
    background-color: #dc3545;
    border: 1px solid #c82333;
    border-radius: 4px;
    padding: 5px 14px;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#stopButton:hover { background-color: #c82333; }
QPushButton#stopButton:pressed { background-color: #bd2130; }
QPushButton#stopButton:disabled {
    background-color: #6c757d;
    border-color: #6c757d;
    color: #ffffff;
}

QProgressBar {
    border: 1px solid #4a5265;
    border-radius: 4px;
    text-align: center;
    background-color: #18181f;
    color: #e6e6eb;
    min-height: 32px;
    font-size: 11px;
    font-weight: 600;
}
QProgressBar::chunk {
    background-color: #5aa0ff;
    border-radius: 3px;
}

/* Individual metric boxes - aligned with progress bars */
QWidget#metricBox {
    background-color: #1a1c23;
    border: 1px solid #444454;
    border-radius: 4px;
    min-width: 140px;
    max-width: 160px;
    padding: 2px;
}

QLabel#metricTitle {
    color: #c0c0d0;
    font-size: 9px;
    font-weight: 600;
    text-align: center;
    margin: 0;
    padding: 0;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

QLabel#metricValue {
    color: #e6e6eb;
    font-size: 12px;
    font-weight: 700;
    text-align: center;
    margin: 0;
    padding: 0;
    font-family: 'Consolas', 'Monaco', monospace;
}

QListView, QListWidget, QTreeView {
    background-color: #18181f;
    border: 1px solid #444454;
    color: #f0f0f5;
}
QListWidget#datListWidget { background-color: #2a2b33; }

QWidget#dialogPanel {
    background-color: #18181f;
    border-radius: 6px;
}

QPushButton#segLeft, QPushButton#segMid, QPushButton#segRight {
    background-color: #2f3645;
    border: 1px solid #4a5265;
    border-radius: 4px;
    padding: 4px 12px;
    color: #e0e0e5;
}
QPushButton#segLeft:hover, QPushButton#segMid:hover, QPushButton#segRight:hover {
    background-color: #3a4356;
}
QPushButton#segLeft:checked, QPushButton#segMid:checked, QPushButton#segRight:checked {
    background-color: #5aa0ff;
    border-color: #7ab3ff;
    color: #0b1020;
    font-weight: 600;
}

QComboBox {
    background-color: #18181f;
    border: 1px solid #444454;
    border-radius: 4px;
    padding: 2px 6px;
    color: #f0f0f5;
}
QComboBox::drop-down { border: none; width: 18px; }
QComboBox::down-arrow {
    image: none;
    width: 0; height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #c0c0d0;
    margin-right: 4px;
}

QPushButton#flatDialogButton {
    background-color: transparent;
    border: 1px solid #4a5265;
    border-radius: 4px;
    padding: 4px 12px;
    color: #e0e0e5;
}
QPushButton#flatDialogButton:hover { background-color: #3a4356; }
QPushButton#primaryDialogButton {
    background-color: #5aa0ff;
    border: 1px solid #7ab3ff;
    border-radius: 4px;
    padding: 4px 14px;
    color: #0b1020;
    font-weight: 600;
}
QPushButton#primaryDialogButton:hover { background-color: #6cb0ff; }

QScrollBar:vertical, QScrollBar:horizontal {
    background: #18181f;
    border: 1px solid #444454;
    border-radius: 4px;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #3a4356;
    border-radius: 4px;
}
QScrollBar::add-line, QScrollBar::sub-line { background: none; border: none; }

QWidget#statusContainer { background-color: #252a36; border-radius: 6px; }
QLabel#statusTitleLabel { color: #c5cff5; font-weight: bold; }
QLabel#statusValueLabel { color: #ffffff; font-weight: 600; }

QStatusBar, QToolTip { color: #e6e6eb; background-color: #2a2a33; }
QMessageBox { background-color: #1e1e24; color: #e6e6eb; }
QMessageBox QLabel { color: #e6e6eb; background-color: transparent; }
QMessageBox QPushButton {
    background-color: #2f3645;
    border: 1px solid #4a5265;
    border-radius: 4px;
    padding: 5px 14px;
    color: #f0f0f5;
    min-width: 80px;
}
QMessageBox QPushButton:hover { background-color: #3a4356; }
QMessageBox QPushButton:pressed { background-color: #252a36; }

QDialog { background-color: #1e1e24; color: #e6e6eb; }
QDialog QLabel { color: #e6e6eb; }
QDialog QPushButton {
    background-color: #2f3645;
    border: 1px solid #4a5265;
    border-radius: 4px;
    padding: 5px 14px;
    color: #f0f0f5;
}
QDialog QPushButton:hover { background-color: #3a4356; }
QDialog QPushButton:pressed { background-color: #252a36; }
"""


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


def normalize_path_display(path_str: str) -> str:
    """Normalize path string for consistent display in UI.
    
    - Converts to OS-native separators (backslash on Windows, forward on Unix)
    - Strips trailing separators
    - Returns empty string for empty/None input
    """
    if not path_str:
        return ""
    # Use pathlib to normalize, then convert to string with OS-native separators
    try:
        normalized = str(Path(path_str))
        return normalized.rstrip("/\\")
    except Exception:  # noqa: BLE001
        return path_str


def get_latest_dat_file() -> str:
    """Get the most recently modified DAT file from dat directory."""
    dat_cache_dir = SCRIPT_DIR / DAT_CACHE_DIR
    if not dat_cache_dir.exists():
        return normalize_path_display(DEFAULT_DAT_FALLBACK)

    dat_files = list(dat_cache_dir.glob(f"*{DAT_EXTENSION}"))
    if not dat_files:
        return normalize_path_display(DEFAULT_DAT_FALLBACK)

    latest_file = max(dat_files, key=lambda f: f.stat().st_mtime)
    return normalize_path_display(str(latest_file))


def get_initial_dat_file() -> str:
    """Get initial DAT file path for GUI - returns empty string if no DAT found."""
    dat_cache_dir = SCRIPT_DIR / DAT_CACHE_DIR
    if not dat_cache_dir.exists():
        return ""

    dat_files = list(dat_cache_dir.glob(f"*{DAT_EXTENSION}"))
    if not dat_files:
        return ""

    latest_file = max(dat_files, key=lambda f: f.stat().st_mtime)
    return normalize_path_display(str(latest_file))


def resolve_path(path_str: str) -> Path:
    """Resolve a path string, expanding user home (~) and making absolute.

    If relative, resolves relative to SCRIPT_DIR (keeps existing behavior).
    """
    if not path_str:
        return Path.cwd().resolve()

    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = SCRIPT_DIR / p
    return p.resolve()


def ensure_directory_exists(path: Path | str, create_if_missing: bool = False) -> Tuple[Path, bool]:
    """Ensure a directory exists, optionally creating it.

    Returns (resolved_path, exists).
    """
    resolved = resolve_path(str(path))
    exists = resolved.exists() and resolved.is_dir()

    if not exists and create_if_missing:
        resolved.mkdir(parents=True, exist_ok=True)
        exists = True

    return resolved, exists


def validate_file_path(path_str: str, description: str = "file") -> Tuple[Path, bool, str]:
    """Validate a file path and return (path, is_valid, error_message)."""
    try:
        path = resolve_path(path_str)
        if path.exists() and path.is_file():
            return path, True, ""
        return path, False, f"{description} not found: {path}"
    except Exception as e:
        return Path(path_str), False, f"Invalid {description} path: {e}"


def validate_directory_path(path_str: str, description: str = "directory",
                           allow_create: bool = False) -> Tuple[Path, bool, str]:
    """Validate a directory path and return (path, is_valid, error_message)."""
    try:
        path = resolve_path(path_str)
        if path.exists() and path.is_dir():
            return path, True, ""
        if allow_create and path.parent.exists() and path.parent.is_dir():
            return path, True, ""
        return path, False, f"{description} not found: {path}"
    except Exception as e:
        return Path(path_str), False, f"Invalid {description} path: {e}"


def prompt_yes_no(question: str, default: str = "y", skip_auto: bool = False) -> bool:
    """Prompt user for yes/no input with default."""
    if not skip_auto and CONFIG.auto_config_yes:
        print(f"{question} [AUTO-YES]")
        return True

    default_bool = default.lower() in ("y", "yes", "true", "1")

    while True:
        prompt = f"{question} [{'Y/n' if default_bool else 'y/N'}]: "
        if CONFIG.auto_config_yes:
            response = default
            print(f"{prompt}{response}")
        else:
            response = input(prompt).strip().lower()

        if not response:
            return default_bool
        if response in ("y", "yes", "true", "1"):
            return True
        if response in ("n", "no", "false", "0"):
            return False

        print("Please answer 'y' or 'n'")


def format_size(bytes_size: int) -> str:
    """Format bytes into human readable format."""
    if bytes_size <= 0:
        return "0 B"

    size = float(bytes_size)
    idx = 0
    while size >= 1024.0 and idx < len(SIZE_UNITS) - 1:
        size /= 1024.0
        idx += 1

    if idx == 0:
        return f"{int(size)} {SIZE_UNITS[idx]}"
    return f"{size:.1f} {SIZE_UNITS[idx]}"


def format_speed(bytes_per_sec: float) -> str:
    """Format bytes per second into human readable format."""
    return f"{format_size(int(bytes_per_sec))}/s"


def format_time(seconds: float) -> str:
    """Format seconds into human readable time."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}h {m}m {s}s"


def extract_system_name(filename_stem: str, collection: str) -> str:
    """Extract just the system name from a filename or DAT header name."""
    # Remove Fresh1G1R suffix if present
    filename_stem = re.sub(r" \(Fresh1G1R - [^)]+\)$", "", filename_stem)

    collection = (collection or "").lower().strip()

    if collection in ("no-intro", "nointro", "no intro"):
        # No-Intro: Extract everything before (YYYYMMDD-HHMMSS)
        date_pattern = r"\(\d{8}-\d{6}\)"
        m = re.search(date_pattern, filename_stem)
        return filename_stem[: m.start()].strip() if m else filename_stem.strip()

    # Redump: remove "- Datfile (number)" and extract before date
    normalized = re.sub(r" - Datfile \(\d+\)", "", filename_stem)
    date_pattern = r"\(\d{4}-\d{2}-\d{2} \d{2}[-:]\d{2}[-:]\d{2}\)"
    m = re.search(date_pattern, normalized)
    if m:
        return normalized[: m.start()].strip()

    normalized = re.sub(r" \(Retool.*$", "", normalized)
    return normalized.strip()


def _normalize_title(s: str) -> str:
    """Normalization used for matching games<->files."""
    s = s.strip()
    s = re.sub(r"\.zip$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)  # remove trailing (...) blocks
    return s.strip().lower()


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Configuration management with validation and type safety."""

    def __init__(self) -> None:
        self.fixdat: Optional[Path] = None  # Path to manual fixdat file (None to auto-generate)
        self.list_dat: str = get_latest_dat_file()  # Path to the latest DAT file from dat/ directory
        self.roms_directory: str = ""  # Empty by default - user must set
        self.downloads_directory: str = ""  # Empty by default - user must set
        self.myrient_base_url: str = DEFAULT_MYRIENT_URL  # Default Myrient URL (can be changed in GUI)
        self.igir_exe: str = IGIR_EXE_DEFAULT
        self.igir_version_override: str = "4.1.2"
        self.auto_config_yes: bool = True
        self.clean_roms: bool = True
        self.include_clones: bool = True  # When False (1G1R), exclude cloneof entries

    def to_dict(self) -> Dict[str, object]:
        """Convert config to dictionary for backward compatibility."""
        return {
            "fixdat": self.fixdat,
            "list_dat": self.list_dat,
            "roms_directory": self.roms_directory,
            "downloads_directory": self.downloads_directory,
            "myrient_base_url": self.myrient_base_url,
            "igir_exe": self.igir_exe,
            "igir_version_override": self.igir_version_override,
            "auto_config_yes": self.auto_config_yes,
            "clean_roms": self.clean_roms,
            "include_clones": self.include_clones,
        }

    def update_from_dict(self, data: Dict[str, object]) -> None:
        """Update config from dictionary."""
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def validate_paths(self) -> Dict[str, bool]:
        """Validate all path configurations and return status dict."""
        results = {}

        # Validate DAT file
        dat_path = resolve_path(self.list_dat)
        results["dat_exists"] = dat_path.exists() and dat_path.is_file()

        # Validate IGIR executable
        igir_path = resolve_path(self.igir_exe)
        results["igir_exists"] = igir_path.exists() and igir_path.is_file()

        # Validate ROMs directory
        roms_path = resolve_path(self.roms_directory)
        results["roms_exists"] = roms_path.exists() and roms_path.is_dir()

        # Validate downloads directory
        downloads_path = resolve_path(self.downloads_directory)
        results["downloads_exists"] = downloads_path.exists() and downloads_path.is_dir()
        results["downloads_creatable"] = downloads_path.parent.exists() and downloads_path.parent.is_dir()

        # Validate Myrient URL
        results["myrient_url_valid"] = bool(self.myrient_base_url and
                                          self.myrient_base_url.startswith(("http://", "https://")))

        return results


# Global config instance
CONFIG = Config()

# Use direct requests instead of shared session (like old working script)
# HTTP = requests.Session()
# HTTP.headers.update({"User-Agent": HTTP_USER_AGENT})


# ============================================================================
# CORE FUNCTIONS
# ============================================================================

ProgressCallback = Callable[[int, int, float, float], None]


def download_file(
    url: str,
    output_path: Path | str,
    expected_size: int = 0,
    progress_callback: Optional[ProgressCallback] = None,
    session: Optional[requests.Session] = None,
) -> Tuple[bool, int, float]:
    """Download a file with progress tracking. Uses a temp file then atomic replace."""
    # Use direct requests.get instead of session (like old working script)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    downloaded = 0
    start_time = time.time()

    try:
        response = requests.get(url, stream=True, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        if total_size == 0 and expected_size > 0:
            total_size = expected_size

        last_update = start_time

        with open(temp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.time()
                    if progress_callback and (now - last_update) >= PROGRESS_UPDATE_INTERVAL:
                        elapsed = now - start_time
                        rate = downloaded / elapsed if elapsed > 0 else 0.0
                        progress_callback(downloaded, total_size, rate, elapsed)
                        last_update = now

        elapsed = time.time() - start_time
        rate = downloaded / elapsed if elapsed > 0 else 0.0

        # Lenient size verification (DATs can be stale). Only note large differences (>1MB).
        if expected_size > 0 and abs(downloaded - expected_size) > MAX_SIZE_DIFFERENCE:
            print(
                f"   ℹ️  Large size difference: expected {expected_size:,}, got {downloaded:,} "
                f"({downloaded - expected_size:+,} bytes)"
            )

        # Atomic replace
        temp_path.replace(output_path)

        if progress_callback:
            progress_callback(downloaded, total_size, rate, 0.0)

        return True, downloaded, elapsed

    except KeyboardInterrupt:
        # best-effort cleanup
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        raise
    except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
        # Network-related errors
        print(f"   ❌ Network error: {e}")
        # best-effort cleanup
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        return False, 0, 0.0
    except OSError as e:
        # File system errors
        print(f"   ❌ File system error: {e}")
        # best-effort cleanup
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        try:
            if output_path.exists():
                output_path.unlink()
        except OSError:
            pass
        return False, 0, 0.0
    except Exception as e:  # noqa: BLE001
        # Unexpected errors
        print(f"   ❌ Unexpected error during download: {e}")
        # best-effort cleanup
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        try:
            if output_path.exists():
                output_path.unlink()
        except OSError:
            pass
        return False, 0, 0.0


def check_fixdat_setup() -> Tuple[bool, Optional[Path]]:
    """Check for manual fixdat file in script directory."""
    fixdat_path = SCRIPT_DIR / FIXDAT_FILE
    if fixdat_path.exists():
        print(f"📄 Found manual fixdat: {fixdat_path}")
        return True, fixdat_path
    return False, None


def validate_config(
    has_manual_fixdat: bool,
    manual_fixdat: Optional[Path],
    require_igir: bool = True,
) -> Tuple[bool, Optional[str]]:
    """Validate all configuration paths and URLs. Returns (success, myrient_url).
    When require_igir is False (e.g. 'Use IGIR' is off and clean_roms is off),
    a missing IGIR executable is not treated as an error."""
    errors: List[str] = []
    warnings: List[str] = []
    config_info: List[Tuple[str, str, str]] = []
    myrient_url: Optional[str] = None

    print("\n" + "=" * 70)
    print("⚙️  Configuration Check")
    print("=" * 70)
    print()

    list_dat, dat_valid, dat_error = validate_file_path(CONFIG.list_dat, "DAT file")
    if has_manual_fixdat and manual_fixdat:
        config_info.append(("📄 DAT Source", f"Manual fixdat: {manual_fixdat.name}", "✅ Set"))
    elif dat_valid:
        config_info.append(("📄 DAT Source", f"Auto DAT: {list_dat}", "✅ Found"))
    else:
        errors.append(dat_error)

    igir_exe, igir_valid, igir_error = validate_file_path(CONFIG.igir_exe, "IGIR executable")
    if igir_valid:
        config_info.append(("🔧 IGIR Executable", str(igir_exe), "✅ Found"))
    elif require_igir:
        errors.append(igir_error)
    else:
        config_info.append(("🔧 IGIR Executable", str(igir_exe) if igir_exe else "—", "⚠️  Not required (skipped)"))

    roms_dir, roms_valid, roms_error = validate_directory_path(CONFIG.roms_directory, "ROMs directory")
    if roms_valid:
        config_info.append(("📁 ROMs Directory", str(roms_dir), "✅ Exists"))
    else:
        warnings.append(roms_error)

    downloads_dir, downloads_valid, downloads_error = validate_directory_path(
        CONFIG.downloads_directory, "Downloads directory", allow_create=True)
    if downloads_valid:
        if downloads_dir.exists():
            config_info.append(("📥 Downloads Directory", str(downloads_dir), "✅ Exists"))
        else:
            config_info.append(("📥 Downloads Directory", f"Will create: {downloads_dir}", "⚠️  Missing"))
    else:
        errors.append(downloads_error)

    base_url = CONFIG.myrient_base_url
    base_url = str(base_url) if base_url else ""
    if not base_url:
        errors.append(
            "Myrient base URL not set. Please enter your Myrient base URL in the GUI."
        )
        config_info.append(("🔗 Myrient Base URL", "Not configured", "❌ Missing"))
    else:
        config_info.append(("🔗 Myrient Base URL", base_url, "✅ Set"))
        if list_dat.exists():
            inferred_url = infer_myrient_url_from_dat(list_dat, base_url)
            if inferred_url:
                myrient_url = inferred_url
                config_info.append(("🌐 Inferred Myrient URL", inferred_url, "✅ Inferred"))
            else:
                errors.append(
                    "Could not infer Myrient URL from DAT. Ensure the DAT follows Fresh1G1R naming "
                    "or that the DAT header includes collection metadata."
                )
                config_info.append(("🌐 Inferred Myrient URL", "Could not infer", "❌ Failed"))
        else:
            warnings.append("Cannot infer Myrient URL: DAT file not found.")
            config_info.append(("🌐 Inferred Myrient URL", "N/A (DAT not found)", "⚠️  Skipped"))

    clean_roms = CONFIG.clean_roms
    config_info.append(("🧹 Clean ROMs", "Enabled" if clean_roms else "Disabled", "✅ Will run" if clean_roms else "⚠️  Skipped"))

    print("Configuration Status:")
    for name, value, status in config_info:
        print(f"   {status} {name}: {value}")

    if warnings:
        print("\n⚠️  Warnings:")
        for w in warnings:
            print(f"   • {w}")

    if errors:
        print("\n❌ Errors:")
        for e in errors:
            print(f"   • {e}")
        print("\nPlease fix the errors above and try again.")
        return False, None

    print("\n✅ Configuration validated successfully!")
    return True, myrient_url


# ============================================================================
# IGIR AUTO-DOWNLOAD FUNCTIONS
# ============================================================================


def get_igir_asset_info(release_data: dict) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract download URL and asset name from a release data object.
    Returns (download_url, asset_name) or (None, None) if not found.
    """
    assets = release_data.get("assets", [])
    download_url = None
    asset_name = None

    # First, try to find a standalone .exe file
    for asset in assets:
        name = asset.get("name", "")
        name_lower = name.lower()
        # Look for Windows executable
        if name_lower == "igir.exe" or (("windows" in name_lower or "win" in name_lower) and name_lower.endswith(".exe")):
            download_url = asset.get("browser_download_url")
            asset_name = name
            break

    # If no standalone .exe found, try to find a zip file with Windows in the name
    if not download_url:
        for asset in assets:
            name = asset.get("name", "")
            name_lower = name.lower()
            if (("windows" in name_lower or "win" in name_lower) and name_lower.endswith(".zip")):
                download_url = asset.get("browser_download_url")
                asset_name = name
                break

    # If still nothing, try any .exe file
    if not download_url:
        for asset in assets:
            name = asset.get("name", "")
            name_lower = name.lower()
            if name_lower.endswith(".exe") and "igir" in name_lower:
                download_url = asset.get("browser_download_url")
                asset_name = name
                break

    # Last resort: try any zip file
    if not download_url:
        for asset in assets:
            name = asset.get("name", "")
            if name.lower().endswith(".zip"):
                download_url = asset.get("browser_download_url")
                asset_name = name
                break

    return download_url, asset_name


def get_latest_igir_version() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Check GitHub releases API for the latest IGIR version.
    Returns (version_tag, download_url, asset_name) or (None, None, None) on error.
    """
    try:
        resp = requests.get(IGIR_RELEASES_API, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        version_tag = data.get("tag_name")
        download_url, asset_name = get_igir_asset_info(data)
        return version_tag, download_url, asset_name
    except Exception as e:  # noqa: BLE001
        print(f"   ⚠️  Could not check for IGIR updates: {e}")
        return None, None, None


def get_specific_igir_version(version_tag: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Get a specific IGIR version from GitHub releases API.
    version_tag can be with or without 'v' prefix (e.g., "v4.1.0" or "4.1.0").
    Returns (version_tag, download_url, asset_name) or (None, None, None) on error.
    """
    try:
        # Normalize version tag (ensure it has 'v' prefix for API)
        if not version_tag.startswith('v'):
            version_tag = f"v{version_tag}"

        # Get specific release
        release_api = f"https://api.github.com/repos/{IGIR_REPO}/releases/tags/{version_tag}"

        resp = requests.get(release_api, timeout=10)
        if resp.status_code == 404:
            print(f"   ⚠️  IGIR version {version_tag} not found on GitHub")
            return None, None, None
        resp.raise_for_status()
        data = resp.json()
        download_url, asset_name = get_igir_asset_info(data)
        return version_tag, download_url, asset_name
    except Exception as e:  # noqa: BLE001
        print(f"   ⚠️  Could not fetch IGIR version {version_tag}: {e}")
        return None, None, None


def get_current_igir_version(igir_path: Path) -> Optional[str]:
    """
    Get the currently installed IGIR version from stored version file.
    Returns version string or None if unable to determine.
    """
    if not igir_path.exists():
        return None

    # Read version from stored file
    version_file = igir_path.parent / "INSTALLED_VERSION.txt"
    if version_file.exists():
        try:
            version = version_file.read_text().strip()
            if version:
                return version
        except Exception:  # noqa: BLE001
            pass

    return None


def download_and_extract_igir(
    download_url: str,
    version_tag: str,
    output_path: Path,
    asset_name: Optional[str] = None,
    current_version: Optional[str] = None,
    log_callback: Optional[Callable[[str], None]] = None
) -> bool:
    """
    Download and extract the latest IGIR release.
    Returns True on success.
    """
    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    try:
        is_zip = asset_name and asset_name.lower().endswith('.zip') if asset_name else download_url.endswith('.zip')
        is_exe = asset_name and asset_name.lower().endswith('.exe') if asset_name else download_url.endswith('.exe')

        if current_version:
            log(f"   🔄 Updating IGIR to {version_tag} from {current_version}...")
        else:
            log(f"   📥 Downloading IGIR {version_tag}...")

        # Use system temp directory (automatically cleaned up by OS)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            temp_file = temp_path / ("igir-update.zip" if is_zip else "igir.exe")

            # Download the release
            log(f"   ⬇️  Downloading from {download_url}...")
            resp = requests.get(download_url, timeout=120, stream=True)
            resp.raise_for_status()
            with open(temp_file, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            # If it's a zip file, extract it
            if is_zip:
                log("   📦 Extracting...")
                extract_dir = temp_path / "igir-extract"
                extract_dir.mkdir(parents=True, exist_ok=True)

                with zipfile.ZipFile(temp_file, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)

                # Find igir.exe in extracted files (case-insensitive)
                igir_exe = None
                for item in extract_dir.rglob("*"):
                    if item.is_file() and item.name.lower() == "igir.exe":
                        igir_exe = item
                        break

                if not igir_exe:
                    log("   ❌ Could not find igir.exe in extracted files")
                    return False

                # Copy to output location
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(igir_exe), str(output_path))
            elif is_exe:
                # Direct .exe download
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(temp_file), str(output_path))
            else:
                log(f"   ❌ Unknown file type: {asset_name or 'unknown'}")
                return False

        # Make sure output path is executable (on Unix systems)
        try:
            output_path.chmod(0o755)
        except (AttributeError, PermissionError):
            # Windows doesn't support chmod, or permission error - that's okay
            pass

        # Save the installed version
        version_file = output_path.parent / "INSTALLED_VERSION.txt"
        version_file.write_text(version_tag)

        log(f"   ✅ Successfully installed IGIR {version_tag}")
        return True

    except Exception as e:  # noqa: BLE001
        import traceback
        print(f"   ❌ Error updating IGIR: {e}")
        print(f"   📋 Traceback: {traceback.format_exc()}")
        return False


def check_and_update_igir(
    igir_path: Path,
    version_override: Optional[str] = None,
    log_callback: Optional[Callable[[str], None]] = None
) -> Dict[str, object]:
    """
    Check and update IGIR, returning status information.
    Returns dict with 'error', 'message', 'success' keys.
    """
    result: Dict[str, object] = {'error': None, 'message': '', 'success': False}

    igir_exists = igir_path.exists()

    # Version override specified
    if version_override:
        target_version, download_url, asset_name = get_specific_igir_version(version_override)

        if not target_version or not download_url:
            result['error'] = f"IGIR version {version_override} not found on GitHub"
            result['message'] = f"Version {version_override} not available"
            return result

        current_version = get_current_igir_version(igir_path)

        # Check if we already have this version
        if igir_exists and current_version:
            target_clean = target_version.replace("v", "").strip()
            current_clean = current_version.replace("v", "").strip()
            if target_clean == current_clean:
                result['success'] = True
                result['message'] = f"Using IGIR version override: {version_override} - already installed"
                return result

        # Need to download/update
        if download_and_extract_igir(download_url, target_version, igir_path, asset_name, current_version, log_callback):
            result['success'] = True
            result['message'] = f"Using IGIR version override: {version_override} - downloaded"
            return result
        else:
            result['error'] = f"Failed to download IGIR version {version_override}"
            result['message'] = f"Download failed for {version_override}"
            return result

    # No override - use latest
    latest_version, download_url, asset_name = get_latest_igir_version()
    if not latest_version or not download_url:
        if igir_exists:
            result['success'] = True
            result['message'] = "Found (could not check for updates)"
            return result
        else:
            result['error'] = "Could not determine latest IGIR version and IGIR not found"
            result['message'] = "Version check failed"
            return result

    current_version = get_current_igir_version(igir_path)

    if igir_exists and current_version:
        latest_clean = latest_version.replace("v", "").strip()
        current_clean = current_version.replace("v", "").strip()

        if latest_clean == current_clean:
            result['success'] = True
            result['message'] = f"Found (v{current_version}) - up to date"
            return result
        else:
            # Update needed
            if download_and_extract_igir(download_url, latest_version, igir_path, asset_name, current_version, log_callback):
                result['success'] = True
                result['message'] = f"Updated to v{latest_version} (from v{current_version})"
                return result
            else:
                result['error'] = "Failed to update IGIR"
                result['message'] = "Update failed"
                return result
    elif igir_exists:
        # IGIR exists but we don't know the version - update to be safe
        if download_and_extract_igir(download_url, latest_version, igir_path, asset_name, None, log_callback):
            result['success'] = True
            result['message'] = f"Updated to v{latest_version}"
            return result
        else:
            result['error'] = "Failed to update IGIR"
            result['message'] = "Update failed"
            return result
    else:
        # No IGIR installed, install the latest
        if download_and_extract_igir(download_url, latest_version, igir_path, asset_name, None, log_callback):
            result['success'] = True
            result['message'] = f"Downloaded v{latest_version}"
            return result
        else:
            result['error'] = "Failed to download IGIR"
            result['message'] = "Download failed"
            return result


def run_igir_clean(igir_exe: Path, dat_file: Path, rom_dir: Path) -> bool:
    """Run IGIR clean to remove unrequired ROMs."""
    print("\n" + "=" * 70)
    print("🧹 Running IGIR Clean")
    print("=" * 70)

    # Create backup directory for cleaned files
    backup_dir = rom_dir / "NotRequired"
    backup_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(igir_exe),
        "link",  # IGIR clean must be combined with another command
        "clean",
        "--dat", str(dat_file),
        "--input", str(rom_dir),
        "--output", str(rom_dir),
        "--clean-backup", str(backup_dir),
    ]
    # IGIR doesn't support --yes flag, removed to prevent errors

    print(f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=SCRIPT_DIR)
        if result.returncode == 0:
            print("✅ IGIR clean completed successfully")
            return True
        print("❌ IGIR clean failed")
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        return False
    except Exception as e:  # noqa: BLE001
        print(f"❌ Error running IGIR clean: {e}")
        return False


def run_igir_report_and_get_missing_games(igir_exe: Path, dat_file: Path, rom_dir: Path) -> Optional[List[Dict[str, str]]]:
    """Run IGIR report to identify missing games."""
    print("\n" + "=" * 70)
    print("🔍 Running IGIR Report")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        csv_file = temp_path / "report.csv"

        cmd = [
            str(igir_exe),
            "report",
            "--dat", str(dat_file),
            "--input", str(rom_dir),
            "--report-output", str(csv_file),
        ]
        # IGIR doesn't support --yes flag, removed to prevent errors

        print(f"Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=SCRIPT_DIR)
            if result.returncode != 0:
                print("❌ IGIR report failed")
                print("STDOUT:", result.stdout)
                print("STDERR:", result.stderr)
                return None

            print("✅ IGIR report completed successfully")

            if not csv_file.exists():
                print("❌ IGIR report CSV not found")
                return None

            games: List[Dict[str, str]] = []
            with open(csv_file, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("Status") == "MISSING":
                        # Try different column names for game name
                        game_name = (
                            row.get("Game Name") or  # From IGIR CSV
                            row.get("Game") or       # Alternative
                            row.get("Name") or       # Alternative
                            ""                       # Fallback
                        ).strip()

                        if game_name:
                            games.append(
                                {
                                    "ROM": row.get("ROM Files", "") or "",  # IGIR uses "ROM Files"
                                    "Game": game_name,
                                    "Size": row.get("Size", "") or "",
                                }
                            )
            return games

        except Exception as e:  # noqa: BLE001
            print(f"❌ Error running IGIR report: {e}")
            return None


def _parse_myrient_listing_html(html: str, system_url: str) -> List[Dict[str, object]]:
    """Parse Myrient directory listing HTML into [{filename,url,size}]."""
    files: List[Dict[str, object]] = []

    # Preferred parser
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")  # type: ignore[misc]

        # First try to parse table structure (like old script)
        rows = soup.find_all("tr")
        if rows:
            for row in rows:
                # Find link in this row
                link = row.find("a")
                if not link:
                    continue

                href = link.get("href")
                if not href or href.startswith("?") or href.startswith("/"):
                    continue

                is_folder = href.endswith("/")
                filename = urllib.parse.unquote(href).strip().rstrip("/")
                if filename in (".", "..") or filename.startswith("../"):
                    continue

                # Look for size in table cells (files only; folders often show "-")
                size_bytes = 0
                if not is_folder:
                    cells = row.find_all("td")
                    for cell in cells:
                        cell_text = cell.get_text().strip()
                        m = re.match(r"^\s*([\d.]+)\s*([KMGT]?I?B)\s*$", cell_text, re.IGNORECASE)
                        if m:
                            num = float(m.group(1))
                            unit = m.group(2).upper()
                            if unit in SIZE_MULTIPLIERS:
                                size_bytes = int(num * SIZE_MULTIPLIERS[unit])
                                break

                full_url = system_url.rstrip("/") + "/" + href
                if is_folder and not full_url.endswith("/"):
                    full_url += "/"
                files.append(
                    {
                        "filename": filename,
                        "url": full_url,
                        "size": size_bytes,
                        "is_folder": is_folder,
                    }
                )
            return files

        # Fallback to link text parsing
        for link in soup.find_all("a"):
            href = link.get("href")
            if not href or href.startswith("?") or href.startswith("/"):
                continue

            is_folder = href.endswith("/")
            raw_name = urllib.parse.unquote(href).strip().rstrip("/")
            if raw_name in (".", "..") or raw_name.startswith("../"):
                continue
            # Many Myrient listings show "Filename - 25.3 MiB" as link text
            text = (link.get_text() or "").strip()
            filename = None
            size_str = None

            if " - " in text:
                parts = text.split(" - ")
                if len(parts) >= 2:
                    filename = parts[0].strip()
                    size_str = parts[1].strip()

            if not filename:
                filename = urllib.parse.unquote(href).strip().rstrip("/")

            size_bytes = 0
            if not is_folder and size_str:
                m = re.match(r"^\s*([\d.]+)\s*([KMG])iB\s*$", size_str)
                if m:
                    num = float(m.group(1))
                    unit = m.group(2)
                    mult = SIZE_MULTIPLIERS[unit]
                    size_bytes = int(num * mult)

            full_url = system_url.rstrip("/") + "/" + href
            if is_folder and not full_url.endswith("/"):
                full_url += "/"
            files.append(
                {
                    "filename": filename,
                    "url": full_url,
                    "size": size_bytes,
                    "is_folder": is_folder,
                }
            )
        return files

    # Fallback: regex-based parse with table support
    # First try to parse table rows
    for row_match in re.finditer(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE):
        row_html = row_match.group(1)

        # Find link in row
        link_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>', row_html, re.IGNORECASE)
        if not link_match:
            continue

        href = link_match.group(1)
        if not href or href.startswith("?") or href.startswith("/"):
            continue

        is_folder = href.endswith("/")
        filename = urllib.parse.unquote(href).strip().rstrip("/")
        if filename in (".", "..") or filename.startswith("../"):
            continue
        size_bytes = 0
        if not is_folder:
            for cell_match in re.finditer(r'<td[^>]*>([^<]+)</td>', row_html, re.IGNORECASE):
                cell_text = cell_match.group(1).strip()
                m = re.match(r"^\s*([\d.]+)\s*([KMGT]?I?B)\s*$", cell_text, re.IGNORECASE)
                if m:
                    num = float(m.group(1))
                    unit = m.group(2).upper()
                    if unit in SIZE_MULTIPLIERS:
                        size_bytes = int(num * SIZE_MULTIPLIERS[unit])
                        break
        full_url = system_url.rstrip("/") + "/" + href
        if is_folder and not full_url.endswith("/"):
            full_url += "/"
        files.append(
            {"filename": filename, "url": full_url, "size": size_bytes, "is_folder": is_folder}
        )

    if not files:
        for m in re.finditer(r'<a href="([^"]+)">([^<]+)</a>', html, flags=re.IGNORECASE):
            href = m.group(1)
            text = m.group(2).strip()
            if not href or href.startswith("?") or href.startswith("/"):
                continue

            is_folder = href.endswith("/")
            filename = None
            size_str = None
            if " - " in text:
                parts = text.split(" - ")
                if len(parts) >= 2:
                    filename = parts[0].strip()
                    size_str = parts[1].strip()
            if not filename:
                filename = urllib.parse.unquote(href).strip().rstrip("/")
            if filename in (".", "..") or filename.startswith("../"):
                continue

            size_bytes = 0
            if not is_folder and size_str:
                mm = re.match(r"^\s*([\d.]+)\s*([KMG])iB\s*$", size_str)
                if mm:
                    num = float(mm.group(1))
                    unit = mm.group(2)
                    mult = SIZE_MULTIPLIERS[unit]
                    size_bytes = int(num * mult)
            full_url = system_url.rstrip("/") + "/" + href
            if is_folder and not full_url.endswith("/"):
                full_url += "/"
            files.append(
                {"filename": filename, "url": full_url, "size": size_bytes, "is_folder": is_folder}
            )

    return files


def fetch_myrient_index(system_url: str) -> Tuple[Optional[List[Dict[str, object]]], Optional[str]]:
    """Download and parse Myrient directory listing.
    Returns (files, None) on success, or (None, error_type) on failure.
    error_type is '404', 'timeout', 'connection', 'http', or 'error' for other failures."""
    print("\n" + "=" * 70)
    print("🌐 Downloading Myrient directory metadata...")
    print("=" * 70)
    print(f"🔗 Fetching: {system_url}")

    try:
        resp = requests.get(system_url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        files = _parse_myrient_listing_html(resp.text, system_url)
        print(f"📁 Found {len(files)} entries (files + folders) in Myrient directory")
        return files, None
    except requests.Timeout:
        print(f"❌ Timeout fetching Myrient index: {system_url}")
        return None, "timeout"
    except requests.ConnectionError:
        print(f"❌ Connection error fetching Myrient index: {system_url}")
        return None, "connection"
    except requests.HTTPError as e:
        print(f"❌ HTTP error fetching Myrient index: {e}")
        if e.response is not None and e.response.status_code == 404:
            return None, "404"
        return None, "http"
    except Exception as e:  # noqa: BLE001
        print(f"❌ Unexpected error fetching Myrient index: {e}")
        return None, "error"


def fetch_folder_contents(
    folder_url: str,
) -> List[Dict[str, object]]:
    """Recursively list all files under a Myrient folder. Returns list of {relative_path, url, size}."""
    base = folder_url.rstrip("/") + "/"
    try:
        resp = requests.get(base, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"   ⚠️ Could not fetch folder {base}: {e}")
        return []
    listing = _parse_myrient_listing_html(resp.text, base)
    result: List[Dict[str, object]] = []
    for entry in listing:
        fn = str(entry.get("filename", "") or "").strip()
        if not fn or fn in (".", "..") or fn.startswith("../"):
            continue
        is_folder = entry.get("is_folder", False)
        url = str(entry.get("url", "") or "")
        size = int(entry.get("size", 0) or 0)
        if is_folder:
            subfiles = fetch_folder_contents(url)
            prefix = fn + "/"
            for sf in subfiles:
                result.append({
                    "relative_path": prefix + str(sf.get("relative_path", "")),
                    "url": sf.get("url", ""),
                    "size": int(sf.get("size", 0) or 0),
                })
        else:
            result.append({"relative_path": fn, "url": url, "size": size})
    return result


def enrich_matched_games_with_folder_sizes(
    matched_games: List[Dict[str, object]],
    log_callback: Optional[object] = None,
) -> None:
    """For each folder game, fetch contents, set File Size to sum of file sizes, and cache _folder_contents for download."""
    folder_games = [g for g in matched_games if g.get("is_folder")]
    if not folder_games:
        return
    if callable(log_callback):
        try:
            log_callback("Fetching folder sizes...")
        except Exception:  # noqa: BLE001
            pass
    for game in matched_games:
        if not game.get("is_folder"):
            continue
        url = str(game.get("Download URL", "") or "")
        if not url:
            continue
        try:
            contents = fetch_folder_contents(url)
            total = sum(int(c.get("size", 0) or 0) for c in contents)
            game["File Size"] = total
            game["_folder_contents"] = contents
        except Exception:  # noqa: BLE001
            game["File Size"] = 0
            game["_folder_contents"] = []


def standardize_game_entry(game: Dict[str, str]) -> Dict[str, str]:
    """Standardize game entry format for consistent processing."""
    # Unify key names and ensure consistent format
    game_name = (game.get("Game Name") or game.get("Game") or "").strip()
    rom_name = (game.get("ROM") or game.get("ROM Files") or game_name).strip()
    size = (game.get("Size") or "0").strip()

    return {
        "Game Name": game_name,  # Standardized key
        "ROM": rom_name,
        "Size": size
    }


def process_games_for_download(
    games: List[Dict[str, str]],
    myrient_index: List[Dict[str, object]],
) -> Optional[List[Dict[str, object]]]:
    """Process game list and match with Myrient files for download."""
    # Standardize all game entries first
    standardized_games = [standardize_game_entry(game) for game in games]
    return match_games_with_myrient(standardized_games, myrient_index)


def match_games_with_myrient(
    games: List[Dict[str, str]],
    myrient_index: List[Dict[str, object]],
) -> Optional[List[Dict[str, object]]]:
    """Match missing games with Myrient files (optimized lookup)."""

    if not myrient_index:
        print("❌ No Myrient index available")
        return None

    # Build lookup map: key = game name (stem). Accept any file type; folders = single entity.
    # Stem: for files strip any extension; for folders use name as-is. Prefer folder over file when both exist.
    index_map: Dict[str, Dict[str, object]] = {}

    for f in myrient_index:
        fn = str(f.get("filename", "") or "").strip()
        if not fn:
            continue
        is_folder = f.get("is_folder", False)
        stem = fn if is_folder else re.sub(r"\.[^.]+$", "", fn)
        if not stem:
            continue
        existing = index_map.get(stem)
        # Prefer folder (one entity with all contents) over a single file
        if existing is None or (is_folder and not existing.get("is_folder", False)):
            index_map[stem] = f

    matched_games: List[Dict[str, object]] = []

    for game in games:
        game_name = (game.get("Game Name") or "").strip()
        if not game_name:
            continue

        best = index_map.get(game_name)

        if best:
            matched_games.append(
                {
                    "Game Name": game_name,
                    "Myrient Filename": best.get("filename", ""),
                    "Download URL": best.get("url", ""),
                    "File Size": int(best.get("size", 0) or 0),
                    "Expected Filename": game.get("ROM", game_name),
                    "is_folder": best.get("is_folder", False),
                }
            )

    print(f"✅ Matched {len(matched_games)} out of {len(games)} missing games")
    return matched_games


def infer_myrient_url_from_dat(dat_path: Path, base_url: str) -> Optional[str]:
    """Infer Myrient URL from DAT filename (Fresh1G1R convention) or DAT header."""
    try:
        filename_stem = dat_path.stem

        # Method 1: Fresh1G1R bracket on filename end
        fresh1g1r_pattern = r" \(([^)]*Fresh1G1R[^)]*)\)$"
        m = re.search(fresh1g1r_pattern, filename_stem)
        if m:
            url_path = re.sub(fresh1g1r_pattern, "", filename_stem)
            bracket = m.group(1).lower()

            if "no-intro" in bracket or "no intro" in bracket:
                collection = COLLECTION_NO_INTRO
            elif "redump" in bracket:
                collection = COLLECTION_REDUMP
            else:
                return None

            encoded_path = urllib.parse.quote(url_path, safe="")
            return f"{base_url.rstrip('/')}/files/{collection}/{encoded_path}/"

        # Method 2: DAT header (XML)
        tree = ET.parse(dat_path)
        root = tree.getroot()
        header = root.find("header")
        if header is None:
            return None

        name_elem = header.find("name")
        if name_elem is None or not (name_elem.text or "").strip():
            return None

        system_name = (name_elem.text or "").strip()

        # RetroAchievements: identify by <homepage>https://retroachievements.org/</homepage>
        homepage_elem = header.find("homepage")
        if homepage_elem is not None and (homepage_elem.text or "").strip():
            homepage = (homepage_elem.text or "").strip()
            if "retroachievements.org" in homepage:
                encoded_name = urllib.parse.quote(system_name, safe="")
                return f"{base_url.rstrip('/')}/files/{COLLECTION_RETRO_ACHIEVEMENTS}/{encoded_name}/"

        url_elem = header.find("url")
        if url_elem is None or not (url_elem.text or "").strip():
            return None

        dat_url = (url_elem.text or "").strip().lower()

        if "redump.org" in dat_url:
            collection = COLLECTION_REDUMP
            clean_system = extract_system_name(system_name, "redump")
        elif "no-intro.org" in dat_url or "no-intro" in dat_url:
            collection = COLLECTION_NO_INTRO
            clean_system = extract_system_name(system_name, "no-intro")
        else:
            return None

        encoded_system = urllib.parse.quote(clean_system, safe="")
        return f"{base_url.rstrip('/')}/files/{collection}/{encoded_system}/"

    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️  Could not infer Myrient URL from DAT: {e}")
        return None


def is_retroachievements_dat(dat_path: Path) -> bool:
    """Return True if the DAT file is a RetroAchievements DAT (by homepage in header)."""
    if not dat_path.exists() or not dat_path.is_file():
        return False
    try:
        tree = ET.parse(dat_path)
        root = tree.getroot()
        header = root.find("header")
        if header is None:
            return False
        homepage_elem = header.find("homepage")
        if homepage_elem is None or not (homepage_elem.text or "").strip():
            return False
        homepage = (homepage_elem.text or "").strip()
        return "retroachievements.org" in homepage
    except Exception:  # noqa: BLE001
        return False


def dat_has_clones(dat_path: Path) -> bool:
    """Return True if the DAT has any game/machine with a cloneof attribute (parent/clone relationship)."""
    if not dat_path.exists() or not dat_path.is_file():
        return False
    try:
        tree = ET.parse(dat_path)
        root = tree.getroot()
        for tag in ("game", "machine"):
            for elem in root.findall(f".//{tag}"):
                if (elem.get("cloneof") or "").strip():
                    return True
        return False
    except Exception:  # noqa: BLE001
        return False


def parse_fixdat(
    fixdat_path: Path,
    original_dat_path: Optional[Path] = None,
    include_clones: bool = True,
) -> Optional[List[Dict[str, str]]]:
    """Parse a fixdat (DAT file) and extract game names. If include_clones is False, skip entries with cloneof."""
    _ = original_dat_path  # reserved for future use / debug
    print(f"\n📄 Parsing fixdat: {fixdat_path}")
    if not include_clones:
        print("   ℹ️  Excluding clones (1G1R) — only parent entries will be included.")

    try:
        tree = ET.parse(fixdat_path)
        root = tree.getroot()
    except ET.ParseError as e:
        print(f"❌ Error parsing DAT XML: {e}")
        return None
    except FileNotFoundError:
        print(f"❌ DAT file not found: {fixdat_path}")
        return None
    except PermissionError:
        print(f"❌ Permission denied reading DAT file: {fixdat_path}")
        return None

    # Handle XML namespaces - if the root has a default namespace, we need to register it
    ns = {}
    if root.tag.startswith('{'):
        # Extract namespace URI from root tag
        ns_uri = root.tag.split('}')[0].strip('{')
        ns[''] = ns_uri  # Default namespace
    else:
        pass  # No XML namespace detected

    games: List[Dict[str, str]] = []

    # Try with namespace-aware search first, then fallback to regular search
    game_elements = root.findall(".//game", ns) if ns else root.findall(".//game")
    is_retroachievements_format = False

    if not game_elements:
        # Try without namespace
        if ns:
            game_elements = root.findall(".//game")
        if not game_elements:
            # RetroAchievements DATs use <machine> instead of <game>, and <disk> instead of <rom>
            game_elements = root.findall(".//machine", ns) if ns else root.findall(".//machine")
            if ns and not game_elements:
                game_elements = root.findall(".//machine")
            is_retroachievements_format = bool(game_elements)
        if not game_elements:
            for child in root:
                if child.tag.endswith('game') or 'game' in child.tag.lower():
                    game_elements = [child] + list(root.findall(".//*[local-name()='game']"))
                    break

    for game_elem in game_elements:
        # Skip clones when user chose 1G1R (parents only)
        if not include_clones and (game_elem.get("cloneof") or "").strip():
            continue
        if is_retroachievements_format:
            # RetroAchievements: <machine name="Game Name"> with <disk name="file.chd"/> or <rom name="..." size="..."/>
            game_name = (game_elem.get("name") or "").strip()
            if not game_name:
                desc_elem = game_elem.find("description", ns) if ns else game_elem.find("description")
                if desc_elem is not None and (desc_elem.text or "").strip():
                    game_name = (desc_elem.text or "").strip()
            if not game_name:
                continue
            # Prefer <disk> then <rom> (RA DATs often use <disk> for CHD etc.)
            rom_elem = game_elem.find("disk", ns) if ns else game_elem.find("disk")
            if rom_elem is None:
                rom_elem = game_elem.find("rom", ns) if ns else game_elem.find("rom")
            if rom_elem is None:
                continue
            rom_name = (rom_elem.get("name") or "").strip() or game_name
            rom_size = rom_elem.get("size") or "0"
        else:
            # Standard DAT: <game> with <description> and <rom>
            desc_elem = game_elem.find("description", ns) if ns else game_elem.find("description")
            if desc_elem is None and ns:
                desc_elem = game_elem.find("description")
            if desc_elem is None:
                for alt_name in ["description", "{*}description"]:
                    desc_elem = game_elem.find(alt_name, ns) if ns else game_elem.find(alt_name)
                    if desc_elem is not None:
                        break
            if desc_elem is None or not (desc_elem.text or "").strip():
                continue
            game_name = (desc_elem.text or "").strip()
            rom_elem = game_elem.find("rom", ns) if ns else game_elem.find("rom")
            if rom_elem is None and ns:
                rom_elem = game_elem.find("rom")
            if rom_elem is None:
                continue
            rom_name = rom_elem.get("name") or game_name
            rom_size = rom_elem.get("size") or "0"

        games.append({"Game Name": game_name, "ROM": rom_name, "Size": rom_size})

    print(f"📋 Found {len(games)} games in fixdat")
    return games


def download_missing_games(matched_games: List[Dict[str, object]], downloads_dir: Path | str) -> None:
    """Download matched games from Myrient (CLI mode)."""
    print("\n" + "=" * 70)
    print("⬇️  Downloading Missing Games")
    print("=" * 70)

    if not matched_games:
        print("❌ No games to download")
        return

    enrich_matched_games_with_folder_sizes(matched_games)
    total_games = len(matched_games)
    total_size = sum(int(g.get("File Size", 0) or 0) for g in matched_games)
    print(f"📥 Downloading {total_games:,} games ({format_size(total_size)})")

    downloads_dir, _ = ensure_directory_exists(downloads_dir, create_if_missing=True)

    successful = 0
    failed = 0
    total_downloaded = 0
    start_time = time.time()

    for i, game in enumerate(matched_games, 1):
        game_name = str(game.get("Game Name", ""))
        url = str(game.get("Download URL", ""))
        file_size = int(game.get("File Size", 0) or 0)
        myrient_filename = str(game.get("Myrient Filename") or game.get("Expected Filename") or "")
        is_folder = game.get("is_folder", False)

        if is_folder:
            folder_name = myrient_filename or (urllib.parse.unquote(url.rstrip("/").split("/")[-1]) if url else f"download_{i}")
            output_dir = downloads_dir / folder_name
            print(f"[{i}/{total_games}] {game_name} (folder)")
            try:
                contents = game.get("_folder_contents") or fetch_folder_contents(url)
                folder_ok = True
                for item in contents:
                    rel = str(item.get("relative_path", ""))
                    file_url = str(item.get("url", ""))
                    size = int(item.get("size", 0) or 0)
                    out_path = output_dir / rel
                    if out_path.exists():
                        total_downloaded += size
                        continue
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    ok, n, _ = download_file(file_url, out_path, size)
                    if ok:
                        total_downloaded += n
                    else:
                        folder_ok = False
                if folder_ok:
                    successful += 1
                    print(f"✅ [{i}/{total_games}] {game_name} (folder) - {len(contents)} file(s)")
                else:
                    failed += 1
                    print(f"❌ [{i}/{total_games}] {game_name} - Some files failed")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"❌ [{i}/{total_games}] {game_name} - Error: {e}")
            continue

        filename = myrient_filename or (urllib.parse.unquote(url.split("/")[-1]).rstrip("/") if url else "") or f"download_{i}"
        output_path = downloads_dir / filename

        if output_path.exists():
            print(f"⏭️  [{i}/{total_games}] {game_name} - Already exists, skipping")
            successful += 1
            continue

        print(f"[{i}/{total_games}] {game_name} ({format_size(file_size)})")

        try:
            success, downloaded_bytes, elapsed = download_file(url, output_path, file_size)
            if success:
                successful += 1
                total_downloaded += downloaded_bytes
                print(f"✅ [{i}/{total_games}] {game_name} - {format_size(downloaded_bytes)} in {elapsed:.1f}s")
            else:
                failed += 1
                print(f"❌ [{i}/{total_games}] {game_name} - Failed")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"❌ [{i}/{total_games}] {game_name} - Error: {e}")

    total_elapsed = time.time() - start_time
    avg_rate = total_downloaded / total_elapsed if total_elapsed > 0 else 0.0

    print("\n" + "=" * 70)
    print("📊 Download Summary")
    print("=" * 70)
    print(f"   ✅ Successful: {successful:,}/{total_games:,}")
    print(f"   ❌ Failed: {failed:,}/{total_games:,}")
    print(f"   📦 Total downloaded: {format_size(total_downloaded)}")
    print(f"   ⏱️  Time elapsed: {format_time(total_elapsed)}")
    print(f"   🚀 Average speed: {format_speed(avg_rate)}")
    print("=" * 70)


# ============================================================================
# GUI CLASSES
# ============================================================================

class LogEmitter(QtCore.QObject):
    """Emit log messages into the GUI thread."""
    log_signal = QtCore.pyqtSignal(str)

    def write(self, text: str) -> None:
        text = str(text)
        if text:
            self.log_signal.emit(text.rstrip("\n"))

    def flush(self) -> None:
        pass


class CustomCheckBox(QtWidgets.QCheckBox):
    """Custom checkbox that properly shows white checkmarks."""

    def paintEvent(self, event):  # type: ignore[override]
        super().paintEvent(event)

        if self.isChecked():
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setPen(
                QtGui.QPen(
                    QtCore.Qt.white, 2, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin
                )
            )

            style = self.style()
            option = QtWidgets.QStyleOptionButton()
            self.initStyleOption(option)
            indicator_rect = style.subElementRect(QtWidgets.QStyle.SE_CheckBoxIndicator, option, self)

            cx = indicator_rect.x() + indicator_rect.width() // 2
            cy = indicator_rect.y() + indicator_rect.height() // 2

            offset = 4
            x1, y1 = cx - offset, cy - 1
            x2, y2 = cx - 1, cy + offset
            x3, y3 = cx + offset, cy - offset

            painter.drawLine(x1, y1, x2, y2)
            painter.drawLine(x2, y2, x3, y3)
            painter.end()


class _MyrientOverrideReceiver(QtCore.QObject):
    """Lives in worker thread; receives override URL from main window and quits the worker's event loop."""

    @QtCore.pyqtSlot(str)
    def set_override_url(self, url: str) -> None:
        if hasattr(self, "_worker") and hasattr(self, "_event_loop"):
            self._worker._override_url_result = url  # type: ignore[attr-defined]
            self._event_loop.quit()


class DownloadWorker(QtCore.QThread):
    """Runs the full workflow for the Qt GUI."""

    progress_signal = QtCore.pyqtSignal(object, object, str, str, str, str)  # overall, current_file, text, speed, total_size, eta
    status_signal = QtCore.pyqtSignal(str)
    finished_signal = QtCore.pyqtSignal()
    error_signal = QtCore.pyqtSignal(str)
    log_signal = QtCore.pyqtSignal(str)
    request_myrient_url_override = QtCore.pyqtSignal(str)  # emitted on 404; main window shows dialog and emits result back

    def __init__(self, config_snapshot: dict, use_igir: bool, parent=None) -> None:
        super().__init__(parent)
        self._config = dict(config_snapshot)
        self._use_igir = bool(use_igir)
        self._stop_requested = False
        self._current_file_progress = ""
        # Speed averaging for stable ETA calculation
        self._speed_history: List[float] = []
        self._max_speed_samples = 10  # Keep last 10 speed measurements

    def request_stop(self) -> None:
        self._stop_requested = True

    def _emit_log_lines(self, text: str) -> None:
        if not text:
            return
        for line in text.split("\n"):
            if line.strip():
                self.log_signal.emit(line)

    def _log_header(self) -> None:
        """Log the application header."""
        self.log_signal.emit("=" * 70)
        self.log_signal.emit("🎮 Myrient Can FixDAT 🎮")
        self.log_signal.emit("=" * 70)

    def _setup_fixdat_config(self) -> Tuple[bool, Optional[Path]]:
        """Set up fixdat configuration based on user selection."""
        if self._use_igir:
            # Use IGIR to compare ROM directory against DAT
            return check_fixdat_setup()
        else:
            # Skip IGIR - use DAT file directly as fixdat
            manual_fixdat = resolve_path(CONFIG.list_dat)
            self.log_signal.emit("ℹ️  Using DAT file directly (skipping IGIR processing)")
            return True, manual_fixdat

    def _validate_configuration(self, has_manual_fixdat: bool, manual_fixdat: Optional[Path]) -> Tuple[bool, Optional[str]]:
        """Validate configuration and return (valid, myrient_url)."""
        import contextlib
        import io

        self.log_signal.emit("\n⚙️  Validating configuration...")

        original_auto = CONFIG.auto_config_yes
        CONFIG.auto_config_yes = True

        require_igir = self._use_igir or CONFIG.clean_roms
        stdout_capture = io.StringIO()
        with contextlib.redirect_stdout(stdout_capture):
            config_valid, myrient_url = validate_config(has_manual_fixdat, manual_fixdat, require_igir=require_igir)

        CONFIG.auto_config_yes = original_auto
        self._emit_log_lines(stdout_capture.getvalue())

        if not config_valid:
            self.error_signal.emit(ERROR_CONFIG_VALIDATION)
            return False, None
        if not myrient_url:
            self.error_signal.emit(ERROR_MYRIENT_URL_MISSING)
            return False, None

        self.log_signal.emit(f"✅ Using Myrient URL: {myrient_url}")
        self.progress_signal.emit(CONFIG_VALIDATION_PROGRESS, 0.0, "Configuration validated", "", "", "")
        return True, myrient_url

    def _ensure_igir_available(self) -> bool:
        """Ensure IGIR is available (download if missing). Returns True if ready."""
        # Only need IGIR if use_igir is enabled or clean_roms is enabled
        if not self._use_igir and not CONFIG.clean_roms:
            return True

        self.log_signal.emit("\n🔧 Checking IGIR...")
        self.status_signal.emit("Checking IGIR...")

        igir_path = resolve_path(CONFIG.igir_exe)
        version_override = CONFIG.igir_version_override if hasattr(CONFIG, 'igir_version_override') else None

        # Pass log_signal.emit directly for real-time logging
        result = check_and_update_igir(igir_path, version_override, self.log_signal.emit)

        if result.get('success'):
            self.log_signal.emit(f"   ✅ IGIR: {result.get('message', 'Ready')}")
            return True
        else:
            error_msg = result.get('error') or result.get('message') or 'IGIR not available'
            self.error_signal.emit(f"IGIR Error: {error_msg}")
            return False

    def _perform_rom_cleaning(self) -> bool:
        """Perform ROM cleaning if enabled. Returns True if successful or skipped."""
        import contextlib
        import io

        if not CONFIG.clean_roms:
            return True

        self.log_signal.emit("\n🧹 Cleaning ROMs directory...")
        self.status_signal.emit("Cleaning ROMs...")

        igir_exe = resolve_path(CONFIG.igir_exe)
        rom_dir = resolve_path(CONFIG.roms_directory)
        dat_file = resolve_path(CONFIG.list_dat)

        if not (igir_exe.exists() and dat_file.exists() and rom_dir.exists()):
            self.error_signal.emit("Required files/directories not found for cleaning.")
            return False

        stdout_capture = io.StringIO()
        with contextlib.redirect_stdout(stdout_capture):
            ok = run_igir_clean(igir_exe, dat_file, rom_dir)
        self._emit_log_lines(stdout_capture.getvalue())

        if not ok:
            self.error_signal.emit(ERROR_IGIR_CLEAN_FAILED)
            return False

        self.progress_signal.emit(CLEAN_COMPLETE_PROGRESS, 0.0, "ROMs cleaned", "", "", "")
        return True

    def _identify_missing_games(self, has_manual_fixdat: bool, manual_fixdat: Optional[Path]) -> Optional[List[Dict[str, str]]]:
        """Identify missing games and return the list."""
        import contextlib
        import io

        self.log_signal.emit("\n🔍 Identifying missing games...")
        self.status_signal.emit("Identifying missing games...")

        if not has_manual_fixdat:
            igir_exe = resolve_path(CONFIG.igir_exe)
            dat_file = resolve_path(CONFIG.list_dat)
            rom_dir = resolve_path(CONFIG.roms_directory)

            stdout_capture = io.StringIO()
            with contextlib.redirect_stdout(stdout_capture):
                games = run_igir_report_and_get_missing_games(igir_exe, dat_file, rom_dir)
            self._emit_log_lines(stdout_capture.getvalue())

            if not games:
                self.status_signal.emit("Collection is complete!")
                return None
        else:
            self.log_signal.emit("\n📄 Parsing fixdat...")
            original_dat = resolve_path(CONFIG.list_dat) if self._use_igir else None

            include_clones = getattr(CONFIG, "include_clones", True)
            stdout_capture = io.StringIO()
            with contextlib.redirect_stdout(stdout_capture):
                games = parse_fixdat(
                    manual_fixdat or resolve_path(CONFIG.list_dat),
                    original_dat,
                    include_clones=include_clones,
                )
            self._emit_log_lines(stdout_capture.getvalue())

            if not games:
                self.error_signal.emit(ERROR_MISSING_FIXDAT)
                return None

        self.progress_signal.emit(MISSING_GAMES_FOUND_PROGRESS, 0.0, f"Found {len(games):,} missing games", "", "", "")
        return games

    def _fetch_myrient_index(self, myrient_url: str) -> Optional[List[Dict[str, object]]]:
        """Fetch Myrient index and return it. On 404, ask user for full Myrient URL and retry."""
        import contextlib
        import io

        self.log_signal.emit("\n🌐 Downloading Myrient metadata...")
        self.status_signal.emit("Fetching Myrient index...")

        stdout_capture = io.StringIO()
        with contextlib.redirect_stdout(stdout_capture):
            myrient_index, error_type = fetch_myrient_index(myrient_url)
        self._emit_log_lines(stdout_capture.getvalue())

        if error_type == "404":
            main_win = self.parent()
            if main_win is not None and hasattr(main_win, "myrient_override_result_signal"):
                event_loop = QtCore.QEventLoop()
                self._override_url_result = None  # type: ignore[attr-defined]
                receiver = _MyrientOverrideReceiver(self)
                receiver._worker = self  # type: ignore[attr-defined]
                receiver._event_loop = event_loop  # type: ignore[attr-defined]
                main_win.myrient_override_result_signal.connect(receiver.set_override_url)
                self.request_myrient_url_override.emit(myrient_url)
                event_loop.exec_()
                main_win.myrient_override_result_signal.disconnect(receiver.set_override_url)
                override_url = (self._override_url_result or "").strip()  # type: ignore[attr-defined]
                if override_url:
                    self.log_signal.emit("\n🔄 Retrying with user-provided URL...")
                    stdout_capture = io.StringIO()
                    with contextlib.redirect_stdout(stdout_capture):
                        myrient_index, error_type = fetch_myrient_index(override_url)
                    self._emit_log_lines(stdout_capture.getvalue())

        if not myrient_index:
            self.error_signal.emit(ERROR_MYRIENT_INDEX_FAILED)
            return None

        self.progress_signal.emit(MYRIENT_INDEX_DOWNLOADED_PROGRESS, 0.0, "Myrient index downloaded", "", "", "")
        return myrient_index

    def _match_games_with_myrient(self, games: List[Dict[str, str]], myrient_index: List[Dict[str, object]]) -> Optional[List[Dict[str, object]]]:
        """Match games with Myrient index and return matched games."""
        import contextlib
        import io

        self.log_signal.emit("\n🔗 Matching games with Myrient files...")
        self.status_signal.emit("Matching games...")

        stdout_capture = io.StringIO()
        with contextlib.redirect_stdout(stdout_capture):
            matched_games = process_games_for_download(games, myrient_index)
        self._emit_log_lines(stdout_capture.getvalue())

        if not matched_games:
            self.status_signal.emit("No matches found")
            return None

        self.log_signal.emit("Computing total size (folder contents)...")
        enrich_matched_games_with_folder_sizes(matched_games, log_callback=lambda msg: self.log_signal.emit(msg))
        total_size = sum(int(g.get("File Size", 0) or 0) for g in matched_games)
        self.log_signal.emit("\n📊 Summary:")
        self.log_signal.emit(f"   📋 Total missing: {len(games):,}")
        self.log_signal.emit(f"   ✅ Available: {len(matched_games):,}")
        self.log_signal.emit(f"   📦 Total size: {format_size(total_size)}")

        self.progress_signal.emit(MATCHED_GAMES_PROGRESS, 0.0, f"Matched {len(matched_games):,} games", "", "", "")
        return matched_games

    def _download_matched_games(self, matched_games: List[Dict[str, object]]) -> None:
        """Download the matched games."""
        self.log_signal.emit("\n⬇️  Starting downloads...")
        self.status_signal.emit("Downloading...")

        downloads_dir = resolve_path(CONFIG.downloads_directory)
        self._download_with_gui_updates(matched_games, downloads_dir)

    def _log_completion(self) -> None:
        """Log successful completion."""
        self.log_signal.emit("\n✅ All operations completed!")
        self.status_signal.emit("Completed successfully")
        self.progress_signal.emit(DOWNLOAD_COMPLETE_PROGRESS, 0.0, "Complete", "", "", "")

    def _download_with_gui_updates(self, matched_games: List[Dict[str, object]], download_dir: Path) -> None:
        total_games = len(matched_games)
        # Folder sizes were set by enrich_matched_games_with_folder_sizes in _match_games_with_myrient
        total_size = sum(int(g.get("File Size", 0) or 0) for g in matched_games)

        self.log_signal.emit(f"📥 Downloading {total_games:,} games ({format_size(total_size)})")
        download_dir.mkdir(parents=True, exist_ok=True)

        successful = 0
        failed = 0
        total_downloaded = 0
        start_time = time.time()

        for i, game in enumerate(matched_games, 1):
            if self._stop_requested or self.isInterruptionRequested():
                self.log_signal.emit(f"\n{ERROR_STOP_REQUESTED}")
                break

            game_name = str(game.get("Game Name", ""))
            url = str(game.get("Download URL", ""))
            file_size = int(game.get("File Size", 0) or 0)
            myrient_filename = str(game.get("Myrient Filename") or game.get("Expected Filename") or "")
            is_folder = game.get("is_folder", False)

            if is_folder:
                folder_name = myrient_filename or (urllib.parse.unquote(url.rstrip("/").split("/")[-1]) if url else f"download_{i}")
                output_dir = download_dir / folder_name
                self.log_signal.emit(f"[{i}/{total_games}] {game_name} (folder)")
                try:
                    contents = game.get("_folder_contents") or fetch_folder_contents(url)
                    num_files = len(contents)
                    folder_ok = True
                    for j, item in enumerate(contents):
                        if self._stop_requested or self.isInterruptionRequested():
                            self.log_signal.emit(f"\n{ERROR_STOP_REQUESTED}")
                            break
                        rel = str(item.get("relative_path", ""))
                        file_url = str(item.get("url", ""))
                        size = int(item.get("size", 0) or 0)
                        out_path = output_dir / rel
                        if out_path.exists():
                            total_downloaded += size
                            continue
                        out_path.parent.mkdir(parents=True, exist_ok=True)

                        self._current_file_progress = f"0 B / {format_size(size)}"
                        overall_start = DOWNLOAD_START_PROGRESS + ((i - 1 + j / max(num_files, 1)) / max(total_games, 1)) * (DOWNLOAD_COMPLETE_PROGRESS - DOWNLOAD_START_PROGRESS)
                        self.progress_signal.emit(overall_start, 0.0, f"Downloading {i}/{total_games}: {game_name[:40]} (file {j + 1}/{num_files})", "", "", "")

                        def folder_progress_cb(downloaded: int, total: int, rate: float, elapsed: float, _j: int = j, _n: int = num_files) -> None:
                            if total <= 0:
                                return
                            file_progress = downloaded / total
                            overall_progress = DOWNLOAD_START_PROGRESS + ((i - 1 + (_j + file_progress) / max(_n, 1)) / max(total_games, 1)) * (DOWNLOAD_COMPLETE_PROGRESS - DOWNLOAD_START_PROGRESS)
                            if rate > 0:
                                self._speed_history.append(rate)
                                if len(self._speed_history) > self._max_speed_samples:
                                    self._speed_history.pop(0)
                            avg_rate = sum(self._speed_history) / len(self._speed_history) if self._speed_history else rate
                            total_so_far = total_downloaded + downloaded
                            total_size_text = f"{format_size(total_so_far)} / {format_size(total_size)}"
                            eta_text = "--"
                            if avg_rate > 0:
                                remaining_bytes = total_size - total_so_far
                                if remaining_bytes > 0:
                                    eta_text = format_time(remaining_bytes / avg_rate)
                            self._current_file_progress = f"{format_size(downloaded)} / {format_size(total)}"
                            self.progress_signal.emit(overall_progress, (downloaded / total) * 100.0, "", format_speed(avg_rate), total_size_text, eta_text)

                        ok, n, _ = download_file(file_url, out_path, size, progress_callback=folder_progress_cb)
                        if ok:
                            total_downloaded += n
                        else:
                            folder_ok = False
                    if self._stop_requested or self.isInterruptionRequested():
                        break
                    if folder_ok:
                        successful += 1
                        self.log_signal.emit(f"✅ [{i}/{total_games}] {game_name} (folder) - {num_files} file(s)")
                    else:
                        failed += 1
                        self.log_signal.emit(f"❌ [{i}/{total_games}] {game_name} - Some files failed")
                except Exception:  # noqa: BLE001
                    failed += 1
                self.progress_signal.emit(None, 0.0, "", "", "", "")
                continue

            filename = myrient_filename or (urllib.parse.unquote(url.split("/")[-1]).rstrip("/") if url else "") or f"download_{i}"
            output_path = download_dir / filename

            if output_path.exists():
                self.log_signal.emit(f"⏭️  [{i}/{total_games}] {game_name} - Already exists, skipping")
                successful += 1
                total_downloaded += file_size
                continue

            self.progress_signal.emit(0.0, 0.0, "", "", "", "")

            def progress_cb(downloaded: int, total: int, rate: float, elapsed: float) -> None:
                if total <= 0:
                    return
                file_progress = downloaded / total
                current_percent = file_progress * 100.0
                overall_progress = DOWNLOAD_START_PROGRESS + ((i - 1 + file_progress) / max(total_games, 1)) * (DOWNLOAD_COMPLETE_PROGRESS - DOWNLOAD_START_PROGRESS)
                if rate > 0:
                    self._speed_history.append(rate)
                    if len(self._speed_history) > self._max_speed_samples:
                        self._speed_history.pop(0)
                avg_rate = sum(self._speed_history) / len(self._speed_history) if self._speed_history else rate
                total_downloaded_so_far = total_downloaded + downloaded
                total_size_text = f"{format_size(total_downloaded_so_far)} / {format_size(total_size)}"
                eta_text = "--"
                if avg_rate > 0:
                    remaining_bytes = total_size - total_downloaded_so_far
                    if remaining_bytes > 0:
                        eta_text = format_time(remaining_bytes / avg_rate)
                self._current_file_progress = f"{format_size(downloaded)} / {format_size(total)}"
                self.progress_signal.emit(overall_progress, current_percent, "", format_speed(avg_rate), total_size_text, eta_text)

            overall_progress = DOWNLOAD_START_PROGRESS + (i / max(total_games, 1)) * (DOWNLOAD_COMPLETE_PROGRESS - DOWNLOAD_START_PROGRESS)
            self._current_file_progress = f"0 B / {format_size(file_size)}"
            self.progress_signal.emit(overall_progress, 0.0, f"Downloading {i}/{total_games}: {game_name[:40]}", "", "", "")
            self.log_signal.emit(f"[{i}/{total_games}] {game_name} ({format_size(file_size)})")

            try:
                success, downloaded_bytes, elapsed = download_file(
                    url,
                    output_path,
                    expected_size=file_size,
                    progress_callback=progress_cb,
                )

                if self._stop_requested or self.isInterruptionRequested():
                    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
                    try:
                        if tmp.exists():
                            tmp.unlink()
                    except Exception:  # noqa: BLE001
                        pass
                    self.log_signal.emit(f"\n{ERROR_STOP_REQUESTED}")
                    break

                self.progress_signal.emit(None, 0.0, "", "", "", "")

                if success:
                    successful += 1
                    total_downloaded += downloaded_bytes
                    self.progress_signal.emit(
                        DOWNLOAD_START_PROGRESS + (i / max(total_games, 1)) * (DOWNLOAD_COMPLETE_PROGRESS - DOWNLOAD_START_PROGRESS),
                        0.0,
                        f"Completed {i}/{total_games}: {game_name[:40]}",
                        "", "", ""
                    )
                    self.log_signal.emit(
                        f"✅ [{i}/{total_games}] {game_name} - {format_size(downloaded_bytes)} in {elapsed:.1f}s"
                    )
                else:
                    failed += 1
                    self.log_signal.emit(f"❌ [{i}/{total_games}] {game_name} - Failed")

            except Exception as e:  # noqa: BLE001
                if self._stop_requested or self.isInterruptionRequested():
                    self.log_signal.emit(f"\n{ERROR_STOP_REQUESTED}")
                    break
                failed += 1
                self.log_signal.emit(f"❌ [{i}/{total_games}] {game_name} - Error: {e}")

        total_elapsed = time.time() - start_time
        avg_rate = total_downloaded / total_elapsed if total_elapsed > 0 else 0.0

        self.progress_signal.emit(None, 0.0, "", "", "", "")

        self.log_signal.emit("\n" + "=" * 70)
        self.log_signal.emit("📊 Download Summary")
        self.log_signal.emit("=" * 70)
        self.log_signal.emit(f"   ✅ Successful: {successful:,}/{total_games:,}")
        self.log_signal.emit(f"   ❌ Failed: {failed:,}/{total_games:,}")
        self.log_signal.emit(
            f"   📦 Total downloaded: {format_size(total_downloaded)}/{format_size(total_size)}"
        )
        self.log_signal.emit(f"   ⏱️  Time elapsed: {format_time(total_elapsed)}")
        self.log_signal.emit(f"   🚀 Average speed: {format_speed(avg_rate)}")
        self.log_signal.emit("=" * 70)

    def run(self) -> None:
        """Main workflow execution."""
        import traceback

        try:
            CONFIG.update_from_dict(self._config)

            self._log_header()
            self.status_signal.emit("Starting...")

            # Phase 1: Setup fixdat config
            has_manual_fixdat, manual_fixdat = self._setup_fixdat_config()

            # Phase 1.5: Ensure IGIR is available BEFORE validation (if needed)
            if not self._ensure_igir_available():
                return

            # Phase 2: Validate configuration (now IGIR should exist if needed)
            config_valid, myrient_url = self._validate_configuration(has_manual_fixdat, manual_fixdat)

            if not config_valid or not myrient_url:
                return

            # Phase 3: Clean ROMs (optional)
            if not self._perform_rom_cleaning():
                return

            # Phase 4: Identify missing games
            games = self._identify_missing_games(has_manual_fixdat, manual_fixdat)
            if not games:
                return

            # Phase 5: Fetch and match with Myrient
            myrient_index = self._fetch_myrient_index(myrient_url)
            if not myrient_index:
                return

            matched_games = self._match_games_with_myrient(games, myrient_index)
            if not matched_games:
                return

            # Phase 6: Download matched games
            self._download_matched_games(matched_games)

            self._log_completion()

        except Exception as e:  # noqa: BLE001
            self.error_signal.emit(f"Error: {e}\n{traceback.format_exc()}")
        finally:
            self.finished_signal.emit()


class MainWindow(QtWidgets.QMainWindow):
    myrient_override_result_signal = QtCore.pyqtSignal(str)  # emitted with override URL when user provides it (from 404 dialog)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Myrient Can FixDAT")
        self.resize(WINDOW_MIN_WIDTH, WINDOW_HEIGHT)
        self.setMinimumWidth(WINDOW_MIN_WIDTH)

        # Native window chrome (TitleBar removed per Phase 1 migration)
        self._apply_dark_theme()

        self.worker: Optional[QtCore.QThread] = None
        self._stop_requested_once = False
        self._last_eta = ""
        self._myrient_url_cache: Dict[str, bool] = {}  # Cache for URL validation results
        # QNetworkAccessManager performs HEAD requests asynchronously, so URL
        # validation no longer freezes the GUI thread on unreachable hosts.
        self._qnam = QtNetwork.QNetworkAccessManager(self)
        self._pending_myrient_url: str = ""  # URL of the in-flight HEAD; used to drop stale responses

        central = QtWidgets.QWidget(self)
        self.setCentralWidget(central)

        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # Initialize UI elements
        self.dat_edit = QtWidgets.QLineEdit()
        self.roms_edit = QtWidgets.QLineEdit()
        self.downloads_edit = QtWidgets.QLineEdit()
        self.myrient_edit = QtWidgets.QLineEdit()

        max_edit_width = 1000
        for edit in (self.dat_edit, self.roms_edit, self.downloads_edit, self.myrient_edit):
            edit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            edit.setMaximumWidth(max_edit_width)

        self.dat_status = QtWidgets.QLabel("")
        self.roms_status = QtWidgets.QLabel("")
        self.downloads_status = QtWidgets.QLabel("")
        self.myrient_status = QtWidgets.QLabel("")
        for lbl in (self.dat_status, self.roms_status, self.downloads_status, self.myrient_status):
            lbl.setFixedWidth(STATUS_INDICATOR_WIDTH)
            lbl.setAlignment(QtCore.Qt.AlignCenter)

        paths_group = QtWidgets.QGroupBox("Paths")
        paths_layout = QtWidgets.QGridLayout(paths_group)
        paths_layout.setColumnStretch(1, 1)
        row = 0

        dat_label = QtWidgets.QLabel("DAT File")
        f = dat_label.font()
        f.setBold(True)
        dat_label.setFont(f)

        dat_subtitle = QtWidgets.QLabel("(with the collection you want)")
        dat_subtitle.setStyleSheet("color: gray; font-size: 10px;")

        dat_label_layout = QtWidgets.QVBoxLayout()
        dat_label_layout.addWidget(dat_label)
        dat_label_layout.addWidget(dat_subtitle)
        dat_label_container = QtWidgets.QWidget()
        dat_label_container.setLayout(dat_label_layout)

        paths_layout.addWidget(dat_label_container, row, 0)
        paths_layout.addWidget(self.dat_edit, row, 1)

        dat_buttons_container = QtWidgets.QWidget()
        dat_buttons_container.setMinimumWidth(200)
        dat_buttons_layout = QtWidgets.QHBoxLayout(dat_buttons_container)
        dat_buttons_layout.setContentsMargins(0, 0, 0, 0)
        dat_buttons_layout.setSpacing(6)

        dat_browse_btn = QtWidgets.QPushButton("Browse")
        dat_browse_btn.clicked.connect(self._browse_dat)

        self.download_fresh1g1r_button = QtWidgets.QPushButton("Fresh 1G1R")
        self.download_fresh1g1r_button.clicked.connect(self._on_download_fresh1g1r_clicked)

        self.download_ra_button = QtWidgets.QPushButton("RetroAchievements")
        self.download_ra_button.clicked.connect(self._on_download_retroachievements_clicked)

        dat_buttons_layout.addWidget(self.download_fresh1g1r_button)
        dat_buttons_layout.addWidget(self.download_ra_button)
        dat_buttons_layout.addWidget(dat_browse_btn)

        paths_layout.addWidget(dat_buttons_container, row, 2)
        paths_layout.addWidget(self.dat_status, row, 3)
        row += 1

        def add_path_row(label_text: str, subtitle: str, line_edit: QtWidgets.QLineEdit, status_label: QtWidgets.QLabel, browse_slot):
            nonlocal row
            lbl = QtWidgets.QLabel(label_text)
            ff = lbl.font()
            ff.setBold(True)
            lbl.setFont(ff)

            sub = QtWidgets.QLabel(subtitle)
            sub.setStyleSheet("color: gray; font-size: 10px;")

            label_layout = QtWidgets.QVBoxLayout()
            label_layout.addWidget(lbl)
            label_layout.addWidget(sub)

            label_container = QtWidgets.QWidget()
            label_container.setLayout(label_layout)

            browse_btn = QtWidgets.QPushButton("Browse")
            browse_btn.setMinimumWidth(200)
            browse_btn.clicked.connect(browse_slot)

            paths_layout.addWidget(label_container, row, 0)
            paths_layout.addWidget(line_edit, row, 1)
            paths_layout.addWidget(browse_btn, row, 2)
            paths_layout.addWidget(status_label, row, 3)
            row += 1

        add_path_row("ROMs Directory", "(containing your current collection)", self.roms_edit, self.roms_status, self._browse_roms)
        add_path_row("Downloads Directory", "(where you want new downloads to go)", self.downloads_edit, self.downloads_status, self._browse_downloads)

        url_label = QtWidgets.QLabel("Myrient Base URL")
        ff = url_label.font()
        ff.setBold(True)
        url_label.setFont(ff)
        url_subtitle = QtWidgets.QLabel("(i'm innocent, i tells ya!)")
        url_subtitle.setStyleSheet("color: gray; font-size: 10px;")

        url_label_layout = QtWidgets.QVBoxLayout()
        url_label_layout.addWidget(url_label)
        url_label_layout.addWidget(url_subtitle)
        url_label_container = QtWidgets.QWidget()
        url_label_container.setLayout(url_label_layout)

        paths_layout.addWidget(url_label_container, row, 0)
        paths_layout.addWidget(self.myrient_edit, row, 1, 1, 2)
        paths_layout.addWidget(self.myrient_status, row, 3)

        main_layout.addWidget(paths_group)

        options_group = QtWidgets.QGroupBox("Options")
        options_layout = QtWidgets.QVBoxLayout(options_group)
        options_layout.setSpacing(8)
        options_layout.setContentsMargins(9, 0, 9, 9)

        def add_option_row(title_text: str, subtitle_text: str, initial_checked: bool = False):
            row_container = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row_container)
            row_layout.setSpacing(6)

            checkbox = CustomCheckBox()
            checkbox.setChecked(initial_checked)

            text_container = QtWidgets.QWidget()
            text_layout = QtWidgets.QVBoxLayout(text_container)
            text_layout.setContentsMargins(0, 0, 0, 0)

            title_label = QtWidgets.QLabel(title_text)
            tf = title_label.font()
            tf.setBold(True)
            title_label.setFont(tf)

            subtitle_label = QtWidgets.QLabel(subtitle_text)
            subtitle_label.setStyleSheet("color: gray; font-size: 10px;")

            text_layout.addWidget(title_label)
            text_layout.addWidget(subtitle_label)

            row_layout.addWidget(checkbox, alignment=QtCore.Qt.AlignVCenter)
            row_layout.addWidget(text_container, alignment=QtCore.Qt.AlignVCenter)
            row_layout.addStretch()

            return row_container, checkbox, subtitle_label, title_label

        igir_row, self.use_igir_check, igir_subtitle, igir_title = add_option_row(
            "Use IGIR to Align a Pre-Existing Collection Before Downloading",
            "",  # We'll set rich text below
            False,
        )
        # Configure subtitle with clickable link; store default for restoring when not RA
        igir_subtitle.setTextFormat(QtCore.Qt.RichText)
        igir_subtitle.setOpenExternalLinks(True)
        self._igir_subtitle_default = (
            '<span style="color: #8a8a8a;">'
            'Enable this if you have pre-existing ROMs in your ROM directory — '
            'this will compare your ROMs directory against the DAT and only download missing files.'
            '</span> '
            '<span style="color: #c0c0c0; font-weight: 600;">'
            'Note: Fetches IGIR.exe from '
            '</span>'
            '<a href="https://github.com/emmercm/igir/" style="color: #4da6ff; font-weight: 600;">'
            'github.com/emmercm/igir/'
            '</a>'
        )
        igir_subtitle.setText(self._igir_subtitle_default)
        self._igir_subtitle = igir_subtitle
        self._igir_title = igir_title

        options_layout.addWidget(igir_row)

        clean_row, self.clean_roms_check, self.clean_subtitle, self.clean_title_label = add_option_row(
            "Move Unrequired ROMs",
            "",
            CONFIG.clean_roms,
        )
        options_layout.addWidget(clean_row)

        main_layout.addWidget(options_group)

        buttons_layout = QtWidgets.QHBoxLayout()
        buttons_layout.setContentsMargins(10, 16, 10, 16)
        buttons_layout.setSpacing(12)

        self.run_button = QtWidgets.QPushButton("Run")
        self.run_button.setObjectName("primaryRunButton")
        self.run_button.clicked.connect(self._on_run_clicked)

        self.stop_button = QtWidgets.QPushButton("Stop")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.clicked.connect(self._on_stop_clicked)
        self.stop_button.setEnabled(False)

        for btn in (self.run_button, self.stop_button):
            ff = btn.font()
            ff.setPointSize(ff.pointSize() + 1)
            btn.setFont(ff)
            btn.setMinimumHeight(BUTTON_HEIGHT)

        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.run_button)
        buttons_layout.addWidget(self.stop_button)
        buttons_layout.addStretch(1)
        main_layout.addLayout(buttons_layout)

        runtime_group = QtWidgets.QGroupBox("Run")
        runtime_layout = QtWidgets.QVBoxLayout(runtime_group)
        runtime_layout.setContentsMargins(10, 8, 10, 10)
        runtime_layout.setSpacing(10)

        status_layout = QtWidgets.QHBoxLayout()
        status_layout.setContentsMargins(8, 6, 8, 6)
        status_layout.setSpacing(6)

        status_label = QtWidgets.QLabel("Status:")
        status_label.setObjectName("statusTitleLabel")
        sf = status_label.font()
        sf.setBold(True)
        status_label.setFont(sf)

        self.status_value = QtWidgets.QLabel("Ready")
        self.status_value.setObjectName("statusValueLabel")

        status_layout.addWidget(status_label)
        status_layout.addWidget(self.status_value, 1)

        status_container = QtWidgets.QWidget()
        status_container.setObjectName("statusContainer")
        status_container.setLayout(status_layout)
        runtime_layout.addWidget(status_container)

        self.overall_progress = QtWidgets.QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setFormat("%p%")
        self.overall_progress.setMinimumHeight(32)

        self.current_file_progress = QtWidgets.QProgressBar()
        self.current_file_progress.setRange(0, 100)
        self.current_file_progress.setFormat("%p%")
        self.current_file_progress.setMinimumHeight(32)

        # Initialize download tracking variables
        self._total_downloaded = 0
        self._total_size = 0
        self._current_file_size = 0
        self._last_total_size = ""
        self._last_current_file_progress = ""

        # Initialize download metrics labels (will be restyled below)
        self.speed_label = QtWidgets.QLabel("--")
        self.total_size_label = QtWidgets.QLabel("--")
        self.eta_label = QtWidgets.QLabel("--")
        self.current_file_progress_label = QtWidgets.QLabel("--")

        # Create main vertical layout for progress bars and their aligned metrics
        progress_section = QtWidgets.QVBoxLayout()
        progress_section.setSpacing(12)

        # First row: Overall progress bar with Total and Time Remaining
        overall_row = QtWidgets.QHBoxLayout()
        overall_row.setSpacing(12)

        # Overall progress bar (taller)
        self.overall_progress.setMinimumHeight(32)
        self._total_size = 0  # Will be updated during download
        overall_row.addWidget(self.overall_progress, 1)  # Give it stretch priority

        # Total metric box
        total_container = QtWidgets.QWidget()
        total_container.setObjectName("metricBox")
        total_layout = QtWidgets.QVBoxLayout(total_container)
        total_layout.setContentsMargins(8, 4, 8, 4)
        total_layout.setSpacing(1)

        total_title = QtWidgets.QLabel("Total")
        total_title.setObjectName("metricTitle")
        total_layout.addWidget(total_title)

        self.total_size_label.setText("--")
        self.total_size_label.setObjectName("metricValue")
        total_layout.addWidget(self.total_size_label)

        overall_row.addWidget(total_container)

        # Time Remaining metric box
        eta_container = QtWidgets.QWidget()
        eta_container.setObjectName("metricBox")
        eta_layout = QtWidgets.QVBoxLayout(eta_container)
        eta_layout.setContentsMargins(8, 4, 8, 4)
        eta_layout.setSpacing(1)

        eta_title = QtWidgets.QLabel("Time Remaining")
        eta_title.setObjectName("metricTitle")
        eta_layout.addWidget(eta_title)

        self.eta_label.setText("--")
        self.eta_label.setObjectName("metricValue")
        eta_layout.addWidget(self.eta_label)

        overall_row.addWidget(eta_container)

        progress_section.addLayout(overall_row)

        # Second row: Current file progress bar with Speed and Current Filesize
        file_row = QtWidgets.QHBoxLayout()
        file_row.setSpacing(12)

        # Current file progress bar (taller)
        self.current_file_progress.setMinimumHeight(32)
        file_row.addWidget(self.current_file_progress, 1)  # Give it stretch priority

        # Current file progress metric box (shows downloaded / total for current file)
        current_container = QtWidgets.QWidget()
        current_container.setObjectName("metricBox")
        current_layout = QtWidgets.QVBoxLayout(current_container)
        current_layout.setContentsMargins(8, 4, 8, 4)
        current_layout.setSpacing(1)

        current_title = QtWidgets.QLabel("Current")
        current_title.setObjectName("metricTitle")
        current_layout.addWidget(current_title)

        self.current_file_progress_label = QtWidgets.QLabel("--")
        self.current_file_progress_label.setObjectName("metricValue")
        current_layout.addWidget(self.current_file_progress_label)

        file_row.addWidget(current_container)

        # Speed metric box
        speed_container = QtWidgets.QWidget()
        speed_container.setObjectName("metricBox")
        speed_layout = QtWidgets.QVBoxLayout(speed_container)
        speed_layout.setContentsMargins(8, 4, 8, 4)
        speed_layout.setSpacing(1)

        speed_title = QtWidgets.QLabel("SPEED")
        speed_title.setObjectName("metricTitle")
        speed_layout.addWidget(speed_title)

        self.speed_label.setText("--")
        self.speed_label.setObjectName("metricValue")
        speed_layout.addWidget(self.speed_label)

        file_row.addWidget(speed_container)

        progress_section.addLayout(file_row)

        # Add the progress section to runtime layout
        runtime_layout.addLayout(progress_section)

        log_label = QtWidgets.QLabel("Log Output")
        lf = log_label.font()
        lf.setBold(True)
        log_label.setFont(lf)
        log_label.setContentsMargins(0, 8, 0, 0)
        runtime_layout.addWidget(log_label)

        self.log_edit = QtWidgets.QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.log_edit.setStyleSheet(f"font-family: Consolas, monospace; font-size: {LOG_FONT_SIZE}px;")
        runtime_layout.addWidget(self.log_edit, 1)

        main_layout.addWidget(runtime_group, 1)

        self._log_emitter = LogEmitter()
        self._log_emitter.log_signal.connect(self.append_log)

        self._retroachievements_dat = False
        self.dat_edit.textChanged.connect(lambda: (self._validate_field("dat"), self._update_igir_options_for_dat()))
        self.roms_edit.textChanged.connect(lambda: (self._validate_field("roms"), self._update_clean_roms_subtitle()))
        self.downloads_edit.textChanged.connect(lambda: self._validate_field("downloads"))
        # Myrient URL: only validate on focus loss/Enter (not every keystroke) to avoid network spam
        self.myrient_edit.editingFinished.connect(lambda: self._validate_field("myrient"))

        self.use_igir_check.stateChanged.connect(self._on_use_igir_changed)

        # Load saved settings BEFORE validation so we validate the loaded values
        self._load_settings()

        # Connect settings change signals (after load to avoid triggering saves during load)
        self._connect_settings_signals()

        # Now validate all fields with loaded values
        self._validate_all()
        self._update_clean_roms_subtitle()
        self._update_igir_options_for_dat()
        self._on_use_igir_changed(self.use_igir_check.checkState())

    def append_log(self, text: str) -> None:
        if not text:
            return
        scrollbar = self.log_edit.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= (scrollbar.maximum() - 10)

        self.log_edit.appendPlainText(text)

        if was_at_bottom:
            cursor = self.log_edit.textCursor()
            cursor.movePosition(cursor.End)
            self.log_edit.setTextCursor(cursor)

    def set_status(self, text: str) -> None:
        self.status_value.setText(text)

    def _apply_dark_theme(self) -> None:
        palette = self.palette()
        bg = QtGui.QColor(30, 30, 36)
        panel = QtGui.QColor(40, 40, 48)
        text = QtGui.QColor(230, 230, 235)
        disabled_text = QtGui.QColor(120, 120, 130)
        accent = QtGui.QColor(90, 160, 255)

        palette.setColor(QtGui.QPalette.Window, bg)
        palette.setColor(QtGui.QPalette.WindowText, text)
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor(20, 20, 26))
        palette.setColor(QtGui.QPalette.AlternateBase, panel)
        palette.setColor(QtGui.QPalette.Text, text)
        palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, disabled_text)
        palette.setColor(QtGui.QPalette.Button, panel)
        palette.setColor(QtGui.QPalette.ButtonText, text)
        palette.setColor(QtGui.QPalette.Highlight, accent)
        palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(0, 0, 0))
        self.setPalette(palette)

        app_font = self.font()
        app_font.setFamily("Segoe UI")
        app_font.setPointSize(9)
        self.setFont(app_font)

        self.setStyleSheet(APP_STYLESHEET)

    def _update_status_indicator(self, label: QtWidgets.QLabel, is_valid: bool) -> None:
        if is_valid:
            label.setText("✓")
            label.setStyleSheet("color: #4caf50; font-weight: 600; font-size: 16px;")
        else:
            label.setText("⚠")
            label.setStyleSheet("color: #ff9800; font-weight: 600; font-size: 16px;")

    def _validate_field(self, which: str) -> None:
        if which == "dat":
            _, valid, _ = validate_file_path(self.dat_edit.text().strip(), "DAT file")
            self._update_status_indicator(self.dat_status, valid)

        elif which == "roms":
            _, valid, _ = validate_directory_path(self.roms_edit.text().strip(), "ROMs directory")
            self._update_status_indicator(self.roms_status, valid)

        elif which == "downloads":
            _, valid, _ = validate_directory_path(self.downloads_edit.text().strip(),
                                                 "Downloads directory", allow_create=True)
            self._update_status_indicator(self.downloads_status, valid)

        elif which == "myrient":
            url = self.myrient_edit.text().strip()
            # Quick format check first
            if not url or not url.startswith(("http://", "https://")):
                self._update_status_indicator(self.myrient_status, False)
            # Check cache to avoid repeated network requests
            elif url in self._myrient_url_cache:
                self._update_status_indicator(
                    self.myrient_status, self._myrient_url_cache[url]
                )
            else:
                # Non-blocking HEAD request via QNetworkAccessManager. The
                # indicator is updated in _on_myrient_head_finished so the
                # GUI thread never blocks on network I/O.
                self._start_myrient_head(url)

    def _start_myrient_head(self, url: str) -> None:
        """Issue a non-blocking HEAD request via QNetworkAccessManager.

        The result is delivered to _on_myrient_head_finished on the GUI thread.
        Stale responses (where the user has since typed a different URL) still
        update the cache but do not change the visible indicator.
        """
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
        # Match the original requests.head(..., allow_redirects=True) behavior.
        request.setAttribute(
            QtNetwork.QNetworkRequest.FollowRedirectsAttribute, True
        )
        request.setHeader(
            QtNetwork.QNetworkRequest.UserAgentHeader, "MyrientCanFixDAT/1.0"
        )
        self._pending_myrient_url = url
        reply = self._qnam.head(request)
        reply.finished.connect(self._on_myrient_head_finished)

    def _on_myrient_head_finished(self) -> None:
        """Slot for the in-flight HEAD request. Updates cache and indicator."""
        reply = self.sender()
        if not isinstance(reply, QtNetwork.QNetworkReply):
            return
        url = self._pending_myrient_url
        if reply.error() == QtNetwork.QNetworkReply.NoError:
            status = reply.attribute(
                QtNetwork.QNetworkRequest.HttpStatusCodeAttribute
            )
            ok = status is not None and int(status) < 400
        else:
            ok = False
        self._myrient_url_cache[url] = ok
        # Only refresh the visible indicator if the URL is still the current
        # one; otherwise the user has typed something else and stale results
        # would be confusing.
        if url == self.myrient_edit.text().strip():
            self._update_status_indicator(self.myrient_status, ok)
        reply.deleteLater()

    def _validate_all(self) -> None:
        for name in ("dat", "roms", "downloads", "myrient"):
            self._validate_field(name)

    def _update_clean_roms_subtitle(self) -> None:
        self.clean_subtitle.setTextFormat(QtCore.Qt.RichText)

        roms_dir = self.roms_edit.text().strip()
        if roms_dir:
            try:
                resolved = resolve_path(roms_dir)
                not_required = resolved / "NotRequired"
                path_str = normalize_path_display(str(not_required))
            except Exception:  # noqa: BLE001
                path_str = normalize_path_display(f"{roms_dir}/NotRequired")

            self.clean_subtitle.setText(
                '<span style="color: #8a8a8a;">'
                "Filters out your existing ROMs which aren't in the DAT provided "
                "non-destructively and moves them to a subdirectory of your collection: "
                '</span>'
                f'<span style="color: #cfcfcf; font-weight: 600;">{path_str}</span>'
            )
        else:
            self.clean_subtitle.setText(
                '<span style="color: #8a8a8a;">'
                "Filters out your existing ROMs which aren't in the DAT provided "
                "non-destructively and moves them to a subdirectory of your collection: "
                '</span>'
                '<span style="color: #cfcfcf; font-weight: 600;">'
                '{selected directory}\\NotRequired'
                '</span>'
            )


    def _update_igir_options_for_dat(self) -> None:
        """If the selected DAT is a RetroAchievements DAT, disable IGIR/clean options and use simple fixdat matching."""
        dat_path = resolve_path(self.dat_edit.text().strip())
        if dat_path.exists() and dat_path.is_file() and is_retroachievements_dat(dat_path):
            self._retroachievements_dat = True
            self.use_igir_check.setChecked(False)
            self.use_igir_check.setEnabled(False)
            self.clean_roms_check.setChecked(False)
            self.clean_roms_check.setEnabled(False)
            self._igir_title.setEnabled(False)
            self._igir_subtitle.setEnabled(False)
            self.clean_title_label.setEnabled(False)
            self.clean_subtitle.setEnabled(False)
            self._igir_subtitle.setText(
                '<span style="color: #8a8a8a;">'
                "RetroAchievements DAT selected — using simple fixdat matching; IGIR is skipped."
                "</span>"
            )
        else:
            self._retroachievements_dat = False
            self._igir_subtitle.setText(self._igir_subtitle_default)
            self.use_igir_check.setEnabled(True)
            self._igir_title.setEnabled(True)
            self._igir_subtitle.setEnabled(True)
            self.clean_subtitle.setEnabled(True)
            self._on_use_igir_changed(self.use_igir_check.checkState())

    def _on_use_igir_changed(self, state: int) -> None:
        is_checked = state == QtCore.Qt.Checked
        if is_checked:
            # IGIR enabled - allow "Move Unrequired ROMs" option
            self.clean_roms_check.setEnabled(True)
            self.clean_title_label.setEnabled(True)
        else:
            # IGIR disabled - disable "Move Unrequired ROMs" option
            self.clean_roms_check.setChecked(False)
            self.clean_roms_check.setEnabled(False)
            self.clean_title_label.setEnabled(False)

    def _browse_dat(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select DAT file", str(Path.cwd()), "DAT files (*.dat);;All files (*)"
        )
        if path:
            self.dat_edit.setText(normalize_path_display(path))

    def _browse_roms(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select ROMs directory", str(Path.cwd()))
        if path:
            normalized = normalize_path_display(path)
            self.roms_edit.setText(normalized)
            self.downloads_edit.setText(normalized)
            self._validate_field("downloads")

    def _browse_downloads(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select downloads directory", str(Path.cwd()))
        if path:
            self.downloads_edit.setText(normalize_path_display(path))

    def _on_download_fresh1g1r_clicked(self) -> None:
        dialog = DatDownloadDialog(self, mode="fresh1g1r")
        if dialog.exec_() == QtWidgets.QDialog.Accepted and dialog.selected_dat_path:
            self.dat_edit.setText(normalize_path_display(str(dialog.selected_dat_path)))
            self._validate_field("dat")

    def _on_download_retroachievements_clicked(self) -> None:
        dialog = DatDownloadDialog(self, mode="retroachievements")
        if dialog.exec_() == QtWidgets.QDialog.Accepted and dialog.selected_dat_path:
            self.dat_edit.setText(normalize_path_display(str(dialog.selected_dat_path)))
            self._validate_field("dat")

    def _on_run_clicked(self) -> None:
        config_snapshot = CONFIG.to_dict()
        config_snapshot["list_dat"] = self.dat_edit.text().strip()
        config_snapshot["roms_directory"] = self.roms_edit.text().strip()
        config_snapshot["downloads_directory"] = self.downloads_edit.text().strip()

        url = self.myrient_edit.text().strip()
        if url:
            config_snapshot["myrient_base_url"] = url

        # RetroAchievements DATs always use simple fixdat matching; skip IGIR
        if getattr(self, "_retroachievements_dat", False):
            use_igir = False
            config_snapshot["clean_roms"] = False
        else:
            config_snapshot["clean_roms"] = self.clean_roms_check.isChecked()
            use_igir = self.use_igir_check.isChecked()

        # When using fixdat (no IGIR), ask about clones if DAT has parent/clone relationships
        if not use_igir:
            dat_path = resolve_path(self.dat_edit.text().strip())
            if dat_path.exists() and dat_path.is_file() and dat_has_clones(dat_path):
                reply = QtWidgets.QMessageBox.question(
                    self,
                    "Clones Detected in this DAT",
                    "Do you want to include clones in this download?\n\nIf you're aiming for 1G1R — click No.",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No,
                )
                config_snapshot["include_clones"] = reply == QtWidgets.QMessageBox.Yes
            else:
                config_snapshot["include_clones"] = True
        else:
            config_snapshot["include_clones"] = True

        # When using IGIR, create NotRequired/NOTHINGTOCLEAN if ROM directory is empty (IGIR clean expects this)
        if use_igir:
            roms_dir = Path(config_snapshot["roms_directory"])
            if roms_dir.exists() and roms_dir.is_dir():
                try:
                    has_files = any(item.is_file() for item in roms_dir.iterdir())
                    if not has_files:
                        not_required_dir = roms_dir / NOT_REQUIRED_DIR
                        not_required_dir.mkdir(exist_ok=True)
                        nothing_to_clean_file = not_required_dir / "NOTHINGTOCLEAN"
                        nothing_to_clean_file.touch()
                        print(f"📁 Created {nothing_to_clean_file} (ROM directory was empty)")
                except (OSError, PermissionError) as e:
                    print(f"⚠️  Could not check/create NOTHINGTOCLEAN file: {e}")

        self._start_mcfd_worker(config_snapshot, use_igir)

    def _on_stop_clicked(self) -> None:
        if self.worker and self.worker.isRunning():
            if not self._stop_requested_once:
                # First click - graceful stop
                self._stop_requested_once = True
                self.stop_button.setText("Stopping...")
                if hasattr(self.worker, "request_stop"):
                    self.worker.request_stop()  # type: ignore[attr-defined]
                    self.log_edit.appendPlainText("🛑 Stop requested - finishing current download...")
                else:
                    self.worker.requestInterruption()
                    self.log_edit.appendPlainText("🛑 Stop requested...")
            else:
                # Second click - force stop
                self.worker.requestInterruption()  # Signal interruption first
                self.worker.terminate()  # Then terminate forcefully
                self.stop_button.setText("Force Stopping...")
                self.log_edit.appendPlainText("🛑 Force stop requested - terminating immediately...")

                # Force immediate cleanup since terminate() might not trigger finished signal
                QtCore.QTimer.singleShot(100, self._force_cleanup_after_terminate)

    def _start_mcfd_worker(self, config_snapshot: dict, use_igir: bool) -> None:
        if self.worker and self.worker.isRunning():
            return

        self._stop_requested_once = False  # Reset stop flag for new operation
        self.stop_button.setText("Stop")  # Reset button text
        self._last_eta = ""  # Reset ETA for new operation

        # Reset speed history for new operation
        if hasattr(self, 'worker') and self.worker:
            self.worker._speed_history = []

        self.overall_progress.setValue(0)
        self.current_file_progress.setValue(0)
        self.set_status("Preparing...")
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        worker = DownloadWorker(config_snapshot, use_igir, self)
        self.worker = worker

        worker.progress_signal.connect(self._on_mcfd_progress)
        worker.status_signal.connect(self.set_status)
        worker.log_signal.connect(self.append_log)
        worker.error_signal.connect(self._on_mcfd_error)
        worker.finished_signal.connect(self._on_worker_finished)
        worker.request_myrient_url_override.connect(self._on_request_myrient_url_override)
        worker.start()

    @QtCore.pyqtSlot(object, object, str, str, str, str)
    def _on_mcfd_progress(self, overall, current_file, text: str, speed: str, total_size: str, eta: str) -> None:
        if overall is not None:
            self.overall_progress.setValue(int(overall))

        if current_file is not None:
            self.current_file_progress.setValue(int(current_file))

        if text:
            self.set_status(text)

        # Update stylish metrics display
        self.speed_label.setText(speed if speed and speed != "--" else "--")

        # Preserve total size if it's being cleared but we have a valid total stored
        if total_size and total_size != "0 B":
            self._last_total_size = total_size
            self.total_size_label.setText(total_size)
        elif hasattr(self, '_last_total_size') and self._last_total_size:
            # Keep the last known good total size
            self.total_size_label.setText(self._last_total_size)
        else:
            self.total_size_label.setText("--")

        # Preserve ETA if it's being cleared but we have a valid ETA stored
        if eta and eta != "--":
            self._last_eta = eta
            self.eta_label.setText(eta)
        elif hasattr(self, '_last_eta') and self._last_eta:
            # Keep the last known good ETA
            self.eta_label.setText(self._last_eta)
        else:
            self.eta_label.setText("--")

        # Current file progress - get from worker instance
        if hasattr(self, 'current_file_progress_label') and self.worker:
            worker_progress = getattr(self.worker, '_current_file_progress', '')
            if worker_progress and " / " in worker_progress:  # Only update for actual progress format
                self._last_current_file_progress = worker_progress
                self.current_file_progress_label.setText(worker_progress)
            elif worker_progress == "":  # Explicit reset (file completed)
                self._last_current_file_progress = ""
                self.current_file_progress_label.setText("--")
            # Otherwise preserve the current value

    def _show_error_dialog(self, title: str, message: str) -> None:
        """Show an error dialog with a copy button to copy the error message."""
        dialog = QtWidgets.QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setText(message)
        dialog.setIcon(QtWidgets.QMessageBox.Critical)

        # Add copy button
        copy_button = dialog.addButton("Copy Error", QtWidgets.QMessageBox.ActionRole)
        copy_button.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(message))

        # Add standard OK button
        dialog.addButton(QtWidgets.QMessageBox.Ok)

        dialog.exec_()

    @QtCore.pyqtSlot(str)
    def _on_request_myrient_url_override(self, failed_url: str) -> None:
        """Show dialog asking for full Myrient URL when worker got 404; emit result so worker can retry."""
        url = self._show_myrient_url_override_dialog(failed_url)
        self.myrient_override_result_signal.emit(url)

    def _show_myrient_url_override_dialog(self, failed_url: str) -> str:
        """Show a dialog asking for the full Myrient URL when inferred URL returned 404.
        Returns the URL string if user clicks OK, or empty string if cancelled."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Myrient URL Not Found (404)")
        dialog.setWindowFlags(
            QtCore.Qt.Dialog
            | QtCore.Qt.WindowSystemMenuHint
        )
        dialog.resize(520, 220)

        palette = dialog.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(42, 43, 51))
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor(42, 43, 51))
        dialog.setPalette(palette)
        dialog.setAutoFillBackground(True)

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Title bar (match DatDownloadDialog style)
        title_bar = QtWidgets.QWidget(dialog)
        title_bar.setObjectName("titleBar")
        title_bar.setFixedHeight(TITLE_BAR_HEIGHT)
        title_layout = QtWidgets.QHBoxLayout(title_bar)
        title_layout.setContentsMargins(10, 4, 8, 4)
        title_layout.setSpacing(8)
        title_label = QtWidgets.QLabel("Myrient URL Not Found (404)")
        title_label.setObjectName("titleText")
        title_layout.addWidget(title_label)
        title_layout.addStretch(1)
        close_btn = QtWidgets.QPushButton("×")
        close_btn.setObjectName("titleButtonClose")
        close_btn.setFixedSize(28, 22)
        close_btn.clicked.connect(dialog.reject)
        title_layout.addWidget(close_btn)
        layout.addWidget(title_bar)

        # Content panel
        content = QtWidgets.QWidget(dialog)
        content.setObjectName("dialogPanel")
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(8)
        layout.addWidget(content)

        msg = QtWidgets.QLabel(
            "The inferred Myrient URL doesn't seem to exist... Myrient is either down, or more likely the system you are looking for is in a different folder name that we can't infer from the DAT. This is normal for some specific systems.\n\nIn this case, please enter the full Myrient URL to the game directory:"
        )
        msg.setWordWrap(True)
        msg.setStyleSheet("color: #e6e6eb;")
        content_layout.addWidget(msg)
        line_edit = QtWidgets.QLineEdit()
        line_edit.setPlaceholderText("https://myrient.erista.me/files/Redump/...")
        line_edit.setText(failed_url)
        line_edit.setMinimumWidth(450)
        content_layout.addWidget(line_edit)

        buttons_layout = QtWidgets.QHBoxLayout()
        buttons_layout.setSpacing(8)
        buttons_layout.addStretch(1)
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.setObjectName("flatDialogButton")
        ok_btn = QtWidgets.QPushButton("OK")
        ok_btn.setObjectName("primaryDialogButton")
        cancel_btn.clicked.connect(dialog.reject)
        ok_btn.clicked.connect(dialog.accept)
        buttons_layout.addWidget(cancel_btn)
        buttons_layout.addWidget(ok_btn)
        content_layout.addLayout(buttons_layout)

        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            return line_edit.text().strip()
        return ""

    def _on_mcfd_error(self, message: str) -> None:
        self._show_error_dialog("Error", message)
        self.set_status("Error")

    def _force_cleanup_after_terminate(self) -> None:
        """Force cleanup after terminate() since it might not trigger finished signal properly."""
        if self.worker and not self.worker.isRunning():
            self.set_status("Force stopped")  # Override the status
            self._on_worker_finished()  # Use the standard cleanup
        elif self.worker:
            # If still running after timeout, force cleanup anyway
            self.set_status("Force stopped")
            self._on_worker_finished()

    def _on_worker_finished(self) -> None:
        # Reset all UI elements to pre-download state
        self.overall_progress.setValue(0)
        self.current_file_progress.setValue(0)
        self.speed_label.setText("--")
        self.total_size_label.setText("--")
        self.eta_label.setText("--")
        self.current_file_progress_label.setText("--")
        self.set_status("Ready")
        self._last_total_size = ""
        self._last_eta = ""

        # Reset buttons and flags
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.stop_button.setText("Stop")  # Reset button text
        self._stop_requested_once = False  # Reset stop flag

        # Clear worker reference
        if self.worker and hasattr(self.worker, '_current_file_progress'):
            self.worker._current_file_progress = ""
        self.worker = None

    def _load_settings(self) -> None:
        """Load saved settings from QSettings.

        Settings are stored using Qt's QSettings system, which automatically
        chooses the appropriate storage location based on the platform:
        - Windows: Registry (HKCU\Software\MyrientCanFixDAT)
        - macOS: ~/Library/Preferences/com.MyrientCanFixDAT.plist
        - Linux: ~/.config/MyrientCanFixDAT.conf
        """
        settings = QSettings("MyrientCanFixDAT", "Settings")

        # Load path settings with fallbacks to initial defaults
        # Normalize all paths for consistent display (OS-native separators)
        
        # DAT file: use cached DAT if found, otherwise empty
        dat_path = settings.value(SETTING_DAT_FILE, get_initial_dat_file(), str)
        self.dat_edit.setText(normalize_path_display(dat_path))
        
        # ROMs directory: empty by default - user must set
        roms_path = settings.value(SETTING_ROMS_DIR, CONFIG.roms_directory, str)
        self.roms_edit.setText(normalize_path_display(roms_path))
        
        # Downloads directory: empty by default - user must set
        downloads_path = settings.value(SETTING_DOWNLOADS_DIR, CONFIG.downloads_directory, str)
        self.downloads_edit.setText(normalize_path_display(downloads_path))
        
        # Myrient URL: use saved value or default
        self.myrient_edit.setText(
            settings.value(SETTING_MYRIENT_URL, CONFIG.myrient_base_url or "", str)
        )

        # Load checkbox settings
        self.use_igir_check.setChecked(
            settings.value(SETTING_USE_IGIR, False, bool)
        )
        self.clean_roms_check.setChecked(
            settings.value(SETTING_CLEAN_ROMS, CONFIG.clean_roms, bool)
        )

    def _save_settings(self) -> None:
        """Save current settings to QSettings."""
        settings = QSettings("MyrientCanFixDAT", "Settings")

        # Save path settings
        settings.setValue(SETTING_DAT_FILE, self.dat_edit.text().strip())
        settings.setValue(SETTING_ROMS_DIR, self.roms_edit.text().strip())
        settings.setValue(SETTING_DOWNLOADS_DIR, self.downloads_edit.text().strip())
        settings.setValue(SETTING_MYRIENT_URL, self.myrient_edit.text().strip())

        # Save checkbox settings
        settings.setValue(SETTING_USE_IGIR, self.use_igir_check.isChecked())
        settings.setValue(SETTING_CLEAN_ROMS, self.clean_roms_check.isChecked())

        settings.sync()  # Ensure settings are written immediately

    def _connect_settings_signals(self) -> None:
        """Connect signals to automatically save settings when they change."""
        # Save settings when text changes (with debouncing to avoid too frequent saves)
        self.dat_edit.textChanged.connect(self._on_settings_changed)
        self.roms_edit.textChanged.connect(self._on_settings_changed)
        self.downloads_edit.textChanged.connect(self._on_settings_changed)
        self.myrient_edit.textChanged.connect(self._on_settings_changed)

        # Save settings when checkboxes change
        self.use_igir_check.stateChanged.connect(self._on_settings_changed)
        self.clean_roms_check.stateChanged.connect(self._on_settings_changed)

    def _on_settings_changed(self) -> None:
        """Handle settings changes - save after a short delay to avoid excessive writes."""
        # Use a timer to debounce settings saves
        if hasattr(self, '_settings_timer'):
            self._settings_timer.stop()

        self._settings_timer = QtCore.QTimer(self)
        self._settings_timer.setSingleShot(True)
        self._settings_timer.timeout.connect(self._save_settings)
        self._settings_timer.setInterval(1000)  # Save after 1 second of no changes
        self._settings_timer.start()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # type: ignore[name-defined]
        # Save settings before closing
        self._save_settings()

        if self.worker is not None and self.worker.isRunning():
            if hasattr(self.worker, "request_stop"):
                self.worker.request_stop()  # type: ignore[attr-defined]
            self.worker.requestInterruption()

        downloads_dir_text = self.downloads_edit.text().strip()
        if downloads_dir_text:
            try:
                dpath = Path(downloads_dir_text)
                if dpath.exists():
                    for tmp in dpath.glob("*.tmp"):
                        try:
                            tmp.unlink()
                        except OSError:
                            pass
            except OSError:
                pass

        super().closeEvent(event)


class DatDownloadDialog(QtWidgets.QDialog):
    """Dialog to select and download DAT files from Fresh1G1R or RetroAchievements GitHub repos."""

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        mode: Literal["fresh1g1r", "retroachievements"] = "fresh1g1r",
    ) -> None:
        super().__init__(parent)
        self._mode = mode
        self.setWindowTitle("Download DAT from RetroAchievements" if mode == "retroachievements" else "Download DAT from Fresh 1G1R")
        self.resize(650, 550)

        self.setWindowFlags(
            QtCore.Qt.Dialog
            | QtCore.Qt.WindowSystemMenuHint
        )

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(42, 43, 51))
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor(42, 43, 51))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        self.selected_dat_path: Optional[Path] = None
        self._dat_files: List[dict] = []

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        content = QtWidgets.QWidget(self)
        content.setObjectName("dialogPanel")
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(8)
        layout.addWidget(content)

        _link_style = 'style="color: #88b0dc; text-decoration: none;"'
        self.info_label = QtWidgets.QLabel(
            f'DATs from Unofficial RetroAchievements sets: <a href="https://github.com/UltraGodAzgorath/Unofficial-RA-DATs" {_link_style}>github.com/UltraGodAzgorath/Unofficial-RA-DATs</a>'
            if mode == "retroachievements"
            else f'DATs are pulled from the daily updated 1G1R sets at: <a href="https://github.com/UnluckyForSome/Fresh1G1R" {_link_style}>github.com/UnluckyForSome/Fresh1G1R</a>'
        )
        self.info_label.setStyleSheet(
            "color: gray; font-size: 10px;"
            " QLabel a { color: #88b0dc; }"
        )
        self.info_label.setTextFormat(QtCore.Qt.RichText)
        self.info_label.setOpenExternalLinks(True)
        content_layout.addWidget(self.info_label)

        if mode == "retroachievements":
            self.ra_disclaimer_label = QtWidgets.QLabel(
                "This app has no control over this repo — DATs may be out of date or unsuitable."
            )
            self.ra_disclaimer_label.setStyleSheet("color: #a85858; font-size: 10px;")
            content_layout.addWidget(self.ra_disclaimer_label)
        else:
            self.ra_disclaimer_label = None

        selectors = QtWidgets.QWidget()
        selectors_layout = QtWidgets.QHBoxLayout(selectors)
        selectors_layout.setContentsMargins(0, 4, 0, 8)
        selectors_layout.setSpacing(24)

        type_label = QtWidgets.QLabel("Virgin DAT Source")
        type_label.setStyleSheet("font-weight: 600;")

        self.type_no_intro_btn = QtWidgets.QPushButton("no-intro")
        self.type_no_intro_btn.setCheckable(True)
        self.type_no_intro_btn.setObjectName("segLeft")

        self.type_redump_btn = QtWidgets.QPushButton("redump")
        self.type_redump_btn.setCheckable(True)
        self.type_redump_btn.setObjectName("segRight")

        self.type_no_intro_btn.setChecked(True)

        type_buttons_layout = QtWidgets.QHBoxLayout()
        type_buttons_layout.setContentsMargins(0, 0, 0, 0)
        type_buttons_layout.setSpacing(8)
        type_buttons_layout.addWidget(self.type_no_intro_btn)
        type_buttons_layout.addWidget(self.type_redump_btn)

        type_vbox = QtWidgets.QVBoxLayout()
        type_vbox.addWidget(type_label)
        type_vbox.addLayout(type_buttons_layout)

        type_container = QtWidgets.QWidget()
        type_container.setLayout(type_vbox)

        source_label = QtWidgets.QLabel("Filtered Game Collection")
        source_label.setStyleSheet("font-weight: 600;")

        self.source_mclean_btn = QtWidgets.QPushButton("McLean")
        self.source_mclean_btn.setCheckable(True)
        self.source_mclean_btn.setObjectName("segLeft")

        self.source_proper_btn = QtWidgets.QPushButton("PropeR")
        self.source_proper_btn.setCheckable(True)
        self.source_proper_btn.setObjectName("segMid")

        self.source_hearto_btn = QtWidgets.QPushButton("Hearto")
        self.source_hearto_btn.setCheckable(True)
        self.source_hearto_btn.setObjectName("segRight")

        self.source_mclean_btn.setChecked(True)

        source_buttons_layout = QtWidgets.QHBoxLayout()
        source_buttons_layout.setContentsMargins(0, 0, 0, 0)
        source_buttons_layout.setSpacing(8)
        source_buttons_layout.addWidget(self.source_mclean_btn)
        source_buttons_layout.addWidget(self.source_proper_btn)
        source_buttons_layout.addWidget(self.source_hearto_btn)

        source_vbox = QtWidgets.QVBoxLayout()
        source_vbox.addWidget(source_label)
        source_vbox.addLayout(source_buttons_layout)

        source_container = QtWidgets.QWidget()
        source_container.setLayout(source_vbox)

        selectors_layout.addWidget(type_container)
        selectors_layout.addWidget(source_container)
        selectors_layout.setStretch(0, 1)
        selectors_layout.setStretch(1, 1)
        content_layout.addWidget(selectors)
        selectors.setVisible(self._mode == "fresh1g1r")

        list_group = QtWidgets.QGroupBox("Select DAT File")
        list_vbox = QtWidgets.QVBoxLayout(list_group)
        self.dat_list = QtWidgets.QListWidget()
        self.dat_list.setObjectName("datListWidget")
        self.dat_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        list_vbox.addWidget(self.dat_list)
        content_layout.addWidget(list_group, 1)

        buttons_layout = QtWidgets.QHBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(8)
        buttons_layout.addStretch(1)
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.setObjectName("flatDialogButton")
        download_btn = QtWidgets.QPushButton("Download")
        download_btn.setObjectName("primaryDialogButton")
        buttons_layout.addWidget(cancel_btn)
        buttons_layout.addWidget(download_btn)
        content_layout.addLayout(buttons_layout)

        cancel_btn.clicked.connect(self.reject)
        download_btn.clicked.connect(self._on_download_clicked)

        for btn in (
            self.type_no_intro_btn,
            self.type_redump_btn,
            self.source_mclean_btn,
            self.source_proper_btn,
            self.source_hearto_btn,
        ):
            btn.toggled.connect(lambda checked, b=btn: self._on_segment_toggled(b, checked))

        self._refresh_list()

    def _current_type(self) -> str:
        return "redump" if self.type_redump_btn.isChecked() else "no-intro"

    def _current_source(self) -> str:
        if self.source_proper_btn.isChecked():
            return "PropeR"
        if self.source_hearto_btn.isChecked():
            return "Hearto"
        return "McLean"

    def _on_segment_toggled(self, button: QtWidgets.QPushButton, checked: bool) -> None:
        if not checked:
            return

        if button in (self.type_no_intro_btn, self.type_redump_btn):
            for b in (self.type_no_intro_btn, self.type_redump_btn):
                if b is not button:
                    b.setChecked(False)

        if button in (self.source_mclean_btn, self.source_proper_btn, self.source_hearto_btn):
            for b in (self.source_mclean_btn, self.source_proper_btn, self.source_hearto_btn):
                if b is not button:
                    b.setChecked(False)

        self._refresh_list()

    def _refresh_list(self) -> None:
        self.dat_list.clear()
        self.dat_list.addItem("Loading...")
        self._dat_files = []

        if self._mode == "retroachievements":
            folder_path = RA_DAT_PATH
            api_url = f"{GITHUB_API_BASE}/{RA_DAT_REPO}/contents/{urllib.parse.quote(folder_path, safe='/')}"
        else:
            selected_type = self._current_type()
            selected_source = self._current_source()
            folder_path = f"{DAILY_1G1R_PATH}/{selected_source}/{selected_type}"
            api_url = f"{GITHUB_API_BASE}/{FRESH1G1R_REPO}/contents/{folder_path}"

        try:
            resp = requests.get(api_url, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            files = resp.json()
        except requests.Timeout:
            self.dat_list.clear()
            self.dat_list.addItem("Error: Timeout loading DAT list")
            return
        except requests.ConnectionError:
            self.dat_list.clear()
            self.dat_list.addItem("Error: Connection error loading DAT list")
            return
        except requests.HTTPError as e:
            self.dat_list.clear()
            self.dat_list.addItem(f"Error: HTTP {e.response.status_code} loading DAT list")
            return
        except ValueError:
            self.dat_list.clear()
            self.dat_list.addItem("Error: Invalid response from GitHub API")
            return
        except Exception as e:  # noqa: BLE001
            self.dat_list.clear()
            self.dat_list.addItem(f"Error: {e}")
            return

        dat_files = [f for f in files if isinstance(f, dict) and str(f.get("name", "")).endswith(DAT_EXTENSION)]
        dat_files.sort(key=lambda x: str(x.get("name", "")), reverse=True)

        self.dat_list.clear()
        if not dat_files:
            self.dat_list.addItem("No DAT files found")
            return

        for f in dat_files:
            self.dat_list.addItem(str(f.get("name", "")))

        self._dat_files = [
            {"name": f.get("name", ""), "download_url": f.get("download_url"), "path": f.get("path")}
            for f in dat_files
        ]

        if self._dat_files:
            self.dat_list.setCurrentRow(0)

    def _show_error_dialog(self, title: str, message: str) -> None:
        """Show an error dialog with a copy button to copy the error message."""
        dialog = QtWidgets.QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setText(message)
        dialog.setIcon(QtWidgets.QMessageBox.Critical)

        # Add copy button
        copy_button = dialog.addButton("Copy Error", QtWidgets.QMessageBox.ActionRole)
        copy_button.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(message))

        # Add standard OK button
        dialog.addButton(QtWidgets.QMessageBox.Ok)

        dialog.exec_()

    def _on_download_clicked(self) -> None:
        row = self.dat_list.currentRow()
        if row < 0 or not self._dat_files:
            QtWidgets.QMessageBox.warning(self, "Warning", "Please select a DAT file")
            return

        dat_info = self._dat_files[row]
        download_url = dat_info.get("download_url")
        filename = dat_info.get("name") or "downloaded.dat"

        if not download_url:
            QtWidgets.QMessageBox.warning(self, "Warning", "Could not get download URL for DAT file")
            return

        try:
            cache_dir = SCRIPT_DIR / DAT_CACHE_DIR
            cache_dir.mkdir(exist_ok=True)
            output_path = cache_dir / filename

            resp = requests.get(str(download_url), timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            output_path.write_bytes(resp.content)

            self.selected_dat_path = output_path
            QtWidgets.QMessageBox.information(self, "Downloaded", f"Downloaded {filename} to:\n{normalize_path_display(str(output_path))}")
            self.accept()

        except requests.Timeout:
            self._show_error_dialog("Error", "Timeout downloading DAT file. Please try again.")
        except requests.ConnectionError:
            self._show_error_dialog("Error", "Connection error downloading DAT file. Check your internet connection.")
        except requests.HTTPError as e:
            self._show_error_dialog("Error", f"HTTP error downloading DAT file: {e}")
        except OSError as e:
            self._show_error_dialog("Error", f"File system error saving DAT file: {e}")
        except Exception as e:  # noqa: BLE001
            self._show_error_dialog("Error", f"Unexpected error downloading DAT file: {e}")


# ============================================================================
# MAIN
# ============================================================================

def main() -> None:
    app = QtWidgets.QApplication(sys.argv)

    # Palette for native dialogs / overall app
    palette = app.palette()
    bg = QtGui.QColor(30, 30, 36)
    panel = QtGui.QColor(40, 40, 48)
    text = QtGui.QColor(230, 230, 235)
    accent = QtGui.QColor(90, 160, 255)

    palette.setColor(QtGui.QPalette.Window, bg)
    palette.setColor(QtGui.QPalette.WindowText, text)
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(20, 20, 26))
    palette.setColor(QtGui.QPalette.AlternateBase, panel)
    palette.setColor(QtGui.QPalette.Text, text)
    palette.setColor(QtGui.QPalette.Button, panel)
    palette.setColor(QtGui.QPalette.ButtonText, text)
    palette.setColor(QtGui.QPalette.Highlight, accent)
    app.setPalette(palette)

    # One global stylesheet (covers dialogs too)
    app.setStyleSheet(APP_STYLESHEET)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
