# Minerva Can FixDAT

> **Myrient** shut down on 31 March 2026.
> The **Minerva Archive** (https://minerva-archive.org/browse/) is its successor, run by the same team, but uses **torrents** instead of direct HTTP downloads.

A GUI tool that downloads missing ROMs from the **Minerva Archive** via **qBittorrent**. Point it at your **RomVault fix report** or a **DAT file**, and it will download only what you're missing — using the 1050 `.torrent` files covering No-Intro, Redump, MAME, and more.

## Features

- **Smart Downloads** — Load a RomVault fix report (.csv or fix .dat), auto-match against the Minerva torrent index, preview matches with confidence scoring, and queue missing games
- **No-Intro, Redump, RetroAchievements DAT Support** — Load any standard DAT; fuzzy-matches game names against the torrent index
- **RomVault Fix Reports** — Native support for CSV and Fix DAT formats
- **qBittorrent downloads** — Uses qBittorrent's Web API for selective-file torrent downloads (individual files from multi-file torrents)
- **Match Review** — Interactive review screen to accept/reject fuzzy matches before queuing
- **Download Dashboard** — Live progress, speed, ETA, seeds, ratio per torrent; pause/resume individual files
- **Production-grade** — SQLite + FTS5 full-text search, LRU cache, confidence-scored matching with 7-tier formula
- **Browse & Search** 2.4M files across 1050 torrents with instant search
- **Bilingual** — Full UI in English or Spanish (auto-detects user language)

## Getting Started

### Prerequisites

```bash
pip install PyQt5
```

**qBittorrent** is required for downloads. The tool connects via its Web API:
- Install qBittorrent (https://www.qbittorrent.org/)
- Enable Web UI in qBittorrent: Tools → Preferences → Web UI → enable "Web User Interface"
- Default: `http://localhost:8080` with user `admin` / `adminadmin`

### 1. Clone & Set Up

```bash
git clone https://github.com/yourname/minerva-can-fixdat.git
cd Minerva-Can-FixDAT
```

### 2. Get the Torrent Pack

Place the **1050 Minerva torrent files** in:

```
torrents/Minerva Myrient - 1050 torrents/
```

> The torrent pack is distributed separately by the Minerva community.
> It's ~452 MB compressed, extracted it's ~2 GB.

### 3. Build the Index

```bash
python minerva_gui.py --index
```

This parses all 1050 `.torrent` files and builds a **2.4M-entry search index** with:
- SQLite + FTS5 for full-text search
- 1.3 GB index file at `torrents/minerva_index.db`
- Takes ~3-4 minutes, **one-time operation**

### 4. Launch

```bash
python minerva_gui.py
```

## Usage

### Search

Type in the search bar — searches all 2.4M files in real-time. Filter by Collection/System dropdowns.

### Load a ROMVault Fix Report

1. Run RomVault against your collection to generate a fix report
2. Click **Load Fix Report**
3. Select your `.csv` or `.fixdat` file
4. The tool matches each entry against the Minerva index using confidence-scored title matching
5. Review matches in the Match Review screen — accept/reject ambiguous candidates
6. Confirmed matches move to the download queue

### Load a DAT File

1. Click **Load DAT...**
2. Select a No-Intro, Redump, or RetroAchievements `.dat` file
3. Collection and System are auto-detected from the DAT header
4. Games are matched and reviewed interactively

### Download Dashboard

- View live status of all queued torrents (downloading, seeding, paused, error)
- Per-file progress, download speed, ETA, seeds, peer count, ratio
- Actions column: start, pause, remove individual torrents
- Matches flow through from Match Review → Download Controller → qBittorrent
- Completed files are exposed to your library directory (hardlink or copy)

## Architecture

```
minerva/
├── app/                    # Application layer
│   ├── shell.py            # Main window (QMainWindow) — top-level app shell
│   ├── download_controller.py  # Download orchestration — QbitMonitor,
│   │                         #   queue management, file exposure, signals
│   ├── domain/             # Pure domain types (dataclasses, enums)
│   │   └── downloads.py    #   QueueRecord, DownloadRuntime, DownloadStatus
│   ├── pages/              # Page panels (stacked in shell)
│   │   ├── downloads.py    # Live download dashboard with telemetry
│   │   ├── match_review.py # Interactive match acceptance screen
│   │   ├── collections.py  # Collection browser with rebuild
│   │   └── library.py      # Local library view with context actions
│   └── widgets/            # Reusable widgets
│       ├── background_task.py  # Threaded task runner with signals
│       ├── speed_chart.py  # Live download speed chart
│       └── delegates.py    # Custom item delegates (progress bar, actions)
├── app/worker_manager.py   # Background task queue (delegates to controller)
├── minerva_db.py           # Production database layer
│   ├── v2 schema           # SQLite + FTS5 + trigram indexes
│   ├── build_index()       # Parses .torrent files → SQLite DB
│   ├── MinervaDB           # Main interface
│   │   ├── search()        # Substring search with filters
│   │   ├── match_dat_detailed()  # 7-tier confidence-scored matching
│   │   └── DatEntry        # Domain type for matched entries
│   ├── parse_dat_file()    # No-Intro/Redump/RA DAT XML parser
│   └── parse_rv_fix_csv() # RomVault CSV fix report parser
├── app/minerva_qbit.py     # qBittorrent Web API wrapper
├── app/minerva_state.py    # Global application state
├── minerva_gui.py          # Legacy entry point (delegates to shell)
├── minerva_cli.py          # CLI tool (index, search, find, download)
└── ui/                     # UI module (theme, i18n)

tests/
├── test_minerva_db.py      # 26+ model tests
├── test_match_review.py    # MatchReviewPage construction, states, cards
├── test_match_scoring.py   # Confidence formula branch coverage
├── test_new_implementations.py  # Rebuild, activity, context menu, CLI
└── test_download_model.py  # DownloadRecord, delegates, model
```

### Matching confidence tiers

| Tier | Condition | Confidence |
|------|-----------|------------|
| 1 | Exact stem match | 1.00 |
| 2 | Core title match (normalized) | 0.96 |
| 3 | Strong keyword overlap (>=80%) | 0.95 |
| 4 | Moderate keyword overlap (>=50%) | 0.85 |
| 5 | Weak keyword overlap | 0.70 |
| 6 | No keywords possible | 0.50 |

**Adjustments**: matching size +0.03, collection/system match +0.02, size mismatch >10% -0.08, cross-system/collection -0.15. Clamped to [0, 1].

### Download pipeline

```
DAT/Fix Report → match_dat_detailed() → MatchReviewPage → DownloadController
                                                                    ↓
                                                            QbitMonitor (thread)
                                                                    ↓
                                                            qBittorrent Web API
                                                                    ↓
                                                            File exposure (hardlink/copy)
```

## CLI Usage

```bash
# Build/rebuild index
python minerva_cli.py index

# Search for games
python minerva_cli.py find "Tetris"

# Download a single game (headless qBittorrent)
python minerva_cli.py download "Tetris DX (World) (SGB Enhanced) (GB Compatible)"

# List all torrents by collection
python minerva_cli.py list
```

## Running Tests

```bash
python -m pytest tests/ -v

# Run a specific test file:
python -m pytest tests/test_match_scoring.py -v

# Unit tests only (fast, no DB required):
python -m pytest tests/ -v --ignore=tests/test_minerva_db.py
```

## How the Matching Works

Game names from DAT files often differ from torrent filenames:

| Difference | DAT | Torrent |
|-----------|-----|---------|
| Periods | `Super Mario Bros Deluxe` | `Super Mario Bros. Deluxe` |
| Apostrophes | `Link-s Awakening` | `Link's Awakening` |
| The placement | `The Legend of Zelda` | `Legend of Zelda, The` |
| Extra parens | `R-Type DX` | `R-Type DX (USA) (GB Compatible)` |
| Brothers/Bros | `Super Mario Brothers` | `Super Mario Bros.` |

The matching pipeline normalizes all these differences via:
1. Stripping parentheses and punctuation
2. Normalizing "brothers" → "bros" and "The" placement
3. Comparing core title and keyword overlap with confidence scoring
4. Reviewing low-confidence matches interactively before download

## Credits

- **Minerva Archive Team** — Keeping ROM preservation alive after Myrient
- [Fresh1G1R](https://github.com/UnluckyForSome/Fresh1G1R) — Daily updated 1G1R DAT files
- [RomGoGetter](https://github.com/shokoe/RomGoGetter) — Reference implementation for Minerva torrents
- [No-Intro](https://no-intro.org/) — Cartridge preservation
- [Redump](http://redump.org/) — Disc preservation
- [autobrr/mkbrr](https://github.com/autobrr/mkbrr) — Torrent creation tool used by Minerva
- [qBittorrent](https://www.qbittorrent.org/) — Torrent download engine

## License

MIT
