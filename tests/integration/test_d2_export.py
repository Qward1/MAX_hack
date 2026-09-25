"""P7b → DEV-A: выгрузка сессии D2 из буфера — формат P6, без людей и MAX id."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from domsignal.tools.d2_export import ORIGIN, export, message_hash
from tests.integration.passive_harness import NEIGHBOURS, pv  # noqa: F401
from tests.integration.test_passive_signals import ago

LINES = (
    "Лифт во втором подъезде опять стоит",
    "Да, с утра не едет",
    "Продам коляску, почти новая",
)


async def test_the_export_is_the_p6_format_without_identifiers(pv) -> None:  # noqa: F811
    binding = await pv.bind()
    before = await pv.say("Реплика до начала сессии", actor=NEIGHBOURS[0], at=ago(900))
    first = await pv.say(LINES[0], actor=NEIGHBOURS[0], at=ago(300))
    await pv.say(LINES[1], actor=NEIGHBOURS[1], at=ago(290), reply_to=first)
    await pv.say(LINES[2], actor=NEIGHBOURS[2], at=ago(280))
    async with pv.container.session_factory() as session:
        rows = await export(
            session,
            binding_id=binding,
            session_label="S1",
            since=ago(310),
            until=ago(270),
            display_timezone="Europe/Moscow",
        )
        await session.rollback()

    assert [row["text"] for row in rows] == list(LINES), "только интервал сессии, по времени"
    assert all(
        set(row) == {"session", "mid", "sent_at", "author", "reply_to", "text", "synthetic",
                     "origin"}
        for row in rows
    )
    assert all(row["synthetic"] is True and row["origin"] == ORIGIN for row in rows)
    assert [row["author"] for row in rows] == ["A", "B", "C"]
    assert rows[1]["reply_to"] == rows[0]["mid"] == message_hash(binding, first)
    assert rows[0]["reply_to"] is None and rows[0]["mid"].startswith("h:")
    assert rows[0]["sent_at"].endswith("+03:00")
    # Каждое поле имеет строгую форму — места для MAX id или `mid` в выгрузке нет.
    assert all(row["session"] == "S1" for row in rows)
    assert all(HASHED_MID.fullmatch(row["mid"]) for row in rows)
    assert all(row["reply_to"] is None or HASHED_MID.fullmatch(row["reply_to"]) for row in rows)
    assert all(datetime.fromisoformat(row["sent_at"]).tzinfo is not None for row in rows)
    dumped = json.dumps(rows, ensure_ascii=False)
    assert first not in dumped and before not in dumped
    # Идентификатор ищется отдельным токеном: «714» внутри hex-хэша
    # `h:…df71496…` — совпадение цифр, а не утечка (так упал CI #103).
    for actor in NEIGHBOURS:
        assert not _token(str(actor)).search(dumped)


HASHED_MID = re.compile(r"h:[0-9a-f]{16}")


def _token(value: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![0-9A-Za-z]){re.escape(value)}(?![0-9A-Za-z])")


def test_an_id_inside_a_hash_is_not_a_leak_but_a_bare_id_is() -> None:
    assert not _token("714").search('{"mid": "h:f8dab767df71496a"}')
    assert _token("714").search('{"author": "714"}')
    assert _token("714").search('{"mid": "714:abc"}')


async def test_the_export_reads_only_the_given_binding_and_changes_nothing(pv) -> None:  # noqa: F811
    binding = await pv.bind()
    await pv.say(LINES[0], at=ago(60))
    async with pv.container.session_factory() as session:
        other = await export(
            session,
            binding_id=binding.__class__(int=0),
            session_label="S2",
            since=ago(120),
            until=ago(0) + timedelta(seconds=1),
            display_timezone="Europe/Moscow",
        )
        await session.rollback()
    assert other == []
