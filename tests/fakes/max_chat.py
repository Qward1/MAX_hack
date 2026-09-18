"""Deterministic test double. Never imported by the application package."""

from dataclasses import dataclass, field

from domsignal.bot.chat_provider import ChatInfo, ChatMember, MaxProviderError


@dataclass
class FakeMaxChatProvider:
    chats: dict[str, ChatInfo] = field(default_factory=dict)
    bots: dict[str, ChatMember] = field(default_factory=dict)
    admins: dict[str, tuple[ChatMember, ...]] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def configure(self, chat_id: str, *, connector: str = "101") -> None:
        self.chats[chat_id] = ChatInfo(chat_id, "chat", "Synthetic chat", True)
        self.bots[chat_id] = ChatMember(
            "999", True, permissions=frozenset({"read_all_messages"}), is_bot=True
        )
        self.admins[chat_id] = (ChatMember(connector, True),)

    def check(self, chat_id: str, method: str) -> None:
        self.calls.append((method, chat_id))
        error = self.failures.get(chat_id)
        if error:
            if error in {"timeout", "429", "5xx"}:
                raise MaxProviderError("max_temporarily_unavailable", temporary=True)
            raise MaxProviderError(error)
        if chat_id not in self.chats:
            raise MaxProviderError("max_chat_not_found")

    async def get_chat_info(self, chat_id: str) -> ChatInfo:
        self.check(chat_id, "info")
        return self.chats[chat_id]

    async def get_bot_membership(self, chat_id: str) -> ChatMember:
        self.check(chat_id, "bot")
        return self.bots[chat_id]

    async def get_chat_admins(self, chat_id: str) -> tuple[ChatMember, ...]:
        self.check(chat_id, "admins")
        return self.admins[chat_id]
