"""Explicit injection only. Never imported by production composition."""

from domsignal.bot.messaging import MessagingError, PersonalMessage, SentMessage


class RecordingMaxMessagingProvider:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, PersonalMessage]] = []
        self.edited: list[tuple[str, PersonalMessage]] = []
        self.answered: list[tuple[str, PersonalMessage]] = []
        self.chat_sent: list[tuple[str, str, PersonalMessage]] = []
        self.errors: list[MessagingError] = []
        # Номера сообщений не повторяются, даже если тест убрал запись из списка:
        # MAX не выдаёт один mid дважды (уникальность provider_message_id).
        self.personal_count = 0
        self.chat_count = 0

    def fail_if_requested(self) -> None:
        if self.errors:
            raise self.errors.pop(0)

    async def send_personal_message(
        self,
        destination: str,
        message: PersonalMessage,
    ) -> SentMessage:
        self.fail_if_requested()
        self.personal_count += 1
        mid = f"mid.test-{self.personal_count}"
        self.sent.append((destination, mid, message))
        return SentMessage(mid)

    async def edit_message(self, message_id: str, message: PersonalMessage) -> None:
        self.fail_if_requested()
        self.edited.append((message_id, message))

    async def answer_callback(self, callback_id: str, message: PersonalMessage) -> None:
        self.fail_if_requested()
        self.answered.append((callback_id, message))

    async def send_chat_message(self, chat_id: str, message: PersonalMessage) -> SentMessage:
        self.fail_if_requested()
        self.chat_count += 1
        mid = f"mid.chat-{self.chat_count}"
        self.chat_sent.append((chat_id, mid, message))
        return SentMessage(mid)
