"""
Minerva Database Layer — Production grade
==========================================
Provides a robust, performant, and well-tested interface to the
Minerva torrent index.

Architecture:
- Tiered matching: exact → FTS5 MATCH → FTS5 trigram → Python fuzzy
- LRU cache with TTL for repeated queries
- Schema versioning with automatic migration
- Python logging (no print statements)
- Comprehensive docstrings

This module is UI-agnostic. The GUI lives in `minerva_gui.py`.
"""
from __future__ import annotations

import csv
import datetime
import logging
import re
from pathlib import Path
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Collection, Sequence

# ── Domain type imports (graceful fallback for early bootstrap) ────────────────
_HAS_DOMAIN = False
try:
    from minerva.domain.library import FacetCount, LibraryFacets, LibraryItem, LibraryQuery
    from minerva.domain.downloads import DownloadFileSpec
    from minerva.domain.collections import (
        IndexOverview, CollectionSummary, SystemSummary, CollectionStatus,
    )
    _HAS_DOMAIN = True
except ImportError:
    FacetCount = None  # type: ignore[assignment, misc]
    LibraryFacets = None  # type: ignore[assignment, misc]
    LibraryItem = None  # type: ignore[assignment, misc]
    DownloadFileSpec = None  # type: ignore[assignment, misc]
    LibraryQuery = None  # type: ignore[assignment, misc]
    IndexOverview = None  # type: ignore[assignment, misc]
    CollectionSummary = None  # type: ignore[assignment, misc]
    SystemSummary = None  # type: ignore[assignment, misc]
    CollectionStatus = None  # type: ignore[assignment, misc]

# ── Configuration ─────────────────────────────────────────────────────────────
SCHEMA_VERSION = 3
DEFAULT_TORRENT_DIR = Path("torrents/Minerva Myrient - 1050 torrents")
DEFAULT_INDEX_PATH = Path("torrents/minerva_index.db")

# Default cache settings
CACHE_MAX_ENTRIES = 256
CACHE_TTL_SECONDS = 300  # 5 minutes

# Default match settings
MAX_FUZZY_CANDIDATES = 200
MIN_KEYWORD_LEN = 3
FUZZY_KEYWORD_OVERLAP_THRESHOLD = 0.7  # 70% keyword overlap

# ── Logging ──────────────────────────────────────────────────────────────────
log = logging.getLogger(__name__)

# ── Pure-Python Bencode ──────────────────────────────────────────────────────
def bdecode(data: bytes, idx: int = 0) -> tuple:
    """Decode bencoded data. Returns (value, next_index)."""
    c = data[idx:idx + 1]
    if c == b'd':
        idx += 1
        d: dict = {}
        while data[idx:idx + 1] != b'e':
            k, idx = bdecode(data, idx)
            v, idx = bdecode(data, idx)
            d[k] = v
        return d, idx + 1
    if c == b'l':
        idx += 1
        lst: list = []
        while data[idx:idx + 1] != b'e':
            v, idx = bdecode(data, idx)
            lst.append(v)
        return lst, idx + 1
    if c == b'i':
        end = data.index(b'e', idx)
        return int(data[idx + 1:end]), end + 1
    colon = data.index(b':', idx)
    n = int(data[idx:colon])
    start = colon + 1
    return data[start:start + n], start + n


def parse_torrent_files(path: Path) -> list[dict]:
    """Parse a .torrent file → list of file records.

    Returns: [{stem, basename, select_index, size, path_in_torrent}]
    """
    raw = path.read_bytes()
    t, _ = bdecode(raw)
    info = t.get(b'info', {})
    result: list[dict] = []
    if b'files' not in info:
        name = info.get(b'name', b'').decode('utf-8', errors='replace')
        length = info.get(b'length', 0) or 0
        stem = re.sub(r'\.[^.]+$', '', name)
        if stem:
            result.append({
                "stem": stem, "basename": name, "select_index": 1,
                "size": length, "path_in_torrent": name,
            })
        return result
    idx = 1
    for f in info[b'files']:
        full = b'/'.join(f[b'path']).decode('utf-8', errors='replace')
        length = f.get(b'length', 0) or 0
        # Skip BEP 47 pad files
        if full.startswith('.pad/') or '/.pad/' in full:
            idx += 1
            continue
        basename = full.rsplit('/', 1)[-1]
        if not basename:
            idx += 1
            continue
        stem = re.sub(r'\.[^.]+$', '', basename)
        if stem:
            result.append({
                "stem": stem, "basename": basename, "select_index": idx,
                "size": length, "path_in_torrent": full,
            })
        idx += 1
    return result


# ── DAT file parser ───────────────────────────────────────────────────────────
COLLECTION_NO_INTRO = "No-Intro"
COLLECTION_REDUMP = "Redump"
COLLECTION_RETRO_ACHIEVEMENTS = "RetroAchievements"


@dataclass(frozen=True)
class DatEntry:
    """A single rom entry from a DAT file."""
    filename: str
    size: int


@dataclass(frozen=True)
class DatInfo:
    """Parsed DAT file metadata and entries."""
    entries: tuple[DatEntry, ...]
    name: str | None
    collection: str | None
    system: str | None


def parse_dat_file(path: Path) -> DatInfo:
    """Parse a No-Intro / Redump / RetroAchievements DAT XML file.

    Args:
        path: Path to the .dat file.

    Returns:
        DatInfo with entries and inferred metadata.

    Raises:
        FileNotFoundError: If path doesn't exist.
        ET.ParseError: If the file isn't valid XML.
    """
    if not path.exists():
        raise FileNotFoundError(f"DAT file not found: {path}")

    tree = ET.parse(path)
    root = tree.getroot()
    header = root.find("header")

    dat_name: str | None = None
    collection: str | None = None
    system: str | None = None
    clean_dat_name: str | None = None
    clean_path_name: str | None = _clean_dat_system_name(path.stem)

    if header is not None:
        name_elem = header.find("name")
        if name_elem is not None and name_elem.text:
            dat_name = name_elem.text.strip()
            clean_dat_name = _clean_dat_system_name(dat_name)

        # Infer collection from URL
        url_elem = header.find("url")
        if url_elem is not None and url_elem.text:
            dat_url = url_elem.text.strip().lower()
            if "redump.org" in dat_url:
                collection = COLLECTION_REDUMP
                system = clean_dat_name or clean_path_name or dat_name
            elif "no-intro.org" in dat_url or "no-intro" in dat_url:
                collection = COLLECTION_NO_INTRO
                system = clean_dat_name or clean_path_name or dat_name
            elif "retroachievements.org" in dat_url:
                collection = COLLECTION_RETRO_ACHIEVEMENTS
                system = clean_dat_name or clean_path_name or dat_name

        # RA detection by homepage
        homepage_elem = header.find("homepage")
        if homepage_elem is not None and homepage_elem.text:
            if "retroachievements.org" in homepage_elem.text.strip().lower():
                collection = COLLECTION_RETRO_ACHIEVEMENTS
                system = clean_dat_name or clean_path_name or dat_name

        # Fallback from dat_name
        if collection is None and dat_name:
            lower = dat_name.lower()
            if "no-intro" in lower or "no intro" in lower:
                collection = COLLECTION_NO_INTRO
            elif "redump" in lower:
                collection = COLLECTION_REDUMP
            elif "retroachievements" in lower or "ra - " in lower:
                collection = COLLECTION_RETRO_ACHIEVEMENTS

        if system is None:
            system = clean_dat_name or clean_path_name or dat_name

    entries: list[DatEntry] = []
    for game in root.iter("game"):
        for rom in game.iter("rom"):
            fname = (rom.get("name") or "").strip()
            size_str = (rom.get("size") or "").strip()
            if fname:
                try:
                    size = int(size_str) if size_str else 0
                except ValueError:
                    size = 0
                entries.append(DatEntry(filename=fname, size=size))

    return DatInfo(
        entries=tuple(entries),
        name=dat_name,
        collection=collection,
        system=system,
    )


# ── RomVault CSV parser ──────────────────────────────────────────────────────
_RV_NAME_COLS = frozenset({"name", "game", "file", "filename", "rom", "title"})
_RV_STATUS_COLS = frozenset({"status", "result", "fix", "state"})
_RV_SIZE_COLS = frozenset({"size", "bytes", "length", "filesize"})


def parse_rv_fix_csv(path: Path) -> DatInfo:
    """Parse a RomVault CSV fix report.

    Auto-detects column layout from header row and filters to
    entries that need fixing (status == Missing, Fix, etc.).

    Args:
        path: Path to the .csv file.

    Returns:
        DatInfo with extracted rom entries.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return DatInfo(entries=(), name=path.stem, collection=None, system=None)

    header = lines[0]
    try:
        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(header)
        has_header = sniffer.has_header(header)
    except csv.Error:
        dialect = csv.excel
        has_header = False

    reader = csv.reader(lines, dialect=dialect)
    rows = list(reader)

    if has_header:
        cols = rows[0]
        data_rows = rows[1:]
    else:
        cols = []
        data_rows = rows

    # Find column indices
    name_idx = -1
    status_idx = -1
    sz_idx = -1
    for i, c in enumerate(cols):
        cl = c.strip().lower()
        if cl in _RV_NAME_COLS:
            name_idx = i
        elif cl in _RV_STATUS_COLS:
            status_idx = i
        elif cl in _RV_SIZE_COLS:
            sz_idx = i

    entries: list[DatEntry] = []
    for row in data_rows:
        if not row:
            continue

        # Filter by status if status column is present
        if status_idx >= 0 and status_idx < len(row):
            status = row[status_idx].strip().lower()
            if status and not _is_fix_status(status):
                continue

        # Extract filename
        fname = ""
        if name_idx >= 0 and name_idx < len(row):
            fname = row[name_idx].strip()
        elif not cols and row:
            fname = row[0].strip()

        if not fname:
            continue
        fname = fname.strip('"\' \t')
        if not fname or fname.startswith("#") or fname.startswith("//"):
            continue

        # Handle unquoted commas inside parens (re-merge split columns)
        local_sz = sz_idx
        if "(" in fname:
            merges = 0
            paren_diff = fname.count("(") - fname.count(")")
            merge_from = name_idx + 1 if name_idx >= 0 else 1
            while paren_diff > 0 and merge_from < len(row):
                fname += "," + row[merge_from]
                paren_diff = fname.count("(") - fname.count(")")
                merge_from += 1
                merges += 1
            if merges and local_sz >= 0 and local_sz > name_idx:
                local_sz += merges

        # Extract size
        size = 0
        if local_sz is not None and local_sz >= 0 and local_sz < len(row):
            try:
                size = int(row[local_sz].strip())
            except ValueError:
                size = 0

        entries.append(DatEntry(filename=fname, size=size))

    return DatInfo(
        entries=tuple(entries),
        name=path.stem,
        collection=None,
        system=None,
    )


def _is_fix_status(status: str) -> bool:
    """Return True if the status indicates a file that needs fixing."""
    status = status.lower()
    fix_markers = (
        "missing", "not found", "fix", "mismatch",
        "bad", "wrong", "incomplete", "incorrect", "size", "crc",
    )
    return any(marker in status for marker in fix_markers)


# ── Title normalization & matching ──────────────────────────────────────────
_PAREN_STRIP = re.compile(r"\s*\([^)]*\)")
_PUNCT = re.compile(r"[.,!?;:'\"`]+")
_BROS = re.compile(r"\bbrothers\b", re.IGNORECASE)

_DAT_PREFIX = re.compile(r"(?i)^fixdat[_\s-]*")
_DAT_DATE_SUFFIX = re.compile(
    r"\s*\((?:\d{8}-\d{6}|\d{4}-\d{2}-\d{2}(?:[ T]\d{2}[-:]\d{2}[-:]\d{2})?)\)$"
)
_DAT_META_SUFFIX = re.compile(
    r"\s*\((?:Retool[^)]*|Fresh1G1R[^)]*|No-Intro[^)]*|Redump[^)]*|MAMERedump[^)]*|Hearto[^)]*)\)$",
    re.IGNORECASE,
)

# Known No-Intro/Redump category tags found in filename parens
KNOWN_TAGS = frozenset({
    "aftermarket", "alt", "bad", "beta", "bios", "bizarre", "classi",
    "cracked", "demo", "debug", "enhancement", "homebrew", "inventory",
    "pirate", "preproduction", "promo", "prototype", "private", "sample",
    "sec", "trainer", "translation", "unl", "versus",
})

_TAG_RE = re.compile(r"\(([A-Za-z][A-Za-z0-9 .]{1,30})\)")


def extract_tags(stem: str) -> set[str]:
    """Extract known category tags from a filename stem.

    Tags appear in parentheses in standard ROM naming, e.g.
    ``Super Mario Bros (World) (Aftermarket).gb`` → ``{"aftermarket"}``.

    Returns:
        Set of lowercase known tag names found in the stem.
    """
    matches = _TAG_RE.findall(stem)
    return {m.lower().strip() for m in matches if m.lower().strip() in KNOWN_TAGS}


# Stopwords for keyword extraction
_STOPWORDS = frozenset({
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or",
    "with", "by", "from", "is", "as", "but", "edition", "ver", "version",
    "rev", "prototype", "proto", "sample", "demo", "beta", "aftermarket",
    "unl", "homebrew", "private", "np", "kiosk",
    "world", "usa", "europe", "japan", "germany", "france", "spain",
    "italy", "netherlands", "australia", "canada", "brazil", "china",
    "taiwan", "korea", "russia",
    "sgb", "gb", "gba", "nes", "snes", "n64", "ps1", "ps2", "psp",
    "enhanced", "compatible", "multiboot", "play", "yan", "video",
    "ereader", "bll", "lnx", "lyx", "a78", "bin", "cof", "j64", "jag",
    "abs", "rom", "en", "fr", "de", "es", "it", "nl", "pt", "sv", "da",
    "fi", "no", "rumble",
})


def stem_from_romname(name: str) -> str:
    """Strip extension and lowercase → stem for DB lookup."""
    return re.sub(r"\.[^.]+$", "", name).lower()


def _clean_dat_system_name(label: str | None) -> str | None:
    """Normalize DAT labels into a usable system name.

    Strips common fixDat prefixes and trailing metadata such as retool tags,
    release labels, and date stamps.
    """
    if not label:
        return None

    cleaned = label.strip()
    cleaned = _DAT_PREFIX.sub("", cleaned)

    while True:
        new = _DAT_DATE_SUFFIX.sub("", cleaned)
        new = _DAT_META_SUFFIX.sub("", new)
        new = new.strip()
        if new == cleaned:
            break
        cleaned = new

    cleaned = cleaned.strip(" _-")
    return cleaned or None


def core_title(stem: str) -> str:
    """Extract the title core: strip parens, punctuation, normalize articles.

    Examples:
        'the legend of zelda, the - link\\'s awakening dx (usa, europe)'
          → 'legend of zelda the links awakening dx'
        'super mario bros. deluxe (usa, europe)'
          → 'super mario bros deluxe'
    """
    s = _PAREN_STRIP.sub("", stem).strip()
    s = _BROS.sub("bros", s)
    s = _PUNCT.sub("", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    # Normalize "The" placement
    if s.startswith("the "):
        s = s[4:] + " the"
    s = re.sub(r", the$", " the", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(" & ", " and ")
    return s


def title_keywords(stem: str) -> set[str]:
    """Extract significant keyword set from a stem (no parens, no stopwords)."""
    core = core_title(stem)
    words = set(re.findall(r"[a-z0-9]+", core))
    return {w for w in words if len(w) >= MIN_KEYWORD_LEN and w not in _STOPWORDS}


def fts_escape(term: str) -> str:
    """Escape a term for safe use in FTS5 MATCH query."""
    # FTS5 syntax: quote terms that contain special chars
    return f'"{term.replace(chr(34), chr(34)+chr(34))}"'


def stems_match(a_stem: str, b_stem: str) -> bool:
    """Check if two stems refer to the same game title.

    Tries exact, core_title, and keyword overlap.
    """
    if a_stem == b_stem:
        return True
    ca, cb = core_title(a_stem), core_title(b_stem)
    if ca == cb:
        return True
    ka, kb = title_keywords(a_stem), title_keywords(b_stem)
    if not ka or not kb:
        return False
    overlap = ka & kb
    longer = max(len(ka), len(kb))
    if longer == 0:
        return False
    if len(overlap) / longer >= FUZZY_KEYWORD_OVERLAP_THRESHOLD:
        return True
    if len(overlap) >= 3 and (overlap == ka or overlap == kb):
        return True
    return False


def extract_regions(stem: str) -> set[str]:
    """Extract region tags from a filename stem.

    Parses parenthesized region codes: (USA), (Europe), (Japan), etc.
    Returns a set of lowercase region codes.
    """
    regions: set[str] = set()
    for part in re.findall(r'\(([^)]+)\)', stem):
        part_clean = part.strip().lower()
        known = {
            "usa", "europe", "japan", "world", "asia", "australia",
            "brazil", "china", "france", "germany", "greece",
            "hong kong", "italy", "korea", "netherlands", "russia",
            "scandinavia", "spain", "sweden", "taiwan", "ukraine",
            "united kingdom", "usa & europe", "usa/europe", "usa+europe",
            "world & usa/europe",
        }
        if part_clean in known:
            regions.add(part_clean)
    return regions


def _backfill_facets(conn: sqlite3.Connection, batch_size: int = 10_000) -> None:
    """Populate v3 tag and region tables without loading the full index."""
    cursor = conn.execute("SELECT id, stem FROM files ORDER BY id")
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        tag_rows: list[tuple[int, str]] = []
        region_rows: list[tuple[int, str]] = []
        for file_id, stem in rows:
            tag_rows.extend((file_id, tag) for tag in extract_tags(stem))
            region_rows.extend((file_id, region) for region in extract_regions(stem))
        if tag_rows:
            conn.executemany(
                "INSERT OR IGNORE INTO file_tags (file_id, tag) VALUES (?, ?)",
                tag_rows,
            )
        if region_rows:
            conn.executemany(
                "INSERT OR IGNORE INTO file_regions (file_id, region) VALUES (?, ?)",
                region_rows,
            )


def resolve_match_scope(
    dat_collection: str | None,
    dat_system: str | None,
    ui_collection: str = "",
    ui_system: str = "",
) -> tuple[str, str]:
    """Resolve match scope, preferring explicit user filters.

    A user-selected filter from the UI wins when it is non-empty and not
    the sentinel ``"All"``. Otherwise, fall back to the collection/system
    inferred from the DAT/XML header by ``parse_dat_file``.

    This prevents cross-system false positives like a GBA fix DAT matching
    a 3DS title when the UI filter is set to "All".

    Returns:
        (collection, system) — both empty strings mean "no scope".
    """
    def _pick(ui: str, dat: str | None) -> str:
        if ui and ui != "All":
            return ui
        return dat or ""
    return _pick(ui_collection, dat_collection), _pick(ui_system, dat_system)


# ── LRU Cache ────────────────────────────────────────────────────────────────
class LRUCache:
    """Simple LRU cache with TTL.

    Not thread-safe. Use one per thread.
    """

    def __init__(self, max_entries: int = CACHE_MAX_ENTRIES, ttl: int = CACHE_TTL_SECONDS):
        self._max = max_entries
        self._ttl = ttl
        self._data: dict = {}
        self._order: list = []  # insertion order (LRU at front)
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple) -> Any | None:
        """Get a value. Returns (value, expiry_time) or None."""
        if key in self._data:
            value, expiry = self._data[key]
            if time.time() < expiry:
                # Move to back (most recently used)
                self._order.remove(key)
                self._order.append(key)
                self.hits += 1
                return value
            # Expired
            del self._data[key]
            self._order.remove(key)
        self.misses += 1
        return None

    def put(self, key: tuple, value: Any) -> None:
        """Store a value. Evicts oldest if at capacity."""
        if key in self._data:
            self._order.remove(key)
        elif len(self._order) >= self._max:
            # Evict LRU
            oldest = self._order.pop(0)
            del self._data[oldest]
        expiry = time.time() + self._ttl
        self._data[key] = (value, expiry)
        self._order.append(key)

    def clear(self) -> None:
        self._data.clear()
        self._order.clear()
        self.hits = 0
        self.misses = 0

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "size": len(self._data),
            "capacity": self._max,
            "hit_rate": self.hits / total if total else 0.0,
        }


# ── SQLite schema and migration ─────────────────────────────────────────────
SCHEMA_V2 = """
-- Schema version
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', '2');
INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('created', datetime('now'));

-- Main files table
CREATE TABLE files (
    id INTEGER PRIMARY KEY,
    stem TEXT NOT NULL,
    basename TEXT NOT NULL,
    torrent TEXT NOT NULL,
    select_idx INTEGER NOT NULL,
    size INTEGER NOT NULL,
    path_full TEXT NOT NULL,
    collection TEXT NOT NULL,
    system TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_files_unique ON files(torrent, select_idx);
CREATE INDEX idx_files_stem ON files(stem);
CREATE INDEX idx_files_collection ON files(collection);
CREATE INDEX idx_files_system ON files(system);
CREATE INDEX idx_files_coll_sys ON files(collection, system);
CREATE INDEX idx_files_size ON files(size);

-- FTS5 full-text search on stems
CREATE VIRTUAL TABLE files_fts USING fts5(
    stem,
    content='files',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- FTS5 trigram for substring matching
CREATE VIRTUAL TABLE files_trigram USING fts5(
    stem,
    content='files',
    content_rowid='id',
    tokenize='trigram'
);

-- Sync triggers for FTS5
CREATE TRIGGER files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, stem) VALUES (new.id, new.stem);
    INSERT INTO files_trigram(rowid, stem) VALUES (new.id, new.stem);
END;

CREATE TRIGGER files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, stem) VALUES('delete', old.id, old.stem);
    INSERT INTO files_trigram(files_trigram, rowid, stem) VALUES('delete', old.id, old.stem);
END;

CREATE TRIGGER files_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, stem) VALUES('delete', old.id, old.stem);
    INSERT INTO files_fts(rowid, stem) VALUES (new.id, new.stem);
    INSERT INTO files_trigram(files_trigram, rowid, stem) VALUES('delete', old.id, old.stem);
    INSERT INTO files_trigram(rowid, stem) VALUES (new.id, new.stem);
END;

-- Torrents table
CREATE TABLE torrents (
    name TEXT PRIMARY KEY,
    collection TEXT NOT NULL,
    system TEXT NOT NULL,
    file_count INTEGER NOT NULL
);
CREATE INDEX idx_torrents_coll_sys ON torrents(collection, system);
"""

SCHEMA_V3 = SCHEMA_V2 + """
CREATE TABLE IF NOT EXISTS file_tags (
    file_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY(file_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_file_tags_tag_file
    ON file_tags(tag, file_id);

CREATE TABLE IF NOT EXISTS file_regions (
    file_id INTEGER NOT NULL,
    region TEXT NOT NULL,
    PRIMARY KEY(file_id, region)
);
CREATE INDEX IF NOT EXISTS idx_file_regions_region_file
    ON file_regions(region, file_id);

CREATE TABLE IF NOT EXISTS index_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    torrent_count INTEGER NOT NULL DEFAULT 0,
    file_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    elapsed_ms INTEGER
);

INSERT OR REPLACE INTO schema_meta (key, value)
VALUES ('schema_version', '3');
"""

# v1 schema (for migration)
SCHEMA_V1 = """
CREATE TABLE files (
    stem TEXT NOT NULL,
    basename TEXT NOT NULL,
    torrent TEXT NOT NULL,
    select_idx INTEGER NOT NULL,
    size INTEGER NOT NULL,
    path_full TEXT NOT NULL,
    collection TEXT NOT NULL,
    system TEXT NOT NULL
);
CREATE INDEX idx_files_stem ON files(stem);
CREATE INDEX idx_files_coll ON files(collection);
CREATE INDEX idx_files_sys ON files(system);
CREATE TABLE torrents (
    name TEXT PRIMARY KEY,
    collection TEXT NOT NULL,
    system TEXT NOT NULL,
    file_count INTEGER NOT NULL
);
"""


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Detect the schema version of the database. Returns 0 if unknown."""
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row:
            return int(row[0])
    except sqlite3.OperationalError:
        pass
    # Heuristic: check for v1 tables
    try:
        conn.execute("SELECT 1 FROM files LIMIT 1")
        conn.execute("SELECT 1 FROM torrents LIMIT 1")
        return 1
    except sqlite3.OperationalError:
        return 0


def build_index(
    torrent_dir: Path = DEFAULT_TORRENT_DIR,
    index_path: Path = DEFAULT_INDEX_PATH,
    *,
    progress_callback: "Callable[[int, int], None] | None" = None,
) -> Path:
    """Build the SQLite index from all .torrent files.

    Args:
        torrent_dir: Directory containing .torrent files.
        index_path: Where to write the SQLite index.
        progress_callback: Optional callback(current, total) invoked after
            each torrent file is processed.

    Returns:
        The path to the created index.
    """
    if not torrent_dir.is_dir():
        raise FileNotFoundError(f"Torrent directory not found: {torrent_dir}")

    files = sorted(torrent_dir.glob("*.torrent"))
    log.info("Building index from %d torrents in %s", len(files), torrent_dir)

    if index_path.exists():
        log.info("Removing existing index: %s", index_path)
        index_path.unlink()

    conn = sqlite3.connect(str(index_path))
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA cache_size = -8000000")  # 8 MB cache

    # Apply the current schema directly for newly-built indexes.
    conn.executescript(SCHEMA_V3)
    run_started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    run_id = conn.execute(
        "INSERT INTO index_runs (started_at, status) VALUES (?, 'running')",
        (run_started,),
    ).lastrowid

    def extract_cs(name: str) -> tuple[str, str]:
        inner = name.replace(".torrent", "", 1)
        if inner.startswith("Minerva_Myrient - "):
            inner = inner[len("Minerva_Myrient - "):]
        parts = inner.split(" - ", 1)
        return parts[0] if parts else "Unknown", (parts[1] if len(parts) > 1 else name)

    total = errors = 0
    t0 = time.time()
    for tf in files:
        try:
            entries = parse_torrent_files(tf)
            if not entries:
                if progress_callback is not None:
                    progress_callback(files.index(tf) + 1, len(files))
                continue
            coll, sys_name = extract_cs(tf.name)
            rows = [
                (e["stem"].lower(), e["basename"], tf.name,
                 e["select_index"], e["size"], e["path_in_torrent"],
                 coll, sys_name)
                for e in entries
            ]
            conn.executemany(
                "INSERT INTO files (stem, basename, torrent, select_idx, size, path_full, collection, system) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
            conn.execute(
                "INSERT OR REPLACE INTO torrents (name, collection, system, file_count) "
                "VALUES (?, ?, ?, ?)",
                (tf.name, coll, sys_name, len(entries)))

            # Populate v3 facets while the torrent-sized working set is small.
            inserted = conn.execute(
                "SELECT id, stem FROM files WHERE torrent = ?",
                (tf.name,),
            ).fetchall()
            tag_rows: list[tuple[int, str]] = []
            region_rows: list[tuple[int, str]] = []
            for inserted_row in inserted:
                file_id = inserted_row[0]
                stem = inserted_row[1]
                tag_rows.extend((file_id, tag) for tag in extract_tags(stem))
                region_rows.extend((file_id, region) for region in extract_regions(stem))
            if tag_rows:
                conn.executemany(
                    "INSERT OR IGNORE INTO file_tags (file_id, tag) VALUES (?, ?)",
                    tag_rows,
                )
            if region_rows:
                conn.executemany(
                    "INSERT OR IGNORE INTO file_regions (file_id, region) VALUES (?, ?)",
                    region_rows,
                )
            total += len(entries)
        except Exception as e:
            log.error("Failed to parse %s: %s", tf.name, e)
            errors += 1
        finally:
            if progress_callback is not None:
                progress_callback(files.index(tf) + 1, len(files))

    elapsed = time.time() - t0
    conn.execute(
        """
        UPDATE index_runs
        SET completed_at = ?, status = 'completed', torrent_count = ?,
            file_count = ?, error_count = ?, elapsed_ms = ?
        WHERE id = ?
        """,
        (
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            len(files), total, errors, int(elapsed * 1000), run_id,
        ),
    )
    conn.commit()

    # Stats
    unique_stems = conn.execute(
        "SELECT COUNT(DISTINCT stem) FROM files").fetchone()[0]
    torrent_count = conn.execute(
        "SELECT COUNT(*) FROM torrents").fetchone()[0]
    fts_count = conn.execute(
        "SELECT COUNT(*) FROM files_fts").fetchone()[0]

    log.info(
        "Built index: %d files, %d torrents, %d unique stems, %d FTS entries in %.1fs",
        total, torrent_count, unique_stems, fts_count, elapsed)
    if errors:
        log.warning("%d torrents had parse errors", errors)

    size_mb = index_path.stat().st_size / 1024 / 1024
    log.info("Index file: %s (%.1f MB)", index_path, size_mb)

    conn.close()
    return index_path


def migrate_v1_to_v2(index_path: Path) -> None:
    """Migrate a v1 index to v2 schema in-place.

    Adds id column, FTS5 tables, and triggers. This is destructive
    (rebuilds the table) but preserves all data.
    """
    log.info("Migrating %s from v1 to v2", index_path)
    conn = sqlite3.connect(str(index_path))
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")

    # Read all v1 data
    rows = conn.execute(
        "SELECT stem, basename, torrent, select_idx, size, path_full, collection, system "
        "FROM files"
    ).fetchall()
    torrent_rows = conn.execute(
        "SELECT name, collection, system, file_count FROM torrents"
    ).fetchall()

    log.info("Migrating %d file rows + %d torrent rows", len(rows), len(torrent_rows))

    # Drop all v1 tables
    conn.executescript("""
        DROP TABLE IF EXISTS files;
        DROP TABLE IF EXISTS torrents;
        DROP INDEX IF EXISTS idx_files_stem;
        DROP INDEX IF EXISTS idx_files_coll;
        DROP INDEX IF EXISTS idx_files_sys;
    """)

    # Apply the current schema directly for newly-built indexes.
    conn.executescript(SCHEMA_V3)
    run_started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    run_id = conn.execute(
        "INSERT INTO index_runs (started_at, status) VALUES (?, 'running')",
        (run_started,),
    ).lastrowid

    # Re-insert data
    if rows:
        conn.executemany(
            "INSERT INTO files (id, stem, basename, torrent, select_idx, size, path_full, collection, system) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(i + 1,) + r for i, r in enumerate(rows)])
    if torrent_rows:
        conn.executemany(
            "INSERT INTO torrents (name, collection, system, file_count) VALUES (?, ?, ?, ?)",
            torrent_rows)
    _backfill_facets(conn)
    conn.execute(
        """
        UPDATE index_runs
        SET completed_at = ?, status = 'completed', torrent_count = ?,
            file_count = ?, error_count = 0, elapsed_ms = 0
        WHERE id = ?
        """,
        (
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            len(torrent_rows), len(rows), run_id,
        ),
    )

    conn.commit()
    conn.close()
    log.info("Migration complete")


# ── Main database interface ──────────────────────────────────────────────────
@dataclass(frozen=True)
class StemSizeMatch:
    file_id: int
    collection: str
    system: str
    basename: str
    size: int


@dataclass
class MatchResult:
    """Result of matching a single DAT entry against the index."""
    dat_entry: DatEntry
    matched_rows: list[sqlite3.Row] = field(default_factory=list)
    matched_via: str = ""  # "exact", "fts5", "trigram", "keyword"


@dataclass
class MatchReport:
    """Summary of matching an entire DAT against the index."""
    matched: list[sqlite3.Row]            # Unique matched rows (deduplicated)
    matched_stems: set[str]              # Stems that had at least one match
    unmatched: list[DatEntry]            # Entries that didn't match
    results: list[MatchResult]           # Per-entry results
    total_time_ms: float = 0.0

    def __str__(self) -> str:
        return (
            f"MatchReport(matched={len(self.matched)}, "
            f"matched_stems={len(self.matched_stems)}, "
            f"unmatched={len(self.unmatched)}, time={self.total_time_ms:.0f}ms)"
        )


class MinervaDB:
    """Production-grade interface to the Minerva torrent index.

    Thread-safety: Each thread should create its own instance.
    Connection management: opens connections per-call (cheap with SQLite).
    """

    def __init__(
        self,
        db_path: Path | str = DEFAULT_INDEX_PATH,
        cache_max: int = CACHE_MAX_ENTRIES,
        cache_ttl: int = CACHE_TTL_SECONDS,
    ):
        self._path = str(db_path)
        self._cache = LRUCache(max_entries=cache_max, ttl=cache_ttl)
        self._ready = False
        self._validate_schema()
        log.debug("MinervaDB initialized: %s", db_path)

    def conn(self) -> sqlite3.Connection:
        """Open a new connection. Caller is responsible for closing."""
        c = sqlite3.connect(self._path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA mmap_size = 268435456")
        c.execute("PRAGMA temp_store = MEMORY")
        c.execute("PRAGMA cache_size = -8000000")
        return c

    def _validate_schema(self) -> None:
        """Verify the database is at the expected schema version and migrate if needed."""
        try:
            with self.conn() as c:
                self._ensure_schema(c)
                version = get_schema_version(c)
                if version > SCHEMA_VERSION:
                    log.warning(
                        "Database at schema v%d, newer than expected v%d. Some features may not work.",
                        version, SCHEMA_VERSION)
                else:
                    log.debug("Schema v%d OK", version)
                # Ensure filter-performance indexes exist on existing databases.
                # Skip when the files table is absent (uninitialized DB); a fresh
                # DB gets its full schema from build_index(), not from here.
                if c.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='files'"
                ).fetchone():
                    self._ready = True
                    c.execute("CREATE INDEX IF NOT EXISTS idx_files_collection ON files(collection)")
                    c.execute("CREATE INDEX IF NOT EXISTS idx_files_system ON files(system)")
        except sqlite3.OperationalError as e:
            log.error("Cannot open database: %s", e)
            raise

    # ── Schema migration ───────────────────────────────────────────────────

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        """Run schema migrations if needed.

        Checks the current schema version and applies any pending migrations.
        """
        version = get_schema_version(conn)
        if version < SCHEMA_VERSION:
            if version == 2:
                self._migrate_v2_to_v3(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO schema_meta (key, value) "
                    "VALUES ('schema_version', '3')"
                )
                conn.commit()
                log.info("Schema migrated from v2 to v3")
            else:
                log.warning(
                    "Database at schema v%d, expected v%d. Run build_index() to upgrade.",
                    version, SCHEMA_VERSION)

    def _migrate_v2_to_v3(self, conn: sqlite3.Connection) -> None:
        """Migrate schema from v2 to v3: add file_tags, file_regions, index_runs."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_tags (
                file_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                PRIMARY KEY(file_id, tag)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_file_tags_tag_file "
            "ON file_tags(tag, file_id)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_regions (
                file_id INTEGER NOT NULL,
                region TEXT NOT NULL,
                PRIMARY KEY(file_id, region)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_file_regions_region_file "
            "ON file_regions(region, file_id)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS index_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                torrent_count INTEGER NOT NULL DEFAULT 0,
                file_count INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                elapsed_ms INTEGER
            )
        """)
        _backfill_facets(conn)
        conn.execute("PRAGMA user_version = 3")

    # ── Public API ─────────────────────────────────────────────────────────
    def get_collections(self) -> list[str]:
        """Return sorted list of distinct collections."""
        if not self._ready: return []
        with self.conn() as c:
            rows = c.execute(
                "SELECT DISTINCT collection FROM files ORDER BY collection"
            ).fetchall()
            return [r["collection"] for r in rows]

    def get_collection_system_pairs(self) -> list[tuple[str, str]]:
        """Return all distinct (collection, system) pairs sorted by collection then system."""
        if not self._ready: return []
        with self.conn() as c:
            rows = c.execute(
                "SELECT DISTINCT collection, system FROM files ORDER BY collection, system"
            ).fetchall()
            return [(r["collection"], r["system"]) for r in rows]

    def get_systems(self, collection: str | None = None) -> list[str]:
        """Return sorted list of distinct systems, optionally filtered by collection."""
        if not self._ready: return []
        with self.conn() as c:
            if collection:
                rows = c.execute(
                    "SELECT DISTINCT system FROM files WHERE collection = ? ORDER BY system",
                    (collection,)).fetchall()
            else:
                rows = c.execute(
                    "SELECT DISTINCT system FROM files ORDER BY system").fetchall()
            return [r["system"] for r in rows]

    def get_tags(self) -> list[str]:
        """Return sorted list of distinct tags from the file_tags table."""
        if not self._ready: return []
        with self.conn() as c:
            rows = c.execute(
                "SELECT DISTINCT tag FROM file_tags ORDER BY tag"
            ).fetchall()
            return [r["tag"] for r in rows]

    def search(
        self,
        query: str = "",
        collection: str = "",
        system: str = "",
        limit: int = 500,
        offset: int = 0,
    ) -> tuple[list[sqlite3.Row], int]:
        """Search the file index by stem substring.

        Returns:
            (rows, total_count)
        """
        q = query.strip().lower()
        filters: list[str] = []
        filter_params: list = []
        if collection:
            filters.append("collection = ?")
            filter_params.append(collection)
        if system:
            filters.append("system = ?")
            filter_params.append(system)

        def _apply_filters(base_sql: str) -> tuple[str, list]:
            if filters:
                return f"{base_sql} AND {' AND '.join(filters)}", filter_params.copy()
            return base_sql, []

        with self.conn() as c:
            if q and len(q) >= 3:
                # Fast path: trigram FTS handles substring searches without a full scan.
                match_expr = fts_escape(q)
                count_sql, count_params = _apply_filters(
                    "SELECT COUNT(*) FROM files WHERE id IN (SELECT rowid FROM files_trigram WHERE files_trigram MATCH ?)"
                )
                total = c.execute(count_sql, [match_expr, *count_params]).fetchone()[0]
                rows_sql, rows_params = _apply_filters(
                    "SELECT * FROM files WHERE id IN (SELECT rowid FROM files_trigram WHERE files_trigram MATCH ?)"
                )
                rows = c.execute(
                    f"{rows_sql} ORDER BY size DESC LIMIT ? OFFSET ?",
                    [match_expr, *rows_params, limit, offset],
                ).fetchall()
                return rows, total

            # Small or empty queries: fall back to LIKE (cheap enough for the
            # very small candidate set a 1-2 character query would otherwise match).
            where: list[str] = []
            params: list = []
            if q:
                where.append("stem LIKE ?")
                params.append(f"%{q}%")
            where.extend(filters)
            params.extend(filter_params)
            w = " AND ".join(where) if where else "1=1"
            total = c.execute(
                f"SELECT COUNT(*) FROM files WHERE {w}", params
            ).fetchone()[0]
            rows = c.execute(
                f"SELECT * FROM files WHERE {w} ORDER BY size DESC LIMIT ? OFFSET ?",
                [*params, limit, offset]).fetchall()
            return rows, total

    # ── Tag-based search ──────────────────────────────────────────────────────

    def search_by_tags(
        self,
        tags: list[str] | None = None,
        systems: list[str] | None = None,
        collection: str = "",
        query: str = "",
        min_size: int = 0,
        max_size: int = 0,
        limit: int = 0,
        offset: int = 0,
    ) -> tuple[list[sqlite3.Row], int]:
        """Search the index for files matching tags and optional filters.

        Tags are extracted from filename stems, e.g. ``(Aftermarket)``.
        Uses FTS5 trigram for fast substring matching.

        Args:
            tags: Filter by known category tags (OR logic).
            systems: Filter by system name (OR logic).
            collection: Optional collection filter.
            query: Optional title substring filter.
            min_size: Minimum size in bytes (0 = no minimum).
            max_size: Maximum size in bytes (0 = no maximum).
            limit: Max rows (0 = no limit).
            offset: Pagination offset.

        Returns:
            (rows, total_count)
        """
        has_any_filter = bool(tags or systems or collection or query or min_size or max_size)
        if not has_any_filter:
            return self.search(limit=limit, offset=offset)

        with self.conn() as c:
            # Step 1: collect matching rowids from trigram for tags/query.
            rowid_filters: list[list[int]] = []
            for tag in tags or []:
                tag_clean = tag.lower().strip("()")
                escaped = fts_escape(tag_clean)
                rowids = c.execute(
                    "SELECT rowid FROM files_trigram WHERE files_trigram MATCH ?",
                    (escaped,),
                ).fetchall()
                ids = [r[0] for r in rowids]
                if not ids:
                    return [], 0
                rowid_filters.append(ids)

            q = query.strip().lower()
            if q and len(q) >= 3:
                escaped = fts_escape(q)
                rowids = c.execute(
                    "SELECT rowid FROM files_trigram WHERE files_trigram MATCH ?",
                    (escaped,),
                ).fetchall()
                ids = [r[0] for r in rowids]
                if not ids:
                    return [], 0
                rowid_filters.append(ids)

            # Step 2: build filter query.
            parts: list[str] = []
            params: list[Any] = []

            if rowid_filters:
                ids = set(rowid_filters[0])
                for subset in rowid_filters[1:]:
                    ids &= set(subset)
                if not ids:
                    return [], 0
                sorted_ids = sorted(ids)
                placeholders = ",".join("?" * len(sorted_ids))
                parts.append(f"id IN ({placeholders})")
                params.extend(sorted_ids)

            if systems:
                sys_placeholders = ",".join("?" * len(systems))
                parts.append(f"system IN ({sys_placeholders})")
                params.extend(systems)

            if collection:
                parts.append("collection = ?")
                params.append(collection)

            if min_size > 0:
                parts.append("size >= ?")
                params.append(min_size)

            if max_size > 0:
                parts.append("size <= ?")
                params.append(max_size)

            if q and len(q) < 3:
                parts.append("stem LIKE ?")
                params.append(f"%{q}%")

            where = " AND ".join(parts) if parts else "1=1"

            total = c.execute(
                f"SELECT COUNT(*) FROM files WHERE {where}", params
            ).fetchone()[0]

            sql = f"SELECT * FROM files WHERE {where} ORDER BY size DESC"
            if limit > 0:
                sql += " LIMIT ? OFFSET ?"
                params.extend([limit, offset])

            rows = c.execute(sql, params).fetchall()
            return rows, total

    def build_synthetic_dat(
        self,
        rows: list[sqlite3.Row],
        dat_name: str = "Synthetic DAT",
        system: str | None = None,
        collection: str | None = None,
    ) -> str:
        """Build a valid logiqx/clrmamepro XML DAT string from index rows.

        The output is compatible with ``parse_dat_file()`` and with retool.

        Args:
            rows: Index rows from ``search_by_tags()`` or similar.
            dat_name: Name for the DAT header.
            system: Optional system label. Included in header if provided.
            collection: Optional collection label. Included in header if provided.

        Returns:
            XML string representing a valid .dat file.
        """
        root = ET.Element("datafile")
        header = ET.SubElement(root, "header")
        ET.SubElement(header, "name").text = dat_name
        if system:
            ET.SubElement(header, "description").text = system
        if collection:
            ET.SubElement(header, "version").text = collection
        ET.SubElement(header, "url").text = "https://no-intro.org/"

        for row in rows:
            game = ET.SubElement(root, "game", name=row["stem"])
            ET.SubElement(game, "description").text = row["stem"]
            ET.SubElement(
                game, "rom",
                name=row["basename"],
                size=str(row["size"]),
            )

        return ET.tostring(root, encoding="unicode", xml_declaration=True)

    # ── DAT matching ──────────────────────────────────────────────────────────

    def match_dat(
        self,
        entries: list[DatEntry] | tuple[DatEntry, ...],
        collection: str = "",
        system: str = "",
        use_cache: bool = True,
    ) -> MatchReport:
        """Match a list of DAT entries against the index.

        Args:
            entries: List of DatEntry objects from a parsed DAT.
            collection: Optional collection scope (e.g. "No-Intro").
            system: Optional system scope (e.g. "Nintendo - Game Boy Color").
            use_cache: Whether to use the LRU cache.

        Returns:
            MatchReport with matched rows, unmatched entries, and per-entry results.
        """
        if not self._ready:
            return MatchReport(matched=[], unmatched=list(entries), results=[])
        t0 = time.time()

        # Check cache
        cache_key = ("match", tuple(e.filename for e in entries), collection, system)
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                log.debug("Cache hit for match_dat (%d entries)", len(entries))
                return cached

        seen: set[tuple[str, int]] = set()
        matched: list[sqlite3.Row] = []
        matched_stems: set[str] = set()
        unmatched: list[DatEntry] = []
        results: list[MatchResult] = []

        # Use a single connection for the whole match — reduces connection
        # open/close overhead from O(entries × 4) to O(1).
        with self.conn() as conn:
            for entry in entries:
                stem = stem_from_romname(entry.filename)
                size = entry.size
                mr = MatchResult(dat_entry=entry)

                # Tier 1: exact stem match
                rows = self._find_by_stem(stem, collection, system, conn, size=size)
                if rows:
                    for r in rows:
                        key = (r["torrent"], r["select_idx"])
                        if key not in seen:
                            seen.add(key)
                            matched.append(r)
                        mr.matched_rows.append(r)
                    mr.matched_via = "exact"
                    matched_stems.add(stem)
                    results.append(mr)
                    continue

                # Tier 2: FTS5 MATCH query
                rows = self._find_by_fts(stem, collection, system, conn, size=size)
                if rows:
                    for r in rows:
                        if stems_match(stem, r["stem"]):
                            key = (r["torrent"], r["select_idx"])
                            if key not in seen:
                                seen.add(key)
                                matched.append(r)
                            mr.matched_rows.append(r)
                            mr.matched_via = "fts5"
                            break

                if mr.matched_rows:
                    matched_stems.add(stem)
                    results.append(mr)
                    continue

                # Tier 3: trigram FTS5 (substring matching)
                rows = self._find_by_trigram(stem, collection, system, conn, size=size)
                if rows:
                    for r in rows:
                        if stems_match(stem, r["stem"]):
                            key = (r["torrent"], r["select_idx"])
                            if key not in seen:
                                seen.add(key)
                                matched.append(r)
                            mr.matched_rows.append(r)
                            mr.matched_via = "trigram"
                            break

                if mr.matched_rows:
                    matched_stems.add(stem)
                    results.append(mr)
                    continue

                # Tier 4: keyword fallback
                rows = self._find_by_keywords(stem, collection, system, conn, size=size)
                if rows:
                    for r in rows:
                        if stems_match(stem, r["stem"]):
                            key = (r["torrent"], r["select_idx"])
                            if key not in seen:
                                seen.add(key)
                                matched.append(r)
                            mr.matched_rows.append(r)
                            mr.matched_via = "keyword"
                            break

                if mr.matched_rows:
                    matched_stems.add(stem)
                else:
                    unmatched.append(entry)
                results.append(mr)

        report = MatchReport(
            matched=matched,
            matched_stems=matched_stems,
            unmatched=unmatched,
            results=results,
            total_time_ms=(time.time() - t0) * 1000,
        )

        if use_cache:
            self._cache.put(cache_key, report)

        log.debug(
            "match_dat: %d entries → %d matched, %d unmatched in %.0fms",
            len(entries), len(matched_stems), len(unmatched), report.total_time_ms)
        return report

    def cache_stats(self) -> dict:
        """Return cache statistics."""
        return self._cache.stats()

    def clear_cache(self) -> None:
        """Clear the query cache."""
        self._cache.clear()

    def get_download_spec(
        self,
        file_id: int,
        torrent_dir: Path = DEFAULT_TORRENT_DIR,
    ) -> "DownloadFileSpec | None":
        """Resolve a file ID into all metadata needed by the downloader."""
        if not _HAS_DOMAIN:
            raise RuntimeError("Domain types not available")
        with self.conn() as c:
            row = c.execute(
                "SELECT * FROM files WHERE id = ?",
                (file_id,),
            ).fetchone()
        if row is None:
            return None
        return DownloadFileSpec(
            file_id=row["id"],
            torrent_name=row["torrent"],
            torrent_path=torrent_dir / row["torrent"],
            select_index=row["select_idx"],
            basename=row["basename"],
            path_in_torrent=row["path_full"],
            size=row["size"],
            collection=row["collection"],
            system=row["system"],
        )

    # ── Typed query API ───────────────────────────────────────────────────

    _SORT_COLUMNS = {
        "stem": "stem",
        "size": "size",
        "collection": "collection",
        "system": "system",
    }

    def _row_to_library_item(
        self,
        row: sqlite3.Row,
        tags: tuple[str, ...] = (),
        regions: tuple[str, ...] = (),
    ) -> "LibraryItem":
        """Convert a sqlite3.Row to a LibraryItem with optional tags/regions."""
        return LibraryItem(
            id=row["id"],
            stem=row["stem"],
            basename=row["basename"],
            collection=row["collection"],
            system=row["system"],
            size=row["size"],
            source_torrent=row["torrent"],
            source_index=row["select_idx"],
            path_in_torrent=row["path_full"],
            tags=tags,
            regions=regions,
        )

    def _load_tags_for_files(
        self, c: sqlite3.Connection, file_ids: Collection[int],
    ) -> dict[int, tuple[str, ...]]:
        """Batch-load file_tags for the given file IDs."""
        if not file_ids:
            return {}
        ids = sorted(set(file_ids))
        placeholders = ",".join("?" * len(ids))
        result: dict[int, list[str]] = {fid: [] for fid in ids}
        for row in c.execute(
            f"SELECT file_id, tag FROM file_tags "
            f"WHERE file_id IN ({placeholders}) ORDER BY tag",
            ids,
        ):
            result.setdefault(row["file_id"], []).append(row["tag"])
        return {fid: tuple(tags) for fid, tags in result.items()}

    def _load_regions_for_files(
        self, c: sqlite3.Connection, file_ids: Collection[int],
    ) -> dict[int, tuple[str, ...]]:
        """Batch-load file_regions for the given file IDs."""
        if not file_ids:
            return {}
        ids = sorted(set(file_ids))
        placeholders = ",".join("?" * len(ids))
        result: dict[int, list[str]] = {fid: [] for fid in ids}
        for row in c.execute(
            f"SELECT file_id, region FROM file_regions "
            f"WHERE file_id IN ({placeholders}) ORDER BY region",
            ids,
        ):
            result.setdefault(row["file_id"], []).append(row["region"])
        return {fid: tuple(regions) for fid, regions in result.items()}

    @staticmethod
    def _category_condition(category: str) -> tuple[str, list[Any]]:
        """Return a SQL predicate for a normalised library category."""
        category = category.strip().lower()
        if category == "homebrew":
            return (
                "id IN (SELECT file_id FROM file_tags WHERE tag = 'homebrew')",
                [],
            )
        if category == "demo":
            return (
                "id IN (SELECT file_id FROM file_tags WHERE tag = 'demo')",
                [],
            )
        if category == "tool":
            return (
                "id IN (SELECT file_id FROM file_tags "
                "WHERE tag IN ('debug', 'trainer', 'inventory'))",
                [],
            )
        if category == "game":
            return (
                "id NOT IN (SELECT file_id FROM file_tags "
                "WHERE tag IN ('homebrew', 'demo', 'debug', 'trainer', 'inventory'))",
                [],
            )
        return "1=0", []

    def _build_library_where(
        self,
        query: "LibraryQuery",
        *,
        include_tags: bool = True,
        include_regions: bool = True,
        include_categories: bool = True,
    ) -> tuple[str, list[Any]]:
        """Build a parameterised WHERE clause shared by search and facets."""
        where: list[str] = []
        params: list[Any] = []

        text = query.text.strip().lower()
        if text:
            if len(text) >= 3:
                where.append(
                    "id IN (SELECT rowid FROM files_trigram "
                    "WHERE files_trigram MATCH ?)"
                )
                params.append(fts_escape(text))
            else:
                where.append("stem LIKE ?")
                params.append(f"%{text}%")

        if query.collection:
            where.append("collection = ?")
            params.append(query.collection)
        if query.system:
            where.append("system = ?")
            params.append(query.system)

        if query.file_ids:
            placeholders = ",".join("?" * len(query.file_ids))
            where.append(f"id IN ({placeholders})")
            params.extend(query.file_ids)
        elif query.selected_only:
            where.append("1=0")

        if include_tags:
            for tag in sorted(query.tags):
                where.append(
                    "id IN (SELECT file_id FROM file_tags WHERE tag = ?)"
                )
                params.append(tag)

        if include_regions:
            for region in sorted(query.regions):
                where.append(
                    "id IN (SELECT file_id FROM file_regions WHERE region = ?)"
                )
                params.append(region)

        if include_categories and query.categories:
            category_parts: list[str] = []
            for category in sorted(query.categories):
                predicate, category_params = self._category_condition(category)
                category_parts.append(f"({predicate})")
                params.extend(category_params)
            where.append("(" + " OR ".join(category_parts) + ")")

        return (" AND ".join(where) if where else "1=1"), params

    def search_library(
        self,
        query: "LibraryQuery",
    ) -> tuple[list["LibraryItem"], int]:
        """Search the library with validated sorting and SQL pagination."""
        if not _HAS_DOMAIN:
            raise RuntimeError(
                "Domain types not available — cannot return LibraryItem instances"
            )

        where_clause, params = self._build_library_where(query)
        sort_col = self._SORT_COLUMNS.get(query.sort_field, "stem")
        order = "DESC" if query.descending else "ASC"

        with self.conn() as c:
            total = c.execute(
                f"SELECT COUNT(*) FROM files WHERE {where_clause}", params
            ).fetchone()[0]

            if query.limit <= 0:
                return [], total

            rows = c.execute(
                f"SELECT * FROM files WHERE {where_clause} "
                f"ORDER BY {sort_col} {order}, id ASC "
                f"LIMIT ? OFFSET ?",
                [*params, query.limit, query.offset],
            ).fetchall()
            if not rows:
                return [], total

            ids = [r["id"] for r in rows]
            tag_map = self._load_tags_for_files(c, ids)
            region_map = self._load_regions_for_files(c, ids)
            return [
                self._row_to_library_item(
                    row,
                    tags=tag_map.get(row["id"], ()),
                    regions=region_map.get(row["id"], ()),
                )
                for row in rows
            ], total

    def get_library_facets(self, query: "LibraryQuery") -> "LibraryFacets":
        """Return region, category and tag counts for the current search.

        Each facet dimension is calculated without its own selected values so
        the UI can keep showing alternative choices while another value in the
        same dimension is selected.
        """
        if not _HAS_DOMAIN:
            raise RuntimeError("Domain types not available")

        with self.conn() as c:
            total_where, total_params = self._build_library_where(query)
            total = c.execute(
                f"SELECT COUNT(*) FROM files WHERE {total_where}", total_params
            ).fetchone()[0]

            region_where, region_params = self._build_library_where(
                query, include_regions=False,
            )
            region_rows = c.execute(
                "SELECT fr.region AS value, COUNT(DISTINCT fr.file_id) AS count "
                "FROM file_regions fr JOIN files f ON f.id = fr.file_id "
                f"WHERE {re.sub(r'\\bid\\b', 'f.id', region_where)} "
                "GROUP BY fr.region ORDER BY count DESC, value ASC",
                region_params,
            ).fetchall()

            tag_where, tag_params = self._build_library_where(
                query, include_tags=False,
            )
            tag_rows = c.execute(
                "SELECT ft.tag AS value, COUNT(DISTINCT ft.file_id) AS count "
                "FROM file_tags ft JOIN files f ON f.id = ft.file_id "
                f"WHERE {re.sub(r'\\bid\\b', 'f.id', tag_where)} "
                "GROUP BY ft.tag ORDER BY count DESC, value ASC",
                tag_params,
            ).fetchall()

            category_query = type(query)(
                text=query.text,
                collection=query.collection,
                system=query.system,
                tags=query.tags,
                regions=query.regions,
                categories=frozenset(),
                selected_only=query.selected_only,
                file_ids=query.file_ids,
                offset=0,
                limit=0,
                sort_field=query.sort_field,
                descending=query.descending,
            )
            category_where, category_params = self._build_library_where(
                category_query, include_categories=False,
            )
            category_counts: list[FacetCount] = []
            for category in ("game", "homebrew", "demo", "tool"):
                predicate, predicate_params = self._category_condition(category)
                count = c.execute(
                    "SELECT COUNT(*) FROM files "
                    f"WHERE ({category_where}) AND ({predicate})",
                    [*category_params, *predicate_params],
                ).fetchone()[0]
                category_counts.append(FacetCount(category, count))

        return LibraryFacets(
            total=total,
            regions=tuple(
                FacetCount(row["value"], row["count"]) for row in region_rows
            ),
            categories=tuple(category_counts),
            tags=tuple(
                FacetCount(row["value"], row["count"]) for row in tag_rows
            ),
        )

    def get_files_by_ids(self, file_ids: Collection[int]) -> list["LibraryItem"]:
        """Fetch multiple files by their primary key IDs."""
        if not _HAS_DOMAIN:
            raise RuntimeError("Domain types not available")
        if not self._ready: return []
        if not file_ids:
            return []

        with self.conn() as c:
            ids = sorted(set(file_ids))
            placeholders = ",".join("?" * len(ids))
            rows = c.execute(
                f"SELECT * FROM files WHERE id IN ({placeholders}) ORDER BY id",
                ids,
            ).fetchall()

            tag_map = self._load_tags_for_files(c, ids)
            region_map = self._load_regions_for_files(c, ids)

            return [
                self._row_to_library_item(
                    r,
                    tags=tag_map.get(r["id"], ()),
                    regions=region_map.get(r["id"], ()),
                )
                for r in rows
            ]

    # ── Overview and diagnostics ──────────────────────────────────────────

    def get_index_overview(self) -> "IndexOverview":
        """Return aggregate index statistics."""
        if not _HAS_DOMAIN:
            raise RuntimeError("Domain types not available")
        if not self._ready:
            return IndexOverview(collections=0, systems=0, files=0, database_size=0, last_build=None)

        with self.conn() as c:
            collections = c.execute(
                "SELECT COUNT(DISTINCT collection) FROM files"
            ).fetchone()[0]
            systems = c.execute(
                "SELECT COUNT(DISTINCT system) FROM files"
            ).fetchone()[0]
            files = c.execute("SELECT COUNT(*) FROM files").fetchone()[0]

            # Database file size
            db_path = Path(self._path)
            db_size = db_path.stat().st_size if db_path.exists() else 0

            # Last build from schema_meta
            last_build: datetime.datetime | None = None
            row = c.execute(
                "SELECT value FROM schema_meta WHERE key = 'created'"
            ).fetchone()
            if row and row["value"]:
                try:
                    last_build = datetime.datetime.fromisoformat(row["value"])
                except (ValueError, TypeError):
                    pass

            # Prefer latest completed index_runs if available
            run_row = c.execute(
                "SELECT completed_at FROM index_runs "
                "WHERE status = 'completed' "
                "ORDER BY completed_at DESC LIMIT 1"
            ).fetchone()
            if run_row and run_row["completed_at"]:
                try:
                    last_build = datetime.datetime.fromisoformat(run_row["completed_at"])
                except (ValueError, TypeError):
                    pass

            return IndexOverview(
                collections=collections,
                systems=systems,
                files=files,
                database_size=db_size,
                last_build=last_build,
            )

    def get_collection_summaries(self) -> list["CollectionSummary"]:
        """Return per-collection summary rows."""
        if not _HAS_DOMAIN:
            raise RuntimeError("Domain types not available")
        if not self._ready: return []

        with self.conn() as c:
            rows = c.execute("""
                SELECT collection, COUNT(DISTINCT system) AS systems,
                       COUNT(*) AS files
                FROM files
                GROUP BY collection
                ORDER BY collection
            """).fetchall()

            results: list[CollectionSummary] = []
            for r in rows:
                coll = r["collection"]
                trow = c.execute(
                    "SELECT COUNT(*) AS cnt FROM torrents WHERE collection = ?",
                    (coll,),
                ).fetchone()
                has_torrents = bool(trow and trow["cnt"] > 0)
                status = CollectionStatus.INDEXED if has_torrents else CollectionStatus.MISSING

                results.append(CollectionSummary(
                    name=coll,
                    systems=r["systems"],
                    files=r["files"],
                    status=status,
                ))
            return results

    def get_system_summaries(self, collection: str) -> list["SystemSummary"]:
        """Return per-system summary for a collection."""
        if not _HAS_DOMAIN:
            raise RuntimeError("Domain types not available")
        if not self._ready: return []

        with self.conn() as c:
            rows = c.execute("""
                SELECT system, COUNT(*) AS files
                FROM files
                WHERE collection = ?
                GROUP BY system
                ORDER BY system
            """, (collection,)).fetchall()

            results: list[SystemSummary] = []
            for r in rows:
                sys_name = r["system"]
                trow = c.execute(
                    "SELECT COUNT(*) AS cnt FROM torrents "
                    "WHERE collection = ? AND system = ?",
                    (collection, sys_name),
                ).fetchone()
                source_present = bool(trow and trow["cnt"] > 0)

                results.append(SystemSummary(
                    collection=collection,
                    system=sys_name,
                    files=r["files"],
                    last_update=None,
                    source_present=source_present,
                    expected_files=r["files"] if source_present else None,
                ))
            return results

    def get_index_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent index build records, newest first."""
        if not self._ready: return []
        with self.conn() as c:
            rows = c.execute(
                "SELECT id, started_at, completed_at, status, torrent_count, "
                "file_count, error_count, elapsed_ms "
                "FROM index_runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def remove_collection(self, collection: str) -> int:
        """Remove all indexed rows and torrent metadata for a collection."""
        with self.conn() as c:
            count = c.execute(
                "SELECT COUNT(*) FROM files WHERE collection = ?",
                (collection,),
            ).fetchone()[0]
            c.execute("DELETE FROM files WHERE collection = ?", (collection,))
            c.execute("DELETE FROM torrents WHERE collection = ?", (collection,))
        self.clear_cache()
        return count

    def run_integrity_check(self) -> dict:
        """Run PRAGMA quick_check and return results."""
        with self.conn() as c:
            row = c.execute("PRAGMA quick_check").fetchone()
            result = row[0] if row else "unknown"

            table_counts: dict[str, int] = {}
            for table in ("files", "torrents", "file_tags", "file_regions", "index_runs"):
                try:
                    cnt = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    table_counts[table] = cnt
                except sqlite3.OperationalError:
                    table_counts[table] = -1

            return {
                "quick_check": result,
                "table_counts": table_counts,
                "ok": result == "ok",
            }

    def find_missing_torrent_sources(
        self, torrent_dir: Path | str = DEFAULT_TORRENT_DIR,
    ) -> list[dict]:
        """Find indexed torrent sources that are missing from disk.

        ``torrent_dir`` defaults to the project source directory but callers
        can supply the configured location used by the desktop application.
        """
        torrent_dir = Path(torrent_dir)
        with self.conn() as c:
            rows = c.execute(
                "SELECT DISTINCT torrent FROM files ORDER BY torrent"
            ).fetchall()

            missing: list[dict] = []
            for r in rows:
                torrent_name = r["torrent"]
                torrent_path = torrent_dir / torrent_name
                if not torrent_path.exists():
                    missing.append({
                        "torrent": torrent_name,
                        "path": str(torrent_path),
                    })
            return missing

    # ── Detailed DAT matching ─────────────────────────────────────────────

    def match_dat_detailed(
        self,
        entries: Sequence[DatEntry],
        collection: str = "",
        system: str = "",
        candidate_limit: int = 5,
    ) -> dict:
        """Match DAT entries returning multiple candidates with confidence scores.

        Returns a dict with:

        ``results``: list of per-entry results, each containing:
            - entry: DatEntry — the original entry
            - candidates: list of candidate dicts
            - automatic_file_id: int | None — best candidate's file_id
            - automatic_method: str | None — match method
            - automatic_confidence: float | None — confidence [0,1]

        Each candidate dict has:
            file_id, title, collection, system, size, method,
            confidence (float), reasons (list[str])

        ``summary``: dict with total, exact, fuzzy, unmatched counts.

        Scoring formula (deterministic, clamped to [0, 1]):
            - Exact stem: 1.00
            - Exact normalized core title: 0.96
            - Strong keyword overlap (>=80%): 0.95
            - Moderate keyword overlap (>=50%): 0.85
            - Weak keyword overlap: 0.70
            - No keywords possible: 0.50
            - Matching non-zero size: +0.03
            - Collection and system both match: +0.02
            - Conflicting non-zero size (>10% diff): -0.08
            - Cross-system/cross-collection fallback: -0.15
        """
        if not getattr(self, '_ready', False):
            return {"results": [], "summary": {"total": 0, "exact": 0, "fuzzy": 0, "unmatched": 0}}
        def _score(
            entry_stem: str, entry_size: int,
            candidate: sqlite3.Row,
        ) -> tuple[float, list[str]]:
            """Score a single candidate and return (confidence, reasons)."""
            reasons: list[str] = []
            cand_stem = candidate["stem"]
            cand_size = candidate["size"]

            # ── Title similarity ──────────────────────────────────────────
            if entry_stem == cand_stem:
                reasons.append("Exact stem match")
                confidence = 1.0
            else:
                entry_core = core_title(entry_stem)
                cand_core = core_title(cand_stem)
                if entry_core == cand_core:
                    reasons.append(f"Core title match: '{entry_core}'")
                    confidence = 0.96
                else:
                    entry_kw = title_keywords(entry_stem)
                    cand_kw = title_keywords(cand_stem)
                    if entry_kw and cand_kw:
                        overlap = entry_kw & cand_kw
                        overlap_ratio = len(overlap) / max(len(entry_kw), len(cand_kw))
                        if overlap_ratio >= 0.8:
                            reasons.append(f"Strong keyword overlap ({overlap_ratio:.0%})")
                            confidence = 0.95
                        elif overlap_ratio >= 0.5:
                            reasons.append(f"Moderate keyword overlap ({overlap_ratio:.0%})")
                            confidence = 0.85
                        else:
                            reasons.append(f"Weak keyword overlap ({overlap_ratio:.0%})")
                            confidence = 0.70
                    else:
                        reasons.append("No keyword overlap possible")
                        confidence = 0.50

            # ── Size adjustments ──────────────────────────────────────────
            if entry_size > 0 and cand_size > 0:
                if entry_size == cand_size:
                    reasons.append("Exact size match")
                    confidence += 0.03
                else:
                    ratio = abs(entry_size - cand_size) / max(entry_size, cand_size)
                    if ratio > 0.10:
                        reasons.append(
                            f"Size mismatch ({entry_size} vs {cand_size})"
                        )
                        confidence -= 0.08

            # ── Collection / system consistency ───────────────────────────
            coll_match = (not collection or candidate["collection"] == collection)
            sys_match = (not system or candidate["system"] == system)
            if coll_match and sys_match:
                reasons.append("Collection & system match")
                confidence += 0.02
            elif not sys_match and not coll_match:
                reasons.append("Cross-system/cross-collection fallback")
                confidence -= 0.15

            return max(0.0, min(1.0, confidence)), reasons

        t0 = time.time()
        results_list: list[dict] = []
        summary_exact = 0
        summary_fuzzy = 0
        summary_unmatched = 0

        with self.conn() as conn:
            for entry in entries:
                entry_stem = stem_from_romname(entry.filename)
                entry_size = entry.size

                # Collect candidates from all tiers (deduplicated by id)
                seen_ids: set[int] = set()
                tier_sources: dict[int, str] = {}

                # Tier 1: exact stem
                tier1 = self._find_by_stem(
                    entry_stem, collection, system, conn, size=entry_size
                )
                for r in tier1:
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        tier_sources[r["id"]] = "exact"

                # Tier 2: FTS5
                if len(seen_ids) < candidate_limit:
                    tier2 = self._find_by_fts(
                        entry_stem, collection, system, conn, size=entry_size
                    )
                    for r in tier2:
                        if r["id"] not in seen_ids and stems_match(entry_stem, r["stem"]):
                            seen_ids.add(r["id"])
                            tier_sources[r["id"]] = "fuzzy"

                # Tier 3: trigram
                if len(seen_ids) < candidate_limit:
                    tier3 = self._find_by_trigram(
                        entry_stem, collection, system, conn, size=entry_size
                    )
                    for r in tier3:
                        if r["id"] not in seen_ids and stems_match(entry_stem, r["stem"]):
                            seen_ids.add(r["id"])
                            tier_sources[r["id"]] = "fuzzy"

                # Tier 4: keywords
                if len(seen_ids) < candidate_limit:
                    tier4 = self._find_by_keywords(
                        entry_stem, collection, system, conn, size=entry_size
                    )
                    for r in tier4:
                        if r["id"] not in seen_ids and stems_match(entry_stem, r["stem"]):
                            seen_ids.add(r["id"])
                            tier_sources[r["id"]] = "fuzzy"

                # Score and build candidate list
                scored: list[dict] = []
                for cand_id in list(seen_ids)[:candidate_limit]:
                    # Fetch the full row to score it
                    cand_row = conn.execute(
                        "SELECT * FROM files WHERE id = ?", (cand_id,)
                    ).fetchone()
                    if cand_row is None:
                        continue
                    method = tier_sources.get(cand_id, "fuzzy")
                    confidence, reasons = _score(entry_stem, entry_size, cand_row)
                    scored.append({
                        "file_id": cand_row["id"],
                        "title": cand_row["stem"],
                        "collection": cand_row["collection"],
                        "system": cand_row["system"],
                        "size": cand_row["size"],
                        "method": method,
                        "confidence": round(confidence, 4),
                        "reasons": reasons,
                    })

                # Sort by confidence descending
                scored.sort(key=lambda x: -x["confidence"])

                # Best candidate for automatic suggestion
                if scored:
                    auto = scored[0]
                    automatic_file_id: int | None = auto["file_id"]
                    automatic_method: str | None = auto["method"]
                    automatic_confidence: float | None = auto["confidence"]
                    if auto["method"] == "exact":
                        summary_exact += 1
                    else:
                        summary_fuzzy += 1
                else:
                    automatic_file_id = None
                    automatic_method = None
                    automatic_confidence = None
                    summary_unmatched += 1

                results_list.append({
                    "entry": entry,
                    "candidates": scored,
                    "automatic_file_id": automatic_file_id,
                    "automatic_method": automatic_method,
                    "automatic_confidence": automatic_confidence,
                })

        elapsed = (time.time() - t0) * 1000
        log.debug(
            "match_dat_detailed: %d entries → %d exact, %d fuzzy, %d unmatched in %.0fms",
            len(entries), summary_exact, summary_fuzzy, summary_unmatched, elapsed,
        )

        return {
            "results": results_list,
            "summary": {
                "total": len(entries),
                "exact": summary_exact,
                "fuzzy": summary_fuzzy,
                "unmatched": summary_unmatched,
            },
        }

        # ── Two-best-candidates helper (for margin-based classification) ─────

    def get_two_best_candidates(
        self,
        entry: DatEntry,
        collection: str = "",
        system: str = "",
    ) -> tuple[dict | None, dict | None]:
        """Return the top two scored candidates for a single entry.

        Returns (best, second_best) where each is a dict with keys:
            file_id, title, collection, system, size, method, confidence, reasons

        Either or both may be ``None`` (no candidate at all, or only one
        candidate found).  Candidates are never de-duplicated by the
        caller — the margin computation needs both even if they are equal.
        """
        if not self._ready: return None, None
        entry_stem = stem_from_romname(entry.filename)
        entry_size = entry.size

        with self.conn() as conn:
            seen_ids: set[int] = set()
            tier_sources: dict[int, str] = {}

            # Tier 1: exact stem — no candidate_limit here, we want T1 completely
            tier1 = self._find_by_stem(entry_stem, collection, system, conn, size=entry_size)
            for r in tier1:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    tier_sources[r["id"]] = "exact"

            # Tier 2: FTS5
            tier2 = self._find_by_fts(entry_stem, collection, system, conn, size=entry_size)
            for r in tier2:
                if r["id"] not in seen_ids and stems_match(entry_stem, r["stem"]):
                    seen_ids.add(r["id"])
                    if r["id"] not in tier_sources:
                        tier_sources[r["id"]] = "fuzzy"

            # Tier 3: trigram
            tier3 = self._find_by_trigram(entry_stem, collection, system, conn, size=entry_size)
            for r in tier3:
                if r["id"] not in seen_ids and stems_match(entry_stem, r["stem"]):
                    seen_ids.add(r["id"])
                    if r["id"] not in tier_sources:
                        tier_sources[r["id"]] = "fuzzy"

            # Tier 4: keywords — but only if we have fewer than 2 candidates
            if len(seen_ids) < 2:
                tier4 = self._find_by_keywords(entry_stem, collection, system, conn, size=entry_size)
                for r in tier4:
                    if r["id"] not in seen_ids and stems_match(entry_stem, r["stem"]):
                        seen_ids.add(r["id"])
                        if r["id"] not in tier_sources:
                            tier_sources[r["id"]] = "fuzzy"

            # Score all candidates
            scored: list[dict] = []
            for cand_id in seen_ids:
                cand_row = conn.execute(
                    "SELECT * FROM files WHERE id = ?", (cand_id,)
                ).fetchone()
                if cand_row is None:
                    continue
                method = tier_sources.get(cand_id, "fuzzy")
                confidence, reasons = self._score_candidate(
                    entry_stem, entry_size, cand_row, collection, system,
                )
                scored.append({
                    "file_id": cand_row["id"],
                    "title": cand_row["stem"],
                    "collection": cand_row["collection"],
                    "system": cand_row["system"],
                    "size": cand_row["size"],
                    "method": "exact" if method == "exact" else "fuzzy",
                    "confidence": round(confidence, 4),
                    "reasons": reasons,
                })

            scored.sort(key=lambda x: -x["confidence"])
            if not scored:
                return None, None
            best = scored[0]
            second = scored[1] if len(scored) > 1 else None
            return best, second

    @staticmethod
    def _score_candidate(
        entry_stem: str, entry_size: int,
        candidate: sqlite3.Row,
        collection: str = "",
        system: str = "",
    ) -> tuple[float, list[str]]:
        """Score a single candidate and return (confidence, reasons).

        Scoring formula (deterministic, clamped to [0, 1]):
            - Exact stem: 1.00
            - Exact normalized core title: 0.96
            - Strong keyword overlap (>=80%): 0.95
            - Moderate keyword overlap (>=50%): 0.85
            - Weak keyword overlap: 0.70
            - No keywords possible: 0.50
            - Matching non-zero size: +0.03
            - Collection and system both match: +0.02
            - Conflicting non-zero size (>10% diff): -0.08
            - Cross-system/cross-collection fallback: -0.15
        """
        reasons: list[str] = []
        cand_stem = candidate["stem"]
        cand_size = candidate["size"]

        # ── Title similarity ──
        if entry_stem == cand_stem:
            reasons.append("Exact stem match")
            confidence = 1.0
        else:
            entry_core = core_title(entry_stem)
            cand_core = core_title(cand_stem)
            if entry_core == cand_core:
                reasons.append(f"Core title match: '{entry_core}'")
                confidence = 0.96
            else:
                entry_kw = title_keywords(entry_stem)
                cand_kw = title_keywords(cand_stem)
                if entry_kw and cand_kw:
                    overlap = entry_kw & cand_kw
                    overlap_ratio = len(overlap) / max(len(entry_kw), len(cand_kw))
                    if overlap_ratio >= 0.8:
                        reasons.append(f"Strong keyword overlap ({overlap_ratio:.0%})")
                        confidence = 0.95
                    elif overlap_ratio >= 0.5:
                        reasons.append(f"Moderate keyword overlap ({overlap_ratio:.0%})")
                        confidence = 0.85
                    else:
                        reasons.append(f"Weak keyword overlap ({overlap_ratio:.0%})")
                        confidence = 0.70
                else:
                    reasons.append("No keyword overlap possible")
                    confidence = 0.50

        # ── Size adjustments ──
        if entry_size > 0 and cand_size > 0:
            if entry_size == cand_size:
                reasons.append("Exact size match")
                confidence += 0.03
            else:
                ratio = abs(entry_size - cand_size) / max(entry_size, cand_size)
                if ratio > 0.10:
                    reasons.append(f"Size mismatch ({entry_size} vs {cand_size})")
                    confidence -= 0.08

        # ── Collection / system consistency ──
        coll_match = (not collection or candidate["collection"] == collection)
        sys_match = (not system or candidate["system"] == system)
        if coll_match and sys_match:
            reasons.append("Collection & system match")
            confidence += 0.02
        elif not sys_match and not coll_match:
            reasons.append("Cross-system/cross-collection fallback")
            confidence -= 0.15

        return max(0.0, min(1.0, confidence)), reasons

    def find_file_id_by_stem_and_size(
        self,
        stem: str,
        size: int = 0,
        collection: str = "",
        system: str = "",
    ) -> StemSizeMatch | list[StemSizeMatch] | None:
        where_parts = ["stem = ?"]
        params: list = [stem]
        if size:
            where_parts.append("size = ?")
            params.append(size)
        if collection:
            where_parts.append("collection = ?")
            params.append(collection)
        if system:
            where_parts.append("system = ?")
            params.append(system)
        where = " AND ".join(where_parts)

        with self.conn() as c:
            rows = c.execute(
                f"SELECT id, collection, system, basename, size FROM files WHERE {where}",
                params,
            ).fetchall()

        if not rows:
            return None
        matches = [
            StemSizeMatch(
                file_id=r["id"], collection=r["collection"], system=r["system"],
                basename=r["basename"], size=r["size"],
            ) for r in rows
        ]
        return matches[0] if len(matches) == 1 else matches

    def get_file_regions(self, file_ids: list[int]) -> dict[int, list[str]]:
        with self.conn() as c:
            raw = self._load_regions_for_files(c, file_ids)
        return {fid: list(regions) for fid, regions in raw.items()}

    def get_file_tags(self, file_ids: list[int]) -> dict[int, list[str]]:
        with self.conn() as c:
            raw = self._load_tags_for_files(c, file_ids)
        return {fid: list(tags) for fid, tags in raw.items()}

    # ── Private matching methods ──────────────────────────────────────────
    def _find_by_stem(
        self, stem: str, collection: str, system: str,
        conn: sqlite3.Connection | None = None,
        size: int = 0,
    ) -> list[sqlite3.Row]:
        """Tier 1: Exact stem match using the unique index."""
        cache_key = ("stem", stem, collection, system, size)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        def _build_where(include_size: bool) -> tuple[str, list]:
            where = ["stem = ?"]
            params: list = [stem]
            if include_size and size > 0:
                where.append("size = ?")
                params.append(size)
            if collection:
                where.append("collection = ?")
                params.append(collection)
            if system:
                where.append("system = ?")
                params.append(system)
            return " AND ".join(where), params

        def _do(c: sqlite3.Connection) -> list[sqlite3.Row]:
            w, params = _build_where(include_size=True)
            rows = c.execute(
                f"SELECT * FROM files WHERE {w} ORDER BY size DESC", params
            ).fetchall()
            if not rows and size > 0:
                # Soft-filter fallback: maybe the size differs across regions
                # / repacks. Try without the size constraint.
                w, params = _build_where(include_size=False)
                rows = c.execute(
                    f"SELECT * FROM files WHERE {w} ORDER BY size DESC", params
                ).fetchall()
            return rows

        if conn is not None:
            rows = _do(conn)
        else:
            with self.conn() as c:
                rows = _do(c)
        self._cache.put(cache_key, rows)
        return rows

    def _find_by_fts(
        self, stem: str, collection: str, system: str,
        conn: sqlite3.Connection | None = None,
        size: int = 0,
    ) -> list[sqlite3.Row]:
        """Tier 2: FTS5 MATCH query on stem words.

        Uses porter + unicode61 tokenizer for natural language matching.
        """
        keywords = title_keywords(stem)
        if not keywords:
            return []
        fts_terms = " OR ".join(fts_escape(k) for k in keywords)
        return self._fts_query(fts_terms, "files_fts", collection, system, conn, size=size)

    def _find_by_trigram(
        self, stem: str, collection: str, system: str,
        conn: sqlite3.Connection | None = None,
        size: int = 0,
    ) -> list[sqlite3.Row]:
        """Tier 3: FTS5 trigram matching for partial substring matching."""
        keywords = title_keywords(stem)
        if not keywords:
            return []
        longest = max(keywords, key=len)
        fts_terms = fts_escape(longest)
        return self._fts_query(fts_terms, "files_trigram", collection, system, conn, size=size)

    def _find_by_keywords(
        self, stem: str, collection: str, system: str,
        conn: sqlite3.Connection | None = None,
        size: int = 0,
    ) -> list[sqlite3.Row]:
        """Tier 4: LIKE-based keyword fallback (worst case)."""
        keywords = title_keywords(stem)
        if len(keywords) < 2:
            return []
        top_kw = sorted(keywords, key=lambda w: -len(w))[:2]
        where = ["stem LIKE ?" for _ in top_kw]
        params: list = [f"%{kw}%" for kw in top_kw]
        if size > 0:
            where.append("size = ?")
            params.append(size)
        if collection:
            where.append("collection = ?")
            params.append(collection)
        if system:
            where.append("system = ?")
            params.append(system)

        def _do(c: sqlite3.Connection) -> list[sqlite3.Row]:
            return c.execute(
                f"SELECT * FROM files WHERE {' AND '.join(where)} "
                f"LIMIT {MAX_FUZZY_CANDIDATES}", params
            ).fetchall()

        if conn is not None:
            return _do(conn)
        with self.conn() as c:
            return _do(c)

    def _fts_query(
        self,
        fts_terms: str,
        fts_table: str,
        collection: str,
        system: str,
        conn: sqlite3.Connection | None = None,
        size: int = 0,
    ) -> list[sqlite3.Row]:
        """Execute a FTS5 MATCH query with optional collection/system scope.

        Uses a two-step approach: FTS5 first to get rowids, then a single
        batch query to fetch all rows by id. This avoids expensive JOINs.

        ``size`` is a soft pre-filter: when > 0 we restrict the candidate
        set to rows with that exact size (DAT sizes are usually accurate
        and unique enough to drop most cross-system noise). If no rows
        match, we retry without the size constraint.
        """
        if fts_table not in ("files_fts", "files_trigram"):
            raise ValueError(f"Invalid FTS table: {fts_table}")

        def _do(c: sqlite3.Connection) -> list[sqlite3.Row]:
            # Step 1: FTS5 returns rowids fast
            rowids = c.execute(
                f"SELECT rowid FROM {fts_table} "
                f"WHERE {fts_table} MATCH ? "
                f"ORDER BY rank LIMIT ?",
                (fts_terms, MAX_FUZZY_CANDIDATES)).fetchall()
            if not rowids:
                return []
            ids = [r[0] for r in rowids]

            # Step 2: batch query for all matching rows
            placeholders = ",".join("?" * len(ids))
            where = [f"id IN ({placeholders})"]
            params: list = list(ids)
            if size > 0:
                where.append("size = ?")
                params.append(size)
            if collection:
                where.append("collection = ?")
                params.append(collection)
            if system:
                where.append("system = ?")
                params.append(system)
            rows = c.execute(
                f"SELECT * FROM files WHERE {' AND '.join(where)} "
                f"ORDER BY size DESC",
                params).fetchall()
            if not rows and size > 0:
                # Soft-filter fallback: drop the size constraint.
                where = [f"id IN ({placeholders})"]
                params = list(ids)
                if collection:
                    where.append("collection = ?")
                    params.append(collection)
                if system:
                    where.append("system = ?")
                    params.append(system)
                rows = c.execute(
                    f"SELECT * FROM files WHERE {' AND '.join(where)} "
                    f"ORDER BY size DESC",
                    params).fetchall()
            return rows

        if conn is not None:
            return _do(conn)
        with self.conn() as c:
            return _do(c)
