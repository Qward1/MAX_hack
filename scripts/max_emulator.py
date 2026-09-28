"""Эмулятор MAX для локального стенда (F1 §3.2, B-09): проверить бота без MAX.

Стенд запускается с `MAX_TRANSPORT=record`, локальными `MAX_WEBHOOK_SECRET`,
`MAX_BOT_TOKEN`, `MAX_BOT_USERNAME` и общим каталогом `MAX_RECORD_DIR`
(по умолчанию `output/max-record`). Эмулятор:

* ведёт состояние чатов в `<dir>/state.json` — из него двойник MAX API отвечает
  боту о чате, правах бота и участниках;
* отправляет в вебхук стенда события MAX, подписанные локальным секретом:
  сообщение в группе и в личке, `bot_added`, `user_added`, `user_removed`,
  `bot_started` со ссылкой, нажатие кнопки;
* открывает мини-приложение: подписывает данные входа токеном бота (со
  `start_param`) и входит через `/api/v1/auth/max`;
* показывает, что бот отправил (`outbox`), — двойник пишет исходящие в
  `<dir>/outbox.jsonl`.

    uv run python scripts/max_emulator.py chat --chat-id -1001 --title "Дом" --admin 1001
    uv run python scripts/max_emulator.py bot-added --chat-id -1001 --by 1001
    uv run python scripts/max_emulator.py message --chat-id -1001 --user 1002 --text "Лифт стоит"
    uv run python scripts/max_emulator.py outbox

В production эмулятор бесполезен и невозможен: вебхук там принимает только
секрет production, а `MAX_TRANSPORT=record` отвергает проверка настроек.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import itertools
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

DEFAULT_BOT_ID = 900000001
_counter = itertools.count(1)


def now_ms() -> int:
    return int(time.time() * 1000)


class Emulator:
    def __init__(self, base_url: str, secret: str, directory: Path, token: str | None) -> None:
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self.directory = directory
        self.token = token
        directory.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ состояние
    def state(self) -> dict[str, Any]:
        value: dict[str, Any] = {}
        try:
            loaded = json.loads((self.directory / "state.json").read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                value = loaded
        except (OSError, ValueError):
            pass
        value.setdefault("bot", {"user_id": DEFAULT_BOT_ID})
        value.setdefault("chats", {})
        return value

    def save(self, value: dict[str, Any]) -> None:
        path = self.directory / "state.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def chat(
        self, chat_id: int, title: str, admin: int | None, members: list[int], bot_admin: bool
    ) -> None:
        state = self.state()
        chat = state["chats"].setdefault(str(chat_id), {"members": {}})
        chat.update(title=title, bot_admin=bot_admin, bot_present=chat.get("bot_present", False))
        if admin is not None:
            chat["owner_id"] = admin
            chat["members"][str(admin)] = {"is_admin": True}
        for user in members:
            chat["members"].setdefault(str(user), {"is_admin": False})
        self.save(state)

    def set_member(self, chat_id: int, user: int, present: bool) -> None:
        state = self.state()
        chat = state["chats"].setdefault(str(chat_id), {"members": {}, "title": None})
        if present:
            chat["members"].setdefault(str(user), {"is_admin": False})
        else:
            chat["members"].pop(str(user), None)
        self.save(state)

    def set_bot(self, chat_id: int, present: bool) -> None:
        state = self.state()
        chat = state["chats"].setdefault(str(chat_id), {"members": {}, "title": None})
        chat["bot_present"] = present
        self.save(state)

    # ------------------------------------------------------------ события
    def post(self, update: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/max/webhook",
            data=json.dumps(update, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Max-Bot-Api-Secret": self.secret},
            method="POST",
        )
        return self._send(request)

    def _send(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8")
                return {"status": response.status, "body": json.loads(body) if body else None}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            return {"status": exc.code, "body": body[:500]}

    @staticmethod
    def user(user_id: int, name: str | None = None, is_bot: bool = False) -> dict[str, Any]:
        return {"user_id": user_id, "name": name or f"Житель {user_id}", "is_bot": is_bot}

    def lifecycle(
        self, kind: str, chat_id: int, user: dict[str, Any], payload: str | None = None
    ) -> dict[str, Any]:
        update: dict[str, Any] = {
            "update_type": kind,
            "timestamp": now_ms(),
            "chat_id": chat_id,
            "user": user,
        }
        if payload:
            update["payload"] = payload
        return self.post(update)

    def message(
        self, chat_id: int, user_id: int, text: str, dialog: bool, name: str | None
    ) -> dict[str, Any]:
        mid = f"mid.emu{now_ms()}{next(_counter)}"
        update = {
            "update_type": "message_created",
            "timestamp": now_ms(),
            "message": {
                "sender": self.user(user_id, name),
                "recipient": {"chat_id": chat_id, "chat_type": "dialog" if dialog else "chat"},
                "body": {"mid": mid, "text": text},
                "timestamp": now_ms(),
            },
        }
        result = self.post(update)
        result["mid"] = mid
        return result

    def callback(
        self, user_id: int, payload: str, message_id: str, chat_id: int | None
    ) -> dict[str, Any]:
        dialog = chat_id is None
        update = {
            "update_type": "message_callback",
            "timestamp": now_ms(),
            "callback": {
                "timestamp": now_ms(),
                "callback_id": f"cb.emu{now_ms()}{next(_counter)}",
                "payload": payload,
                "user": self.user(user_id),
            },
            "message": {
                "sender": self.user(self.state()["bot"]["user_id"], "ДомСигнал", is_bot=True),
                "recipient": {
                    "chat_id": user_id if dialog else chat_id,
                    "chat_type": "dialog" if dialog else "chat",
                },
                "body": {"mid": message_id, "text": None},
                "timestamp": now_ms(),
            },
        }
        return self.post(update)

    # ------------------------------------------------------------ мини-приложение
    def init_data(self, user_id: int, name: str, start_param: str | None) -> str:
        if not self.token:
            raise SystemExit("MAX_BOT_TOKEN не задан: без него данные входа не подписать")
        fields = {
            "auth_date": str(int(time.time())),
            "query_id": f"emu{now_ms()}",
            "user": json.dumps(
                {"id": user_id, "first_name": name}, ensure_ascii=False, separators=(",", ":")
            ),
        }
        if start_param:
            fields["start_param"] = start_param
        check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", self.token.encode("utf-8"), hashlib.sha256).digest()
        fields["hash"] = hmac.new(secret, check.encode("utf-8"), hashlib.sha256).hexdigest()
        return urlencode(fields)

    def webapp(
        self, user_id: int, name: str, start_param: str | None, show_token: bool = False
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/api/v1/auth/max",
            data=json.dumps({"init_data": self.init_data(user_id, name, start_param)}).encode(
                "utf-8"
            ),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        result = self._send(request)
        token = (
            (result.get("body") or {}).get("access_token")
            if isinstance(result.get("body"), dict)
            else None
        )
        if token:
            me = urllib.request.Request(
                f"{self.base_url}/api/v1/me", headers={"Authorization": f"Bearer {token}"}
            )
            result["me"] = self._send(me).get("body")
            result["body"] = {"access_token": "(выдан)"}
            if show_token:
                # Для приёмочных тестов: токен локального стенда, в production его нет.
                result["token"] = token
        return result

    # ------------------------------------------------------------ исходящие
    def outbox(self, since: int = 0) -> list[dict[str, Any]]:
        path = self.directory / "outbox.jsonl"
        if not path.exists():
            return []
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return [row for row in rows if row.get("at", 0) >= since]


def describe(row: dict[str, Any]) -> str:
    params = row.get("params", {})
    where = (
        f"личка {params['user_id']}"
        if "user_id" in params
        else f"чат {params['chat_id']}"
        if "chat_id" in params
        else f"сообщение {params.get('message_id') or params.get('callback_id', '')}"
    )
    body = row.get("body") or {}
    message = body.get("message", body) if isinstance(body, dict) else {}
    text = message.get("text") or body.get("notification") or ""
    buttons = [
        button.get("text", "")
        for attachment in message.get("attachments", []) or []
        for rows in (attachment.get("payload", {}) or {}).get("buttons", []) or []
        for button in rows
    ]
    stamp = time.strftime("%H:%M:%S", time.localtime(row.get("at", 0) / 1000))
    line = f"{stamp} {row.get('kind')} → {where}: {text}"
    if buttons:
        line += "  [" + " | ".join(buttons) + "]"
    return line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--base-url", default=os.getenv("EMULATOR_BASE_URL", "http://127.0.0.1:8000")
    )
    parser.add_argument("--dir", default=os.getenv("MAX_RECORD_DIR", "output/max-record"))
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("chat", help="создать или обновить групповой чат в состоянии")
    p.add_argument("--chat-id", type=int, required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--admin", type=int, help="владелец и администратор группы")
    p.add_argument("--member", type=int, action="append", default=[])
    p.add_argument("--no-bot-admin", action="store_true", help="бот без прав администратора")
    for name in ("bot-added", "bot-removed"):
        p = sub.add_parser(name)
        p.add_argument("--chat-id", type=int, required=True)
        p.add_argument("--by", type=int, required=True, help="кто добавил или удалил бота")
    for name in ("user-added", "user-removed"):
        p = sub.add_parser(name)
        p.add_argument("--chat-id", type=int, required=True)
        p.add_argument("--user", type=int, required=True)
    p = sub.add_parser("message", help="сообщение в группе")
    p.add_argument("--chat-id", type=int, required=True)
    p.add_argument("--user", type=int, required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--name")
    p = sub.add_parser("dm", help="сообщение боту в личку")
    p.add_argument("--user", type=int, required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--name")
    p = sub.add_parser("start", help="bot_started: человек открыл бота, в том числе по ссылке")
    p.add_argument("--user", type=int, required=True)
    p.add_argument("--payload")
    p = sub.add_parser("callback", help="нажатие кнопки")
    p.add_argument("--user", type=int, required=True)
    p.add_argument("--payload", required=True)
    p.add_argument("--message-id", required=True)
    p.add_argument("--chat-id", type=int, help="кнопка поста в группе; без него — в личке")
    p = sub.add_parser("webapp", help="открыть мини-приложение: данные входа со start_param")
    p.add_argument("--user", type=int, required=True)
    p.add_argument("--name", default="Житель")
    p.add_argument("--start-param")
    p.add_argument("--show-token", action="store_true", help="напечатать токен сессии жителя")
    p = sub.add_parser("outbox", help="что отправил бот")
    p.add_argument("--since-ms", type=int, default=0)
    p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    # Значения по умолчанию совпадают с локальными в compose.yaml; production их не примет.
    secret = os.getenv("MAX_WEBHOOK_SECRET") or "local-emulator-secret"
    token = os.getenv("MAX_BOT_TOKEN") or "local-emulator-token"
    emulator = Emulator(args.base_url, secret, Path(args.dir), token)
    command = args.command
    if command == "outbox":
        for row in emulator.outbox(args.since_ms):
            print(json.dumps(row, ensure_ascii=False) if args.json else describe(row))
        return 0
    if command == "chat":
        emulator.chat(args.chat_id, args.title, args.admin, args.member, not args.no_bot_admin)
        print(json.dumps({"chat": args.chat_id, "saved": True}))
        return 0
    if command in {"bot-added", "bot-removed"}:
        emulator.set_bot(args.chat_id, command == "bot-added")
        result = emulator.lifecycle(command.replace("-", "_"), args.chat_id, emulator.user(args.by))
    elif command in {"user-added", "user-removed"}:
        emulator.set_member(args.chat_id, args.user, command == "user-added")
        result = emulator.lifecycle(
            command.replace("-", "_"), args.chat_id, emulator.user(args.user)
        )
    elif command == "message":
        result = emulator.message(args.chat_id, args.user, args.text, False, args.name)
    elif command == "dm":
        result = emulator.message(args.user, args.user, args.text, True, args.name)
    elif command == "start":
        result = emulator.lifecycle(
            "bot_started", args.user, emulator.user(args.user), args.payload
        )
    elif command == "callback":
        result = emulator.callback(args.user, args.payload, args.message_id, args.chat_id)
    else:
        result = emulator.webapp(args.user, args.name, args.start_param, args.show_token)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if 200 <= int(result.get("status", 500)) < 300 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main())
