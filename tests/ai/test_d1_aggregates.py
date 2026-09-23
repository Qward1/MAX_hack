"""D1: агрегаты реальных выгрузок — только числа, ни одной строки входа.

Проверяется на **синтетической** выгрузке того же формата, что и настоящие
(Telegram Desktop JSON и WhatsApp txt). Настоящие выгрузки тест не читает.
"""

from __future__ import annotations

import ast
import json
import pathlib

from evaluation import d1_aggregates

SECRET_TEXTS = (
    "Синтетическая жалоба: в подъезде №7 лифт встал, зовите Мастерова",
    "у нас тоже, уникальная-метка-зелёный-слон",
    "продам велосипед уникальная-метка-жёлтый-кит",
    "газом пахнет на лестнице уникальная-метка-красный-ёж",
)
SECRET_NAMES = ("Аглая Синтетическая", "Пётр Тестовый", "user424242", "user515151")
CHAT_NAME = "Дом на Синтетической улице 99"
DAY_STRINGS = ("2025-03-14", "14.03.2025", "14.03.25", "2025-04-02", "02.04.2025")


def _telegram(path: pathlib.Path) -> None:
    document = {
        "name": CHAT_NAME,
        "type": "private_supergroup",
        "id": 777000111,
        "messages": [
            {
                "id": 1,
                "type": "message",
                "date": "2025-03-14T10:00:00",
                "date_unixtime": "1741946400",
                "from": SECRET_NAMES[0],
                "from_id": SECRET_NAMES[2],
                "text": SECRET_TEXTS[0],
                "text_entities": [{"type": "plain", "text": SECRET_TEXTS[0]}],
            },
            {
                "id": 2,
                "type": "message",
                "date": "2025-03-14T10:01:00",
                "date_unixtime": "1741946460",
                "from": SECRET_NAMES[1],
                "from_id": SECRET_NAMES[3],
                "reply_to_message_id": 1,
                "text": [SECRET_TEXTS[1]],
                "text_entities": [],
            },
            {
                "id": 3,
                "type": "service",
                "date": "2025-03-14T11:00:00",
                "actor": SECRET_NAMES[0],
                "action": "invite_members",
            },
            {
                "id": 4,
                "type": "message",
                "date": "2025-04-02T09:00:00",
                "date_unixtime": "1743584400",
                "from": SECRET_NAMES[0],
                "from_id": SECRET_NAMES[2],
                "text": [{"type": "bold", "text": SECRET_TEXTS[3]}],
                "text_entities": [],
            },
        ],
    }
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def _whatsapp(path: pathlib.Path) -> None:
    path.write_text(
        "\n".join(
            [
                f"14.03.2025, 12:00 - {SECRET_NAMES[0]} создал(а) группу «{CHAT_NAME}»",
                f"14.03.2025, 12:05 - {SECRET_NAMES[0]}: {SECRET_TEXTS[2]}",
                "вторая строка того же сообщения уникальная-метка-синий-лось",
                f"14.03.2025, 12:07 - {SECRET_NAMES[1]}: <Без медиафайлов>",
                f"[02.04.25, 09:00:00] {SECRET_NAMES[1]}: {SECRET_TEXTS[0]}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _exports(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "exports"
    (root / f"ChatExport {CHAT_NAME}").mkdir(parents=True)
    _telegram(root / f"ChatExport {CHAT_NAME}" / "result.json")
    _whatsapp(root / f"Чат WhatsApp с {CHAT_NAME}.txt")
    return root


def _all_inputs() -> list[str]:
    return [
        *SECRET_TEXTS,
        *SECRET_NAMES,
        CHAT_NAME,
        *DAY_STRINGS,
        "уникальная-метка",
        "777000111",
        "1741946400",
        "result.json",
        "WhatsApp с",
    ]


def test_aggregates_are_numbers_only(tmp_path: pathlib.Path) -> None:
    result = d1_aggregates.run(_exports(tmp_path), rub_per_window=0.3)
    body = json.dumps(result, ensure_ascii=False)
    for secret in _all_inputs():
        assert secret not in body, secret
    telegram, whatsapp = sorted(result["chats"], key=lambda chat: chat["format"])
    assert telegram["format"] == "telegram"
    assert telegram["messages"] == 3
    assert telegram["authors"] == 2
    assert telegram["reply_share"] == round(1 / 3, 4)
    assert telegram["months"] == {"first": "2025-03", "last": "2025-04", "active_months": 2}
    assert telegram["danger_rules_per_1000"]["active"] > 0
    assert whatsapp["format"] == "whatsapp"
    assert whatsapp["messages"] == 2
    assert whatsapp["authors"] == 2
    assert whatsapp["rub_per_month_estimate"]["rub_per_window"] == 0.3


def test_structure_prints_keys_and_types_only(tmp_path: pathlib.Path) -> None:
    result = d1_aggregates.structure(_exports(tmp_path))
    body = json.dumps(result, ensure_ascii=False)
    for secret in _all_inputs():
        assert secret not in body, secret
    telegram = next(entry for entry in result["files"] if entry["suffix"] == ".json")
    assert "messages" in telegram["keys"]
    assert telegram["message_keys"]["from_id"]["types"] == ["str"]
    whatsapp = next(entry for entry in result["files"] if entry["suffix"] == ".txt")
    assert whatsapp["line_forms"]["dated_android"] == 3


def test_script_cannot_reach_a_model() -> None:
    """Скрипт D1 не импортирует ни провайдера, ни сетевой клиент."""
    source = pathlib.Path(d1_aggregates.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = ("httpx", "requests", "urllib", "domsignal.ai.providers", "domsignal.ai.facade")
    assert not [name for name in imported if name.startswith(forbidden)], imported
    assert "evaluation.p6_eval" not in imported and "evaluation.select_models" not in imported
