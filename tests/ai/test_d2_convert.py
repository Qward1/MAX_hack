"""D2: выгрузка сессии сопоставляется с карточками по порядку реплик участника."""

from __future__ import annotations

from evaluation.d2_convert import convert, load_truth


def _message(mid: str, minute: int, author: str, text: str, reply: str | None = None) -> dict:
    return {
        "session": "S1",
        "mid": mid,
        "sent_at": f"2026-09-24T19:{minute:02d}:00+03:00",
        "author": author,
        "reply_to": reply,
        "text": text,
        "synthetic": True,
        "origin": "d2_roleplay",
    }


def test_messages_follow_participant_cards_in_order() -> None:
    cards, incidents = load_truth()
    export = [
        _message("h1", 0, "A", "лифт во втором опять не едет"),
        _message("h2", 1, "B", "у меня тоже", reply="h1"),
        _message("h3", 2, "Z", "всем привет"),
        _message("h4", 3, "A", "почему квитанция выросла?"),
    ]
    rows = convert(export, {"S1": {"A": "P01", "B": "P02"}}, cards, incidents)
    assert len(rows) == 1
    lines = rows[0]["lines"]
    assert [line["role"] for line in lines] == ["new_problem", "me_too", None, "out_of_scope"]
    assert lines[0]["incidents"] == ["S1.I1"] and lines[1]["incidents"] == ["S1.I1"]
    assert lines[1]["reply_to"] == 1
    assert lines[3]["offset_s"] == 180
    assert [item["id"] for item in rows[0]["incidents"]] == ["S1.I1"]
    assert rows[0]["incidents"][0]["expected_route_type"] == "uk_internal"
    assert rows[0]["synthetic"] is True
