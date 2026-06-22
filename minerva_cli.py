"""Thin CLI for the Minerva Myrient-Can-FixDAT index.

Usage:
    python minerva_cli.py index [--rebuild]
    python minerva_cli.py find <query> [--collection <col>] [--system <sys>] [--limit <n>]
    python minerva_cli.py download <file_id> [--dest <path>]
    python minerva_cli.py stats
    python minerva_cli.py check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Import only from the production modules
from minerva_db import DEFAULT_INDEX_PATH, DEFAULT_TORRENT_DIR, MinervaDB, build_index
from minerva_qbit import QBittorrentClient


# ── Formatting helpers ────────────────────────────────────────────────────────

def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ── Commands ──────────────────────────────────────────────────────────────────

def command_index(args: argparse.Namespace) -> None:
    """Build or rebuild the torrent index."""
    import time
    t0 = time.time()
    build_index(DEFAULT_TORRENT_DIR, DEFAULT_INDEX_PATH)
    print(f"Done in {time.time() - t0:.1f}s")


def command_find(args: argparse.Namespace) -> None:
    """Search the library."""
    db = MinervaDB()
    rows, total = db.search(
        query=args.query,
        collection=args.collection or "",
        system=args.system or "",
        limit=args.limit or 20,
    )
    print(f"Found {total} results:")
    for row in rows:
        print(f"  {row['stem']:50s} {_format_bytes(row['size']):>10s}  "
              f"{row['collection']:20s} {row['system']}")


def command_download(args: argparse.Namespace) -> None:
    """Submit one selectively-enabled file to qBittorrent."""
    import os

    db = MinervaDB()
    spec = db.get_download_spec(args.file_id, DEFAULT_TORRENT_DIR)
    if spec is None:
        raise SystemExit(f"Unknown file_id: {args.file_id}")
    client = QBittorrentClient(
        os.environ.get("MINERVA_QBIT_URL", "http://localhost:8080"),
        os.environ.get("MINERVA_QBIT_USER", "admin"),
        os.environ.get("MINERVA_QBIT_PASS", ""),
    )
    client.login()
    torrent_hash = client.add_torrent_paused(str(spec.torrent_path), str(Path(args.dest).resolve()))
    files = client.get_files(torrent_hash)
    all_indices = [int(item["index"]) for item in files]
    client.set_file_priority(torrent_hash, all_indices, 0)
    client.set_file_priority(torrent_hash, [spec.select_index - 1], 1)
    client.resume(torrent_hash)
    print(f"Queued {spec.basename} ({torrent_hash}) → {Path(args.dest).resolve()}")


def command_stats(args: argparse.Namespace) -> None:
    """Show index statistics."""
    db = MinervaDB()
    overview = db.get_index_overview()
    print(f"Collections: {overview.collections}")
    print(f"Systems:     {overview.systems}")
    print(f"Files:       {overview.files}")
    print(f"DB size:     {_format_bytes(overview.database_size)}")
    print(f"Last build:  {overview.last_build or 'never'}")


def command_check(args: argparse.Namespace) -> None:
    """Run integrity check."""
    db = MinervaDB()
    result = db.run_integrity_check()
    print(f"Integrity: {result.get('quick_check', 'unknown')}")


# ── CLI entrypoint ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Minerva CLI")
    sub = parser.add_subparsers(dest="command")

    p_index = sub.add_parser("index", help="Build/rebuild index")
    p_index.add_argument("--rebuild", action="store_true")

    p_find = sub.add_parser("find", help="Search library")
    p_find.add_argument("query")
    p_find.add_argument("--collection")
    p_find.add_argument("--system")
    p_find.add_argument("--limit", type=int, default=20)

    p_dl = sub.add_parser("download", help="Download file")
    p_dl.add_argument("file_id", type=int)
    p_dl.add_argument("--dest", default="downloads")

    sub.add_parser("stats", help="Index statistics")
    sub.add_parser("check", help="Integrity check")

    args = parser.parse_args()

    commands = {
        "index": command_index,
        "find": command_find,
        "download": command_download,
        "stats": command_stats,
        "check": command_check,
    }

    cmd = commands.get(args.command)
    if cmd is None:
        parser.print_help()
        sys.exit(1)
    cmd(args)


if __name__ == "__main__":
    main()
