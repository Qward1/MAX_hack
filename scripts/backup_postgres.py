"""One pg_dump from a named Docker DB container, verified, keeping the last N copies.

Before the dump the directory must have `--min-free-mb` free; after it,
`pg_restore --list` must read the new file, or the unverified file is removed
and the run fails. Only then are copies beyond `--keep` (14 by default) rotated —
and only this script's `domsignal-*.dump` files in the selected directory.
Scheduling is a systemd timer (`deploy/systemd`, D4). Run with an account
authorized to read this database and protect the output directory as private data.
"""

import argparse
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

KEEP = 14
MIN_FREE_MB = 1024


class BackupError(RuntimeError):
    """Not enough space, or the new dump does not read back."""


def free_mb(directory: Path) -> int:
    return shutil.disk_usage(directory).free // (1024 * 1024)


def verify(container: str, target: Path) -> int:
    """Entries in the dump's table of contents; unreadable dump — `BackupError`."""
    with target.open("rb") as stream:
        listed = subprocess.run(
            ["docker", "exec", "-i", container, "pg_restore", "--list"],
            stdin=stream,
            capture_output=True,
            check=False,
        )
    entries = [
        line
        for line in listed.stdout.decode("utf-8", "replace").splitlines()
        if line.strip() and not line.startswith(";")
    ]
    if listed.returncode != 0 or not entries:
        raise BackupError(f"pg_restore --list failed for {target.name}")
    return len(entries)


def backup(
    *,
    container: str,
    user: str,
    database: str,
    directory: Path,
    keep: int = KEEP,
    min_free_mb: int = MIN_FREE_MB,
) -> tuple[Path, int]:
    """Dump, verify, rotate. Returns the new dump and its TOC entry count."""
    if keep < 1:
        raise ValueError("keep must be at least 1")
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if free_mb(directory) < min_free_mb:
        raise BackupError(f"less than {min_free_mb} MB free in {directory}")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"domsignal-{stamp}.dump"
    partial = target.with_suffix(".partial")
    try:
        with partial.open("xb") as stream:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "pg_dump",
                    "--username",
                    user,
                    "--dbname",
                    database,
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                ],
                stdout=stream,
                check=True,
            )
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    try:
        entries = verify(container, target)
    except BaseException:
        target.unlink(missing_ok=True)  # The unverified copy never rotates good ones.
        raise
    # Only this script's dump files in the explicitly selected directory.
    for old in sorted(directory.glob("domsignal-*.dump"), reverse=True)[keep:]:
        if old.is_file() and not old.is_symlink():
            old.unlink()
    return target, entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--user", default="domsignal")
    parser.add_argument("--database", default="domsignal")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--keep", type=int, default=KEEP, help="copies to keep (default 14)")
    parser.add_argument(
        "--min-free-mb", type=int, default=MIN_FREE_MB, help="refuse below this free space"
    )
    args = parser.parse_args()
    target, entries = backup(
        container=args.container,
        user=args.user,
        database=args.database,
        directory=args.directory,
        keep=args.keep,
        min_free_mb=args.min_free_mb,
    )
    print(
        f"{target} size={target.stat().st_size} toc_entries={entries} "
        f"free_mb={free_mb(target.parent)}"
    )


if __name__ == "__main__":
    main()
