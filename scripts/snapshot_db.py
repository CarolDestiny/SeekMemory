"""Create a consistent SQLite snapshot, including WAL contents."""
from __future__ import annotations
import argparse
import sqlite3
from pathlib import Path


def snapshot(source: str, destination: str) -> None:
    src_path = Path(source).expanduser()
    dst_path = Path(destination).expanduser()
    if not src_path.exists():
        raise FileNotFoundError(str(src_path))
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    if dst_path.exists():
        dst_path.unlink()
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    snapshot(args.source, args.destination)
    print(f"snapshot: {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
