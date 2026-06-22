"""Editable application settings used by the Settings dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from minerva.ui.density import Density


class ThemeName:
    DARK = "dark"


class AccentName:
    BLUE = "blue"
    PURPLE = "purple"
    GREEN = "green"


@dataclass
class SettingsDraft:
    qbit_url: str = "http://localhost:8080"
    qbit_username: str = "admin"
    qbit_password: str = ""
    output_directory: Path = Path("downloads")
    torrent_directory: Path = Path("torrents/Minerva Myrient - 1050 torrents")
    index_path: Path = Path("torrents/minerva_index.db")
    cover_directory: Path = Path("covers")
    keep_seeding: bool = True
    create_hardlinks: bool = True
    preserve_partial: bool = True
    open_destination: bool = False
    notifications: bool = True
    max_concurrent: int = 6
    timeout_seconds: int = 1800
    density: Density = Density.COMPACT
    theme: str = ThemeName.DARK
    accent: str = AccentName.BLUE
