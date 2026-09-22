"""Explicit injection only. Never imported by production composition."""

from domsignal.bot.messaging import MessagingError, PersonalMessage, SentMessage


class RecordingMaxMessagingProvider:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, PersonalMessage]] = []
        self.edited: list[tuple[str, PersonalMessage]] = []
        self.answered: list[tuple[str, PersonalMessage]] = []
        self.chat_sent: list[tuple[str, str, PersonalMessage]] = []
        self.errors: list[MessagingError] = []

    def fail_if_requested(self) -> None:
        if self.errors:
            raise self.errors.pop(0)

    async def send_personal_message(
        self,
        destination: str,
        message: PersonalMessage,
    ) -> SentMessage:
        self.fail_if_requested()
        mid = f"mid.test-{len(self.sent) + 1}"
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
        mid = f"mid.chat-{len(self.chat_sent) + 1}"
        self.chat_sent.append((chat_id, mid, message))
        return SentMessage(mid)
