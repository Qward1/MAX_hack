"""Explicit manual group intake. No NLP, participant sync or implicit access grants."""

from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.bot.max_updates import MaxEvent
from domsignal.contracts.chat_connections import GroupMessage
from domsignal.contracts.jobs import InboundAccepted
from domsignal.db.models import InboxReceipt
from domsignal.db.repositories.chat_connections import ChatRepository
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.services.chat_connections import ChatConnectionService


class MaxWebhookService:
    def __init__(self, connections: ChatConnectionService) -> None:
        self.connections = connections

    async def accept(self, session: AsyncSession, event: MaxEvent) -> InboundAccepted:
        async with session.begin():
            repo = ChatRepository(session)
            await repo.lock(f"event:{event.event_id}")
            reliability = ReliabilityRepository(session)
            if await reliability.inbox(event.event_id):
                return InboundAccepted(
                    event_id=event.event_id, accepted=True, duplicate=True, job_id=None
                )
            # Correlation secrets / raw unbound messages are never stored in the inbox.
            session.add(
                InboxReceipt(
                    event_id=event.event_id,
                    event_type=event.kind,
                    payload={"chat_id": event.chat_id},
                )
            )
            job_id = None
            if event.kind == "bot_started" and event.token and event.actor:
                await self.connections.claim(
                    session, token=event.token, connector=event.actor, occurred_at=event.occurred_at
                )
            elif event.kind == "bot_added" and event.chat_id and event.actor:
                await self.connections.bot_added(
                    session,
                    chat_id=event.chat_id,
                    actor=event.actor,
                    occurred_at=event.occurred_at,
                    is_channel=event.is_channel,
                )
            elif event.kind == "bot_removed" and event.chat_id:
                await self.connections.bot_removed(
                    session, chat_id=event.chat_id, occurred_at=event.occurred_at
                )
            elif (
                event.kind == "message_created"
                and event.chat_id
                and event.actor
                and event.text
                and event.text.startswith("/report ")
            ):
                binding = await repo.active_binding(event.chat_id)
                if (
                    binding is not None
                    and binding.activated_at is not None
                    and event.occurred_at >= binding.activated_at
                ):
                    message = GroupMessage(
                        event_id=event.event_id,
                        chat_id=event.chat_id,
                        external_user_id=event.actor,
                        occurred_at=event.occurred_at,
                        text=event.text,
                        chat_binding_id=binding.id,
                        binding_version=binding.binding_version,
                    )
                    job = await reliability.add_job(
                        kind="max.group.report",
                        payload=message.model_dump(mode="json"),
                        priority=50,
                    )
                    job_id = job.id
        return InboundAccepted(
            event_id=event.event_id, accepted=True, duplicate=False, job_id=job_id
        )
