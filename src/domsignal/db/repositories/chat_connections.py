from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.core.chat_connections import TERMINAL
from domsignal.db.models import HouseManagement, ManagementCompany
from domsignal.db.models.chat_connections import ChatBinding, ConnectionRequest, MAXChat


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock(self, key: str) -> None:
        # Serializes absence checks too; no Python process-local locks.
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": "domsignal:chat:" + key},
        )

    async def request(self, request_id: UUID, *, lock: bool = False) -> ConnectionRequest | None:
        query = select(ConnectionRequest).where(ConnectionRequest.id == request_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return cast(ConnectionRequest | None, await self.session.scalar(query))

    async def by_token(self, digest: str) -> ConnectionRequest | None:
        return cast(
            ConnectionRequest | None,
            await self.session.scalar(
                select(ConnectionRequest).where(ConnectionRequest.token_hash == digest)
            ),
        )

    async def open_for_connector(self, connector: str) -> list[ConnectionRequest]:
        return list(
            await self.session.scalars(
                select(ConnectionRequest)
                .where(
                    ConnectionRequest.connector_max_user_id == connector,
                    ConnectionRequest.status.not_in(TERMINAL),
                )
                .order_by(ConnectionRequest.id)
                .with_for_update()
            )
        )

    async def open_for_initiator(
        self,
        actor_id: UUID,
        management_id: UUID,
    ) -> list[ConnectionRequest]:
        return list(
            await self.session.scalars(
                select(ConnectionRequest).where(
                    ConnectionRequest.initiated_by_user_id == actor_id,
                    ConnectionRequest.management_id == management_id,
                    ConnectionRequest.status.not_in(TERMINAL),
                )
            )
        )

    async def open_for_house(self, house_id: UUID) -> list[ConnectionRequest]:
        """U-01: незавершённые запросы подключения дома — у дома он один."""
        return list(
            await self.session.scalars(
                select(ConnectionRequest).where(
                    ConnectionRequest.house_id == house_id,
                    ConnectionRequest.status.not_in(TERMINAL),
                )
            )
        )

    async def chat(self, chat_id: str) -> MAXChat | None:
        return cast(
            MAXChat | None,
            await self.session.scalar(
                select(MAXChat)
                .where(MAXChat.max_chat_id == chat_id)
                .execution_options(populate_existing=True)
            ),
        )

    async def binding(self, binding_id: UUID) -> ChatBinding | None:
        return cast(
            ChatBinding | None,
            await self.session.scalar(
                select(ChatBinding)
                .where(ChatBinding.id == binding_id)
                .execution_options(populate_existing=True)
            ),
        )

    async def active_binding(self, chat_id: str) -> ChatBinding | None:
        return cast(
            ChatBinding | None,
            await self.session.scalar(
                select(ChatBinding)
                .where(
                    ChatBinding.max_chat_id == chat_id,
                    ChatBinding.status == "active",
                )
                .execution_options(populate_existing=True)
            ),
        )

    async def completed_binding(self, request_id: UUID) -> ChatBinding | None:
        return cast(
            ChatBinding | None,
            await self.session.scalar(
                select(ChatBinding).where(
                    ChatBinding.connection_request_id == request_id,
                )
            ),
        )

    async def management_state(self, management_id: UUID, now: datetime) -> str | None:
        row = (
            await self.session.execute(
                select(HouseManagement, ManagementCompany)
                .join(ManagementCompany, HouseManagement.tenant_id == ManagementCompany.id)
                .where(HouseManagement.id == management_id)
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if row is None:
            return "management_not_active"
        management, tenant = row
        if (
            management.status != "active"
            or management.valid_from > now
            or (management.valid_to is not None and management.valid_to <= now)
        ):
            return "management_not_active"
        if tenant.status != "active":
            return "tenant_suspended"
        return None

    async def add(self, value: MAXChat | ConnectionRequest | ChatBinding) -> None:
        self.session.add(value)
        await self.session.flush()
