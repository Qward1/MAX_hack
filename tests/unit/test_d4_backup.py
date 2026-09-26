"""D4, №13: копия БД по расписанию — проверка `pg_restore --list`, место, 14 копий."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import backup_postgres  # noqa: E402

sys.path.remove(str(ROOT / "scripts"))


def fake_docker(monkeypatch: pytest.MonkeyPatch, *, readable: bool = True) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(args: list[str], **kwargs: Any) -> Any:
        calls.append(args)
        if "pg_dump" in args:
            kwargs["stdout"].write(b"PGDMP synthetic")
            return SimpleNamespace(returncode=0)
        listing = b"; header\n1; 2615 2200 SCHEMA - public\n2; 1259 16385 TABLE public houses\n"
        return SimpleNamespace(returncode=0 if readable else 1, stdout=listing if readable else b"")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def old_dumps(directory: Path, count: int) -> None:
    for day in range(count):
        (directory / f"domsignal-202609{day + 1:02d}T000000000000Z.dump").write_bytes(b"old")


def test_a_verified_dump_keeps_fourteen_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = fake_docker(monkeypatch)
    old_dumps(tmp_path, 15)
    (tmp_path / "manual-before-deploy.dump").write_bytes(b"manual")
    target, entries = backup_postgres.backup(
        container="db", user="u", database="d", directory=tmp_path
    )
    assert entries == 2 and target.read_bytes() == b"PGDMP synthetic"
    assert ["docker", "exec", "-i", "db", "pg_restore", "--list"] in calls
    assert len(list(tmp_path.glob("domsignal-*.dump"))) == backup_postgres.KEEP == 14
    assert (tmp_path / "manual-before-deploy.dump").exists()  # чужие файлы не трогаем


def test_an_unreadable_dump_is_removed_and_rotates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_docker(monkeypatch, readable=False)
    old_dumps(tmp_path, 15)
    with pytest.raises(backup_postgres.BackupError, match="pg_restore --list"):
        backup_postgres.backup(container="db", user="u", database="d", directory=tmp_path)
    assert len(list(tmp_path.glob("domsignal-*.dump"))) == 15
    assert not list(tmp_path.glob("*.partial"))


def test_low_disk_space_refuses_before_dumping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = fake_docker(monkeypatch)
    monkeypatch.setattr(backup_postgres, "free_mb", lambda directory: 100)
    with pytest.raises(backup_postgres.BackupError, match="free"):
        backup_postgres.backup(container="db", user="u", database="d", directory=tmp_path)
    assert calls == []
