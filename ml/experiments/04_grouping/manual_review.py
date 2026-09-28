"""Display privacy-normalized chat slices for manual incident annotation.

No source text is written to disk or included in annotation files.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

from replay_real import load_day


def message_key(source: str, message_id: str) -> str:
    return hashlib.sha256(f"{source}:{message_id}".encode()).hexdigest()[:16]


def normalized_for_review(value: str) -> str:
    value = re.sub(r"<[^>]+>", "[скрыто]", value)
    value = re.sub(r"https?://\S+|\S+@\S+", "[скрыто]", value, flags=re.I)
    value = re.sub(r"\b\d{5,}\b", "[число]", value)
    value = value.lower().replace("ё", "е")
    value = re.sub(r"[^а-яa-z0-9\s?!.,:;—()\[\]-]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--day", required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    rows = load_day(args.data_root, args.day)
    index_by_id = {row["id"]: i for i, (_, row) in enumerate(rows)}
    fingerprint = hashlib.sha256("|".join(
        source + ":" + row["id"] for source, row in rows).encode()).hexdigest()
    print(f"day={args.day} total={len(rows)} fingerprint={fingerprint} "
          f"slice={args.start}:{args.start+args.limit}")
    for i in range(args.start, min(len(rows), args.start + args.limit)):
        source, row = rows[i]
        reply = index_by_id.get(row.get("reply_to"), "-")
        key = message_key(source, row["id"])
        print(f"{i:03d} {key} {row['ts'][11:16]} {source[5:7]} reply={reply} "
              f"{normalized_for_review(row['text'])[:320]}")


if __name__ == "__main__":
    main()
