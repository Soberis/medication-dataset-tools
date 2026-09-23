"""Read and update the human-reviewed candidate CSV."""

import csv
import os
import tempfile
from pathlib import Path


FIELDS = ("selected", "bvid", "title", "url", "keyword", "uploader", "duration")


def read_candidates(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not set(FIELDS).issubset(reader.fieldnames or []):
            raise ValueError(f"{path} 缺少必要列：{', '.join(FIELDS)}")
        rows = list(reader)
    seen = set()
    for number, row in enumerate(rows, 2):
        bvid = row["bvid"].strip()
        if not bvid or bvid in seen:
            raise ValueError(f"{path}:{number} BV 号为空或重复")
        seen.add(bvid)
    return rows


def append_candidates(path: Path, new_rows: list[dict[str, str]]) -> int:
    rows = read_candidates(path)
    known = {row["bvid"].strip() for row in rows}
    added = 0
    for row in new_rows:
        if row["bvid"] not in known:
            rows.append(row)
            known.add(row["bvid"])
            added += 1
    if not added and path.exists():
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=".candidates-", suffix=".csv", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return added
