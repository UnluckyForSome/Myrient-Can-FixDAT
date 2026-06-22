#!/usr/bin/env python3
"""Import a romresolve library report JSON into Minerva."""

from __future__ import annotations

import argparse
from pathlib import Path

from minerva.services.report_acquisition import ReportAcquisitionService


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a romresolve library report")
    parser.add_argument("json_path", type=Path, help="Path to library-report.json")
    parser.add_argument("--collection", default="", help="Default collection scope")
    parser.add_argument("--system", default="", help="Default system scope")
    args = parser.parse_args()

    svc = ReportAcquisitionService()
    reports = svc.import_library_report(
        args.json_path,
        collection=args.collection,
        system=args.system,
    )
    for r in reports:
        print(f"Imported report {r.id}: {r.name} (system={r.system})")
    print(f"\nTotal: {len(reports)} reports created")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
