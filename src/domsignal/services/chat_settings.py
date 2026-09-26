"""Настройки бота в домовом чате (BOT-VOICE-HUMAN-2026-09-27).

Что бот может публиковать по решению человека — статусы заявок, объявления и
рассылки УК, опросы, сообщения платформы — и тихие часы. Памятка
безопасности и сообщение о чтении чата этими настройками не отключаются.

Читать настройки может сотрудник с доступом к дому чата (`ticket.read`),
менять — тот, кто может подключать чаты этого дома (`chat.connect`, как у
выключателя чтения). Каждое изменение — событие аудита с автором.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.community import ChatSettingsChange, ChatSettingsUpdate, ChatSettingsView
from domsignal.core.display_time import display_zone, zone_label
from domsignal.core.quiet_hours import minutes_label, parse_minutes
from domsignal.db.models import ChatBinding, InboxReceipt, User
from domsignal.db.repositories.chat_connections import ChatRepository
from domsignal.services.chat_connections import ChatConnectionError, ChatConnectionService
from domsignal.services.errors import AccessDenied, ResourceNotFound
from domsignal.services.house_zone import HouseZones
from domsignal.services.membership import MembershipService
from domsignal.services.onboarding import audit

AUDIT_EVENT = "chat_settings.changed"

#: Виды сообщений по решению человека → настройка привязки.
KIND_SETTING = {
    "ticket_status": "post_ticket_status",
    "company_message": "post_company_messages",
    "company_poll": "post_polls",
    "platform_message": "post_platform_messages",
}

_FLAG_LABELS = {
    "post_ticket_status": "Статусы заявок",
    "post_company_messages": "Объявления и рассылки УК",
    "post_polls": "Опросы",
    "post_platform_messages": "Сообщения платформы",
}


def allows(binding: ChatBinding, kind: str) -> bool:
    """Разрешает ли чат сообщение этого вида. Неизвестный вид — нет."""
    setting = KIND_SETTING.get(kind)
    return bool(setting and getattr(binding, setting))


def broadcast_kind(origin: str, kind: str) -> str:
    """Вид сообщения рассылки для настроек чата."""
    if origin == "platform":
        return "platform_message"
    return "company_poll" if kind == "poll" else "company_message"


def _summary(before: dict[str, object], after: dict[str, object], zone: str) -> str:
    parts: list[str] = []
    for key, label in _FLAG_LABELS.items():
        if before[key] != after[key]:
            parts.append(f"{label}: {'разрешены' if after[key] else 'выключены'}")
    if (before["quiet_start"], before["quiet_end"]) != (after["quiet_start"], after["quiet_end"]):
        if after["quiet_start"] == after["quiet_end"]:
            parts.append("Тихие часы: выключены")
        else:
            parts.append(f"Тихие часы: {after['quiet_start']}–{after['quiet_end']} {zone}")
    return "; ".join(parts) or "Без изменений"


def _state(binding: ChatBinding) -> dict[str, object]:
    return {
        "post_ticket_status": binding.post_ticket_status,
        "post_company_messages": binding.post_company_messages,
        "post_polls": binding.post_polls,
        "post_platform_messages": binding.post_platform_messages,
        "quiet_start": minutes_label(binding.quiet_start_minute),
        "quiet_end": minutes_label(binding.quiet_end_minute),
    }


class ChatSettingsService:
    def __init__(
        self, connections: ChatConnectionService, zones: HouseZones | None = None
    ) -> None:
        self.connections = connections
        self.memberships = MembershipService()
        self.zones = zones or HouseZones(None)

    async def _zone_label(self, session: AsyncSession, binding: ChatBinding) -> str:
        zone = await self.zones.of_house(session, binding.house_id)
        return zone_label(zone, datetime.now(UTC).astimezone(display_zone(zone)))

    async def _readable(
        self, session: AsyncSession, binding_id: UUID, actor_id: UUID
    ) -> ChatBinding:
        binding = await ChatRepository(session).binding(binding_id)
        if binding is None:
            raise ResourceNotFound("Resource was not found")
        context = await self.memberships.require_house(
            session, user_id=actor_id, house_id=binding.house_id
        )
        if context.management_id.value != binding.management_id:
            raise ResourceNotFound("Resource was not found")
        self.memberships.require_permission(context, "ticket.read")
        return binding

    async def _can_edit(self, session: AsyncSession, binding: ChatBinding, actor_id: UUID) -> bool:
        try:
            context = await self.memberships.require_house(
                session, user_id=actor_id, house_id=binding.house_id
            )
        except (AccessDenied, ResourceNotFound):
            return False
        return "chat.connect" in context.permissions and binding.status == "active"

    async def view(
        self, session: AsyncSession, *, binding_id: UUID, actor_id: UUID
    ) -> ChatSettingsView:
        binding = await self._readable(session, binding_id, actor_id)
        return await self._view(
            session, binding, can_edit=await self._can_edit(session, binding, actor_id)
        )

    async def update(
        self,
        session: AsyncSession,
        *,
        binding_id: UUID,
        actor_id: UUID,
        payload: ChatSettingsUpdate,
    ) -> ChatSettingsView:
        """Сохранить настройки. Транзакция — у вызывающего."""
        repo = ChatRepository(session)
        binding = await repo.binding(binding_id)
        if binding is None:
            raise ResourceNotFound("Resource was not found")
        request = await self.connections.locked_request(session, binding.connection_request_id)
        await self.connections.require_authority(session, request, actor_id)
        binding = await repo.binding(binding_id)
        assert binding is not None
        if binding.status != "active":
            raise ChatConnectionError("binding_not_active")
        before = _state(binding)
        binding.post_ticket_status = payload.post_ticket_status
        binding.post_company_messages = payload.post_company_messages
        binding.post_polls = payload.post_polls
        binding.post_platform_messages = payload.post_platform_messages
        binding.quiet_start_minute = parse_minutes(payload.quiet_start)
        binding.quiet_end_minute = parse_minutes(payload.quiet_end)
        after = _state(binding)
        if before != after:
            binding.settings_changed_at = datetime.now(UTC)
            binding.settings_changed_by = actor_id
            label = await self._zone_label(session, binding)
            audit(session, AUDIT_EVENT, actor_id, binding.id, _summary(before, after, label))
        await session.flush()
        return await self._view(session, binding, can_edit=True)

    async def _view(
        self, session: AsyncSession, binding: ChatBinding, *, can_edit: bool
    ) -> ChatSettingsView:
        rows = list(
            await session.scalars(
                select(InboxReceipt)
                .where(
                    InboxReceipt.event_type == f"administration.{AUDIT_EVENT}",
                    InboxReceipt.payload["object_id"].astext == str(binding.id),
                )
                .order_by(InboxReceipt.accepted_at.desc())
                .limit(20)
            )
        )
        actors = {
            str(user.id): user.display_name
            for user in await session.scalars(
                select(User).where(
                    User.id.in_(
                        [
                            UUID(row.payload["actor_id"])
                            for row in rows
                            if row.payload.get("actor_id")
                        ]
                    )
                )
            )
        }
        return ChatSettingsView(
            binding_id=binding.id,
            post_ticket_status=binding.post_ticket_status,
            post_company_messages=binding.post_company_messages,
            post_polls=binding.post_polls,
            post_platform_messages=binding.post_platform_messages,
            quiet_start=minutes_label(binding.quiet_start_minute),
            quiet_end=minutes_label(binding.quiet_end_minute),
            changed_at=binding.settings_changed_at,
            can_edit=can_edit,
            timezone_label=await self._zone_label(session, binding),
            history=[
                ChatSettingsChange(
                    occurred_at=row.accepted_at,
                    actor_name=actors.get(str(row.payload.get("actor_id"))),
                    summary=str(row.payload.get("reason") or ""),
                )
                for row in rows
            ],
        )


__all__ = ["ChatSettingsService", "allows", "broadcast_kind"]
