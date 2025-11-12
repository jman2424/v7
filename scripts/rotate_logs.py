#!/usr/bin/env python3
"""
Rotate logs/* → logs/archive/YYYY-MM-DD/*.log.gz and truncate originals.

Usage:
  python scripts/rotate_logs.py [--logs-dir logs] [--retention 14]

Notes:
- Compresses *.log files into date-stamped archive dir.
- Keeps last N days of archives, removes older ones.
"""

from __future__ import annotations
import argparse
import datetime as dt
import gzip
import os
import shutil
from pathlib import Path

def rotate(logs_dir: Path, retention_days: int) -> None:
    today = dt.date.today().isoformat()
    src = logs_dir
    archive_root = logs_dir / "archive" / today
    archive_root.mkdir(parents=True, exist_ok=True)

    count = 0
    for p in src.glob("*.log"):
        if p.is_dir():
            continue
        gz_path = archive_root / f"{p.name}.gz"
        with p.open("rb") as f_in, gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        p.write_text("", encoding="utf-8")  # truncate
        count += 1

    # retention: delete old archive dirs
    keep_after = dt.date.today() - dt.timedelta(days=retention_days)
    archive_parent = logs_dir / "archive"
    for d in archive_parent.glob("*"):
        try:
            if d.is_dir() and dt.date.fromisoformat(d.name) < keep_after:
                shutil.rmtree(d, ignore_errors=True)
        except Exception:
            continue

    print(f"[OK] Rotated {count} log(s) into {archive_root}. Retention={retention_days}d.")

def main():
    ap = argparse.ArgumentParser(description="Rotate/Archive logs")
    ap.add_argument("--logs-dir", default="logs")
    ap.add_argument("--retention", type=int, default=14)
    args = ap.parse_args()
    rotate(Path(args.logs_dir), args.retention)

if __name__ == "__main__":
    main()
