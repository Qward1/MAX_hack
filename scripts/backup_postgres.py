"""One pg_dump from a named Docker DB container; retain the last seven successes.

No scheduler, credentials, deployment or automatic restore. Run with an account
authorized to read this database and protect the output directory as private data.
"""

import argparse
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def backup(*, container: str, user: str, database: str, directory: Path) -> Path:
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
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
    # Only this script's dump files in the explicitly selected directory.
    for old in sorted(directory.glob("domsignal-*.dump"), reverse=True)[7:]:
        if old.is_file() and not old.is_symlink():
            old.unlink()
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--user", default="domsignal")
    parser.add_argument("--database", default="domsignal")
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    print(
        backup(
            container=args.container,
            user=args.user,
            database=args.database,
            directory=args.directory,
        )
    )


if __name__ == "__main__":
    main()
