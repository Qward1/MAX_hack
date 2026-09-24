"""Житель = участник домового чата и открытый доступ к дому (срез D1).

Основание членства — **текущее участие** в чате с активной привязкой к дому
(RESIDENT-BY-CHAT-2026-09-25), а не авторство сообщений. Оно появляется из
события `user_added` или из точечной проверки
`GET /chats/{chatId}/members?user_ids=<id>` и действует 24 ч от проверки;
по истечении — повторная проверка при следующем обращении. `user_removed`
завершает членство, история остаётся. Отзыв, приостановка привязки и
`bot_removed` снимают доступ сразу — это проверяет политика доступа
(`AccessRepository.access_bases`), записи здесь не нужны.

Вызов MAX API идёт **вне транзакций БД**: короткая транзакция выбирает, какие
чаты проверить, и отмечает попытку; затем сеть; затем короткая транзакция
применяет ответ, заново проверяя, что привязка всё ещё та же. Не чаще одного
вызова на пару «пользователь, чат» за 15 минут. Ошибка MAX — прежний
результат действует до своего срока, нового доступа нет.

Кнопка или ссылка из чата только **сужают**, какой чат проверять: доступ
даёт ответ MAX, а не ссылка.

Открытый доступ (OPEN-HOUSE-ACCESS-2026-09-25) — переключатель дома: пока он
включён, любой вошедший через MAX выбирает дом и действует как житель
(`source = 'open_access'`). Выключение сразу прекращает такой доступ,
история и заявки остаются у УК.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.bot.chat_provider import MaxChatProvider, MaxProviderError
from domsignal.contracts.identity import OpenHouse
from domsignal.db.models import (
    ChatAuthorAlias,
    ChatBinding,
    ChatMemberCheck,
    House,
    HouseManagement,
    ManagementCompany,
    MAXChat,
    NotificationDelivery,
    ResidentMembership,
    User,
)
from domsignal.db.models.access import CHAT_MEMBER_SOURCE, OPEN_ACCESS_SOURCE
from domsignal.db.models.notifications import CHAT_PURPOSES
from domsignal.db.repositories.access import AccessRepository
from domsignal.db.repositories.chat_connections import ChatRepository
from domsignal.services.chat_connections import ChatConnectionService
from domsignal.services.errors import ResourceNotFound
from domsignal.services.sessions import MAX_USER_PLACEHOLDER

logger = logging.getLogger(__name__)


#: Сколько точечных проверок MAX идут одновременно.
CHECK_CONCURRENCY = 4

#: Непрозрачная ссылка на сообщение бота в чате (кнопка «Открыть ДомСигнал»).
CHAT_REF = re.compile(r"c_[A-Za-z0-9_-]{32}")

_MAX_ID = re.compile(r"[1-9]\d{0,18}")


@dataclass(frozen=True)
class RefreshSummary:
    """Итог проверки для журнала: только числа, без людей и чатов."""

    candidates: int = 0
    called: int = 0
    members: int = 0
    not_members: int = 0
    errors: int = 0


def _valid_max_id(value: str | None) -> bool:
    return bool(value) and bool(_MAX_ID.fullmatch(value or "")) and int(value or "0") < 2**63


async def ensure_max_user(
    session: AsyncSession, max_user_id: str, display_name: str | None
) -> User:
    """Пользователь по MAX id из подписанного вебхука.

    Личность не отмечается проверенной: `max_identity_verified_at` ставит
    только вход в mini app по подписанным `initData`.
    """
    repo = AccessRepository(session)
    await ChatRepository(session).lock(f"max-user:{max_user_id}")
    user = await repo.user_by_max_id(max_user_id)
    if user is None:
        name = (display_name or "").strip()[:200] or MAX_USER_PLACEHOLDER
        user = await repo.create_max_user(max_user_id, name)
    return user


class ResidentAccessService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        connections: ChatConnectionService,
        check_all_max_chats: int = 20,
        check_interval_seconds: int = 900,
        membership_ttl_seconds: int = 86400,
    ) -> None:
        self.sessions = session_factory
        # Провайдер MAX общий с подключением чатов: одна граница, одни права бота.
        self.connections = connections
        self.check_all_max_chats = check_all_max_chats
        self.check_interval = timedelta(seconds=check_interval_seconds)
        self.ttl = timedelta(seconds=membership_ttl_seconds)

    @property
    def provider(self) -> MaxChatProvider:
        return self.connections.provider

    # ------------------------------------------------------------ события

    async def user_added(
        self,
        session: AsyncSession,
        *,
        chat_id: str,
        max_user_id: str,
        display_name: str | None,
        occurred_at: datetime,
    ) -> ResidentMembership | None:
        """`user_added` в чате с активной привязкой → создать или продлить членство."""
        if not _valid_max_id(max_user_id):
            return None
        repo = ChatRepository(session)
        await repo.lock(f"chat:{chat_id}")
        binding = await repo.active_binding(chat_id)
        chat = await repo.chat(chat_id)
        if (
            binding is None
            or binding.activated_at is None
            or occurred_at < binding.activated_at
            or chat is None
            or not chat.bot_present
        ):
            return None
        user = await ensure_max_user(session, max_user_id, display_name)
        newer = await session.get(ChatMemberCheck, (user.id, chat_id), populate_existing=True)
        if newer is not None and newer.checked_at > occurred_at and newer.outcome == "not_member":
            return None  # Запоздавшее событие не перебивает более новый ответ.
        await self._record_check(session, user.id, chat_id, "member", occurred_at)
        return await self._grant(session, user.id, binding, checked_at=occurred_at)

    async def user_removed(
        self,
        session: AsyncSession,
        *,
        chat_id: str,
        max_user_id: str,
        occurred_at: datetime,
    ) -> int:
        """`user_removed` → завершить членство по этому чату; история остаётся."""
        if not _valid_max_id(max_user_id):
            return 0
        await ChatRepository(session).lock(f"chat:{chat_id}")
        user = await AccessRepository(session).user_by_max_id(max_user_id)
        if user is None:
            return 0
        await self._record_check(session, user.id, chat_id, "not_member", occurred_at)
        return await self._end_chat(
            session, user.id, chat_id, at=occurred_at, reason="user_removed"
        )

    # ---------------------------------------------------------- проверка

    async def refresh(
        self,
        user_id: UUID,
        *,
        launch_ref: str | None = None,
        chat_ids: Sequence[str] = (),
        now: datetime | None = None,
    ) -> RefreshSummary:
        """Проверить участие пользователя в чатах-кандидатах и обновить членство.

        Кандидаты: чат из кнопки или ссылки; чаты домов, где человек уже
        встречался (событие, псевдоним автора, прежнее членство); все активные
        привязки, если их не больше `RESIDENT_CHECK_ALL_MAX_CHATS`.
        """
        at = now or datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            user = await session.get(User, user_id)
            if user is None or not _valid_max_id(user.max_user_id):
                return RefreshSummary()
            max_user_id = str(user.max_user_id)
            hinted = list(chat_ids)
            if launch_ref:
                chat = await self._chat_of_ref(session, launch_ref)
                if chat is not None:
                    hinted.append(chat)
            candidates = await self._candidates(session, user_id, max_user_id, hinted)
            to_call: list[tuple[str, UUID, int]] = []
            cached: list[tuple[ChatBinding, datetime]] = []
            for binding in candidates:
                if await self._valid_membership(session, user_id, binding, at):
                    continue
                check = await session.get(
                    ChatMemberCheck, (user_id, binding.max_chat_id), populate_existing=True
                )
                if check is not None and check.checked_at > at - self.check_interval:
                    if check.outcome == "member":
                        cached.append((binding, check.checked_at))
                    continue
                # Попытка отмечается до сети: параллельный вход не повторит вызов.
                await self._record_check(session, user_id, binding.max_chat_id, "error", at)
                to_call.append((binding.max_chat_id, binding.id, binding.binding_version))
            for binding, checked_at in cached:
                await self._grant(session, user_id, binding, checked_at=checked_at)

        outcomes = await self._call(max_user_id, [chat for chat, _, _ in to_call])

        members = not_members = errors = 0
        async with self.sessions() as session, session.begin():
            for (chat_id, binding_id, version), outcome in zip(to_call, outcomes, strict=True):
                if outcome is None:
                    errors += 1
                    continue
                await ChatRepository(session).lock(f"chat:{chat_id}")
                await self._record_check(
                    session, user_id, chat_id, "member" if outcome else "not_member", at
                )
                if outcome:
                    members += 1
                    # Привязка могла смениться, пока шёл вызов: право даёт только та же.
                    fresh = await session.get(ChatBinding, binding_id, populate_existing=True)
                    if (
                        fresh is not None
                        and fresh.status == "active"
                        and fresh.binding_version == version
                    ):
                        await self._grant(session, user_id, fresh, checked_at=at)
                else:
                    not_members += 1
                    await self._end_chat(session, user_id, chat_id, at=at, reason="not_member")
        summary = RefreshSummary(
            candidates=len(candidates),
            called=len(to_call),
            members=members,
            not_members=not_members,
            errors=errors,
        )
        if to_call:
            logger.info(
                "resident_membership_checked",
                extra={
                    "candidates": summary.candidates,
                    "called": summary.called,
                    "members": summary.members,
                    "not_members": summary.not_members,
                    "errors": summary.errors,
                },
            )
        return summary

    async def _call(self, max_user_id: str, chats: list[str]) -> list[bool | None]:
        """Точечные вызовы MAX; `None` — ошибка (прежний результат остаётся)."""
        if not chats:
            return []
        limiter = asyncio.Semaphore(CHECK_CONCURRENCY)

        async def one(chat_id: str) -> bool | None:
            async with limiter:
                try:
                    return await self.provider.is_chat_member(chat_id, max_user_id)
                except MaxProviderError as exc:
                    logger.warning("resident_membership_check_failed", extra={"code": exc.code})
                    return None

        return list(await asyncio.gather(*(one(chat) for chat in chats)))

    async def _chat_of_ref(self, session: AsyncSession, ref: str) -> str | None:
        """Чат по ссылке `c_…` из кнопки сообщения бота. Чужая ссылка — `None`."""
        if not CHAT_REF.fullmatch(ref):
            return None
        row = (
            await session.execute(
                select(ChatBinding.max_chat_id)
                .join(NotificationDelivery, NotificationDelivery.chat_binding_id == ChatBinding.id)
                .where(
                    NotificationDelivery.launch_ref == ref,
                    NotificationDelivery.purpose.in_(CHAT_PURPOSES),
                )
            )
        ).first()
        return row[0] if row else None

    async def _candidates(
        self, session: AsyncSession, user_id: UUID, max_user_id: str, hinted: list[str]
    ) -> list[ChatBinding]:
        active = (
            select(ChatBinding)
            .join(MAXChat, MAXChat.max_chat_id == ChatBinding.max_chat_id)
            .where(
                ChatBinding.status == "active",
                ChatBinding.activated_at.is_not(None),
                MAXChat.bot_present.is_(True),
                MAXChat.binding_version == ChatBinding.binding_version,
            )
        )
        total = await session.scalar(select(func.count()).select_from(active.subquery())) or 0
        if total <= self.check_all_max_chats:
            rows = list(await session.scalars(active.order_by(ChatBinding.max_chat_id)))
        else:
            seen_houses = select(ChatAuthorAlias.house_id).where(
                ChatAuthorAlias.external_user_id == max_user_id
            )
            seen_chats = (
                select(ChatBinding.max_chat_id)
                .join(ResidentMembership, ResidentMembership.chat_binding_id == ChatBinding.id)
                .where(ResidentMembership.user_id == user_id)
            )
            rows = list(
                await session.scalars(
                    active.where(
                        or_(
                            ChatBinding.max_chat_id.in_(hinted),
                            ChatBinding.house_id.in_(seen_houses),
                            ChatBinding.max_chat_id.in_(seen_chats),
                        )
                    ).order_by(ChatBinding.max_chat_id)
                )
            )
        return rows

    async def _valid_membership(
        self, session: AsyncSession, user_id: UUID, binding: ChatBinding, at: datetime
    ) -> bool:
        row = await session.scalar(
            select(ResidentMembership.id).where(
                ResidentMembership.user_id == user_id,
                ResidentMembership.chat_binding_id == binding.id,
                ResidentMembership.binding_version == binding.binding_version,
                ResidentMembership.status == "active",
                ResidentMembership.expires_at > at,
            )
        )
        return row is not None

    async def _record_check(
        self, session: AsyncSession, user_id: UUID, chat_id: str, outcome: str, at: datetime
    ) -> None:
        statement = insert(ChatMemberCheck).values(
            user_id=user_id, max_chat_id=chat_id, checked_at=at, outcome=outcome
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[ChatMemberCheck.user_id, ChatMemberCheck.max_chat_id],
                set_={"checked_at": at, "outcome": outcome},
                # Запоздавшее событие не перезаписывает более новый ответ.
                where=ChatMemberCheck.checked_at <= statement.excluded.checked_at,
            )
        )

    async def _grant(
        self, session: AsyncSession, user_id: UUID, binding: ChatBinding, *, checked_at: datetime
    ) -> ResidentMembership:
        """Создать или продлить членство по привязке. Повтор — та же запись."""
        existing = await session.scalar(
            select(ResidentMembership)
            .where(
                ResidentMembership.user_id == user_id,
                ResidentMembership.chat_binding_id == binding.id,
                ResidentMembership.source == CHAT_MEMBER_SOURCE,
                ResidentMembership.status == "active",
            )
            .with_for_update()
        )
        if existing is not None:
            current = existing.checked_at or checked_at
            existing.checked_at = max(current, checked_at)
            existing.expires_at = existing.checked_at + self.ttl
            return existing
        membership = ResidentMembership(
            user_id=user_id,
            house_id=binding.house_id,
            source=CHAT_MEMBER_SOURCE,
            evidence_source="max_chat_member",
            verification_level="chat_member",
            chat_binding_id=binding.id,
            binding_version=binding.binding_version,
            checked_at=checked_at,
            expires_at=checked_at + self.ttl,
            status="active",
        )
        session.add(membership)
        await session.flush()
        return membership

    async def _end_chat(
        self, session: AsyncSession, user_id: UUID, chat_id: str, *, at: datetime, reason: str
    ) -> int:
        """Завершить действующее членство по всем привязкам этого чата.

        Членство, продлённое событием позже `at`, не трогаем: события MAX могут
        прийти не по порядку.
        """
        result = await session.execute(
            update(ResidentMembership)
            .where(
                ResidentMembership.user_id == user_id,
                ResidentMembership.source == CHAT_MEMBER_SOURCE,
                ResidentMembership.status == "active",
                ResidentMembership.checked_at <= at,
                ResidentMembership.chat_binding_id.in_(
                    select(ChatBinding.id).where(ChatBinding.max_chat_id == chat_id)
                ),
            )
            .values(status="revoked", ended_at=at, end_reason=reason)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    # ---------------------------------------------------- открытый доступ

    async def open_houses(self, session: AsyncSession, *, user_id: UUID) -> list[OpenHouse]:
        """Дома с открытым доступом и действующим управлением."""
        now = datetime.now(UTC)
        joined = select(ResidentMembership.house_id).where(
            ResidentMembership.user_id == user_id,
            ResidentMembership.source == OPEN_ACCESS_SOURCE,
            ResidentMembership.status == "active",
        )
        rows = (
            await session.execute(
                _open_house_query(now)
                .add_columns(House.id.in_(joined))
                .order_by(House.address)
                .limit(100)
            )
        ).all()
        return [
            OpenHouse(id=house.id, name=house.name, address=house.address, joined=bool(member))
            for house, member in rows
        ]

    async def has_open_houses(self, session: AsyncSession) -> bool:
        return (
            await session.scalar(
                _open_house_query(datetime.now(UTC)).limit(1).with_only_columns(House.id)
            )
        ) is not None

    async def join_open_house(
        self, session: AsyncSession, *, user_id: UUID, house_id: UUID
    ) -> ResidentMembership:
        """Выбрать открытый дом. Закрытый и несуществующий неотличимы (404)."""
        await AccessRepository(session).lock_house(house_id)
        house = await session.scalar(
            _open_house_query(datetime.now(UTC))
            .where(House.id == house_id)
            .execution_options(populate_existing=True)
        )
        if house is None:
            raise ResourceNotFound("Resource was not found")
        existing = await session.scalar(
            select(ResidentMembership).where(
                ResidentMembership.user_id == user_id,
                ResidentMembership.house_id == house_id,
                ResidentMembership.source == OPEN_ACCESS_SOURCE,
                ResidentMembership.status == "active",
            )
        )
        if existing is not None:
            return existing
        membership = ResidentMembership(
            user_id=user_id,
            house_id=house_id,
            source=OPEN_ACCESS_SOURCE,
            evidence_source="open_house_access",
            verification_level="self_selected",
            status="active",
        )
        session.add(membership)
        await session.flush()
        return membership

    @staticmethod
    async def set_open_access(
        session: AsyncSession, *, house: House, enabled: bool, actor_id: UUID | None
    ) -> int:
        """Переключить открытый доступ. Выключение сразу завершает `open_access`."""
        now = datetime.now(UTC)
        ended = 0
        if house.open_resident_access != enabled:
            house.open_resident_access = enabled
            house.open_access_changed_at = now
            house.open_access_changed_by = actor_id
        if not enabled:
            result = await session.execute(
                update(ResidentMembership)
                .where(
                    ResidentMembership.house_id == house.id,
                    ResidentMembership.source == OPEN_ACCESS_SOURCE,
                    ResidentMembership.status == "active",
                )
                .values(status="revoked", ended_at=now, end_reason="open_access_closed")
            )
            ended = int(getattr(result, "rowcount", 0) or 0)
        return ended


def _open_house_query(now: datetime) -> Select[tuple[House]]:
    return (
        select(House)
        .join(HouseManagement, HouseManagement.house_id == House.id)
        .join(ManagementCompany, ManagementCompany.id == HouseManagement.tenant_id)
        .where(
            House.open_resident_access.is_(True),
            ManagementCompany.status == "active",
            HouseManagement.status == "active",
            HouseManagement.valid_from <= now,
            or_(HouseManagement.valid_to.is_(None), HouseManagement.valid_to > now),
        )
    )


__all__ = [
    "CHAT_REF",
    "MAX_USER_PLACEHOLDER",
    "RefreshSummary",
    "ResidentAccessService",
    "ensure_max_user",
]
