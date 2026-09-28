"""Двойник MAX API для локального стенда (F1 §3.2, B-09): `MAX_TRANSPORT=record`.

Исходящие вызовы бота не уходят в MAX: `POST/PUT/DELETE /messages` и
`POST /answers` дописываются строкой JSON в `<MAX_RECORD_DIR>/outbox.jsonl`,
а чтение чатов (`GET /chats/{id}`, `/members/me`, `/members/admins`,
`/members?user_ids=`) отвечает из `<MAX_RECORD_DIR>/state.json`, который ведёт
эмулятор `scripts/max_emulator.py`. Формы ответов — как у документированного
MAX API, поэтому код бота работает без изменений. В production режим
невозможен: проверка настроек требует `MAX_TRANSPORT=webhook`.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

#: Идентификатор бота в состоянии эмулятора по умолчанию.
DEFAULT_BOT_ID = 900000001


def read_state(directory: Path) -> dict[str, Any]:
    try:
        value = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"bot": {"user_id": DEFAULT_BOT_ID}, "chats": {}}
    return value if isinstance(value, dict) else {"bot": {"user_id": DEFAULT_BOT_ID}, "chats": {}}


class RecordingMaxApi(httpx.AsyncBaseTransport):
    """httpx-транспорт: запись исходящих и ответы о чатах из файла состояния."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def _json(self, status: int, value: Any) -> httpx.Response:
        return httpx.Response(status, json=value)

    def _record(self, entry: dict[str, Any]) -> int:
        at = int(time.time() * 1000)
        entry["at"] = at
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        path = self.directory / "outbox.jsonl"
        # Одна строка — одна запись с O_APPEND: процессы api и worker пишут в один файл.
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
        return at

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)
        body = json.loads(request.content) if request.content else {}
        state = read_state(self.directory)
        bot_id = int(state.get("bot", {}).get("user_id", DEFAULT_BOT_ID))
        if path.startswith("/chats/") and request.method == "GET":
            return self._chat(path, params, state, bot_id)
        if path == "/messages" and request.method == "POST":
            at = self._record({"kind": "send", "params": params, "body": body})
            mid = f"mid.rec{at}"
            if "user_id" in params:
                user = int(params["user_id"])
                recipient: dict[str, Any] = {
                    "user_id": user,
                    "chat_id": user,
                    "chat_type": "dialog",
                }
            else:
                recipient = {"chat_id": int(params.get("chat_id", "0")), "chat_type": "chat"}
            return self._json(
                200,
                {
                    "message": {
                        "recipient": recipient,
                        "body": {"mid": mid, "text": body.get("text")},
                    }
                },
            )
        if path == "/messages" and request.method in {"PUT", "DELETE"}:
            self._record(
                {
                    "kind": "edit" if request.method == "PUT" else "delete",
                    "params": params,
                    "body": body,
                }
            )
            return self._json(200, {"success": True})
        if path == "/answers" and request.method == "POST":
            self._record({"kind": "answer", "params": params, "body": body})
            return self._json(200, {"success": True})
        return self._json(404, {"code": "not.found"})

    def _chat(
        self, path: str, params: dict[str, str], state: dict[str, Any], bot_id: int
    ) -> httpx.Response:
        parts = path.strip("/").split("/")
        chat = state.get("chats", {}).get(parts[1])
        if chat is None:
            return self._json(404, {"code": "chat.not.found"})
        chat_id = int(parts[1])
        members: dict[str, Any] = chat.get("members", {})
        if len(parts) == 2:
            return self._json(
                200,
                {
                    "chat_id": chat_id,
                    "type": "chat",
                    "status": "active" if chat.get("bot_present", True) else "removed",
                    "title": chat.get("title"),
                    "owner_id": chat.get("owner_id"),
                },
            )
        if parts[2:] == ["members", "me"]:
            if not chat.get("bot_present", True):
                return self._json(403, {"code": "chat.denied"})
            return self._json(
                200,
                {
                    "user_id": bot_id,
                    "is_admin": bool(chat.get("bot_admin", True)),
                    "is_owner": False,
                    "is_bot": True,
                    "permissions": chat.get("bot_permissions", ["read_all_messages", "write"]),
                },
            )
        if parts[2:] == ["members", "admins"]:
            admins = [
                {
                    "user_id": int(user_id),
                    "is_admin": True,
                    "is_owner": str(chat.get("owner_id")) == user_id,
                    "is_bot": False,
                    "permissions": ["read_all_messages", "write", "add_admins"],
                }
                for user_id, member in members.items()
                if member.get("is_admin")
            ]
            return self._json(200, {"members": admins})
        if parts[2:] == ["members"]:
            wanted = params.get("user_ids", "")
            found = [
                {"user_id": int(user_id), "is_bot": False}
                for user_id in wanted.split(",")
                if user_id in members
            ]
            return self._json(200, {"members": found})
        return self._json(404, {"code": "not.found"})
