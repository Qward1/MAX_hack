"""Сообщения от УК и платформы: объявления, рассылки и опросы — один механизм.

Поток: черновик → предпросмотр с числом получателей по каналам →
подтверждение («только сервисные сообщения, реклама запрещена») → отправка
сразу или по расписанию; отмена — до отправки. Отправка — задача
`broadcast.send`: под блокировкой строки сообщения она заново разрешает
аудиторию по действующим полномочиям подтвердившего и создаёт доставки в
существующем механизме (`NotificationDelivery`), поэтому повтор задачи и
гонка с отменой ничего не дублируют (BOT-VOICE-HUMAN-2026-09-27).

Кто и кому. Сотрудник УК с правом `broadcast.send` (администратор УК —
все дома, ответственный — свои) пишет только в дома своей УК: всем, выбранным
или по фильтру (город/регион, дома с подключённым чатом, дома с открытым
доступом). Каналы УК: пост бота в домовой чат, личные сообщения жителям
(только начавшим диалог с ботом, отписка уважается) и лента «Объявления».
Суперадмин пишет всем УК, выбранным или по региону — в кабинеты и в личку
сотрудников — и в домовые чаты, где настройка чата разрешает сообщения
платформы (по умолчанию выключено).

Правка отправленного — правка того же поста в чате; удаление — правка поста
на пометку «Сообщение удалено автором». Тихие часы чата переносят отправку.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.contracts.common import PageMeta
from domsignal.contracts.community import (
    AnnouncementItem,
    AnnouncementList,
    BroadcastAudience,
    BroadcastCommand,
    BroadcastConfirm,
    BroadcastContentEdit,
    BroadcastCreate,
    BroadcastHouseOption,
    BroadcastList,
    BroadcastPreview,
    BroadcastSummary,
    BroadcastUpdate,
    BroadcastView,
    ChannelPreview,
    ChannelStats,
    PlatformNotice,
    PlatformNoticeList,
    PollOptionResult,
    PollResults,
    PollSummary,
    PollView,
    PollVote,
    ResidentPreferences,
)
from domsignal.core.quiet_hours import (
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    MSK,
    quiet_until,
)
from domsignal.db.models import (
    Broadcast,
    BroadcastCompany,
    BroadcastHouse,
    ChatBinding,
    House,
    HouseManagement,
    HouseRoutingProfile,
    ManagementCompany,
    MAXChat,
    NotificationDelivery,
    OrganizationMembership,
    OutboxMessage,
    Poll,
    PollBallot,
    PollChoice,
    PollOption,
    User,
)
from domsignal.db.models.notifications import (
    BROADCAST_CHAT_PURPOSE,
    BROADCAST_DM_PURPOSE,
    BROADCAST_STAFF_PURPOSE,
)
from domsignal.db.repositories.access import AccessRepository
from domsignal.db.repositories.reliability import ReliabilityRepository, stable_hash
from domsignal.services.chat_settings import allows, broadcast_kind
from domsignal.services.community_texts import (
    POLL_DISCLAIMER,
    TOPIC_LABELS,
    sender_label,
)
from domsignal.services.errors import (
    AccessDenied,
    FieldValidationError,
    IdempotencyConflict,
    RescheduleJob,
    ResourceNotFound,
    ServiceError,
)
from domsignal.services.membership import MembershipService
from domsignal.services.onboarding import (
    audit,
    current_management,
    require_company,
    require_platform,
)

logger = logging.getLogger(__name__)

#: Задачи: отправка по расписанию и закрытие опроса в срок.
SEND_JOB = "broadcast.send"
POLL_CLOSE_JOB = "poll.close"
#: Запись outbox, к которой привязаны доставки одного сообщения.
FANOUT_OUTBOX_KIND = "broadcast.fanout.v1"
#: Префиксы `launch_ref`: пост в чат, личное жителю, личное сотруднику.
CHAT_POST_REF_PREFIX = "p_"
RESIDENT_DM_REF_PREFIX = "n_"
STAFF_DM_REF_PREFIX = "a_"
#: Итоги опроса правятся в том же сообщении не чаще раза в 5 минут.
POLL_EDIT_INTERVAL = timedelta(minutes=5)
#: Отложенная отправка — не дальше 30 дней.
MAX_SCHEDULE_AHEAD = timedelta(days=30)
#: Опрос открыт хотя бы 10 минут после отправки.
MIN_POLL_OPEN = timedelta(minutes=10)

SEND_PERMISSION = "broadcast.send"
COMPANY_CHANNELS = frozenset({"chat", "dm", "feed"})
PLATFORM_CHANNELS = frozenset({"chat", "staff"})

# Причины пропуска доставки (статистика и предпросмотр).
SKIP_CHAT_SETTING = "CHAT_SETTING_OFF"
SKIP_UNSUBSCRIBED = "UNSUBSCRIBED"
SKIP_NO_DIALOG = "NO_DIALOG"
QUIET_HOURS_CODE = "QUIET_HOURS"


class BroadcastConflict(ServiceError):
    status = 409
    code = "broadcast_conflict"
    title = "Сообщение изменилось"


class PollClosed(ServiceError):
    status = 409
    code = "poll_closed"
    title = "Опрос закрыт"


@dataclass(frozen=True)
class Scope:
    """Где автор вправе писать: дома УК или платформа."""

    origin: str
    company_id: UUID | None
    house_ids: frozenset[UUID] = frozenset()
    admin: bool = False


@dataclass
class Plan:
    """Разрешённая аудитория и цели по каналам."""

    houses: list[House] = field(default_factory=list)
    companies: list[ManagementCompany] = field(default_factory=list)
    chats: list[tuple[ChatBinding, str | None]] = field(default_factory=list)
    residents: list[tuple[User, str | None]] = field(default_factory=list)
    staff: list[tuple[User, str | None]] = field(default_factory=list)


def _ref(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(24)


def dialog_ready(user: User) -> bool:
    """Бот может написать: человек начал диалог или вошёл через MAX (D1)."""
    return bool(user.max_user_id) and (
        user.dialog_open or user.max_identity_verified_at is not None
    )


class BroadcastService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        public_base_url: str | None = None,
    ) -> None:
        self.sessions = session_factory
        self.public_base_url = public_base_url
        self.memberships = MembershipService()

    # ================================================================ полномочия

    async def company_scope(
        self, session: AsyncSession, *, actor_id: UUID, company_id: UUID
    ) -> Scope:
        membership = await require_company(session, actor_id, company_id, admin=False)
        houses = frozenset(
            house.id
            for house, context in await self.memberships.contexts_with(
                session, user_id=actor_id, permission=SEND_PERMISSION
            )
            if context.tenant_id.value == company_id
        )
        if not houses and membership.role != "company_admin":
            raise AccessDenied("Сообщения жителям отправляют администратор УК и ответственный")
        return Scope(
            origin="company",
            company_id=company_id,
            house_ids=houses,
            admin=membership.role == "company_admin",
        )

    async def _scope_for(
        self, session: AsyncSession, broadcast: Broadcast, actor_id: UUID
    ) -> Scope:
        if broadcast.origin == "platform":
            await require_platform(session, actor_id)
            return Scope(origin="platform", company_id=None)
        assert broadcast.tenant_id is not None
        try:
            return await self.company_scope(
                session, actor_id=actor_id, company_id=broadcast.tenant_id
            )
        except AccessDenied:
            raise ResourceNotFound("Ресурс не найден") from None

    async def _load(
        self, session: AsyncSession, broadcast_id: UUID, actor_id: UUID, *, lock: bool = False
    ) -> tuple[Broadcast, Scope]:
        broadcast = await session.get(
            Broadcast, broadcast_id, with_for_update=lock, populate_existing=True
        )
        if broadcast is None:
            raise ResourceNotFound("Ресурс не найден")
        scope = await self._scope_for(session, broadcast, actor_id)
        return broadcast, scope

    # ============================================================== аудитория

    async def _managed_houses(
        self, session: AsyncSession, tenant_ids: list[UUID]
    ) -> list[tuple[House, UUID, UUID]]:
        """Дома под текущим управлением УК: (дом, управление, УК)."""
        if not tenant_ids:
            return []
        rows = await session.execute(
            select(House, HouseManagement.id, HouseManagement.tenant_id)
            .join(HouseManagement, HouseManagement.house_id == House.id)
            .join(ManagementCompany, ManagementCompany.id == HouseManagement.tenant_id)
            .where(
                HouseManagement.tenant_id.in_(tenant_ids),
                ManagementCompany.status == "active",
                *current_management(),
            )
            .order_by(House.address, House.id)
        )
        return [(row[0], row[1], row[2]) for row in rows]

    async def _profiles(
        self, session: AsyncSession, house_ids: list[UUID]
    ) -> dict[UUID, HouseRoutingProfile]:
        if not house_ids:
            return {}
        return {
            profile.house_id: profile
            for profile in await session.scalars(
                select(HouseRoutingProfile).where(HouseRoutingProfile.house_id.in_(house_ids))
            )
        }

    async def _active_bindings(
        self, session: AsyncSession, managements: dict[UUID, UUID]
    ) -> dict[UUID, list[ChatBinding]]:
        """Активные привязки дома при текущем управлении, бот в чате."""
        if not managements:
            return {}
        rows = await session.scalars(
            select(ChatBinding)
            .join(MAXChat, MAXChat.max_chat_id == ChatBinding.max_chat_id)
            .where(
                ChatBinding.house_id.in_(list(managements)),
                ChatBinding.status == "active",
                MAXChat.bot_present.is_(True),
            )
            .order_by(ChatBinding.house_id, ChatBinding.id)
        )
        result: dict[UUID, list[ChatBinding]] = {}
        for binding in rows:
            if managements.get(binding.house_id) == binding.management_id:
                result.setdefault(binding.house_id, []).append(binding)
        return result

    async def _select_houses(
        self,
        session: AsyncSession,
        audience: BroadcastAudience,
        candidates: list[tuple[House, UUID, UUID]],
        *,
        strict: bool,
    ) -> list[tuple[House, UUID, UUID]]:
        """Дома аудитории среди доступных. `strict` — чужой дом даёт 422."""
        if audience.mode == "houses":
            known = {house.id for house, _, _ in candidates}
            foreign = [house_id for house_id in audience.house_ids if house_id not in known]
            if strict and foreign:
                raise FieldValidationError(
                    "В аудитории есть дома вне вашей управляющей компании или ваших назначений",
                    field="audience",
                )
            wanted = set(audience.house_ids)
            return [row for row in candidates if row[0].id in wanted]
        if audience.mode in {"filter", "region"} or (
            audience.region_code or audience.municipality_code
        ):
            profiles = await self._profiles(session, [house.id for house, _, _ in candidates])
            selected = []
            for row in candidates:
                profile = profiles.get(row[0].id)
                if audience.region_code and (
                    profile is None or profile.region_code != audience.region_code
                ):
                    continue
                if audience.municipality_code and (
                    profile is None or profile.municipality_code != audience.municipality_code
                ):
                    continue
                selected.append(row)
            candidates = selected
        if audience.mode == "filter":
            if audience.only_open_access:
                candidates = [row for row in candidates if row[0].open_resident_access]
            if audience.only_with_chat:
                bindings = await self._active_bindings(
                    session, {house.id: management for house, management, _ in candidates}
                )
                candidates = [row for row in candidates if bindings.get(row[0].id)]
        return candidates

    async def _platform_companies(
        self, session: AsyncSession, audience: BroadcastAudience, *, strict: bool
    ) -> list[ManagementCompany]:
        companies = list(
            await session.scalars(
                select(ManagementCompany)
                .where(ManagementCompany.status == "active")
                .order_by(ManagementCompany.name)
            )
        )
        if audience.mode == "companies":
            known = {company.id for company in companies}
            if strict and any(item not in known for item in audience.company_ids):
                raise FieldValidationError(
                    "В аудитории есть неизвестные или неактивные УК", field="audience"
                )
            wanted = set(audience.company_ids)
            return [company for company in companies if company.id in wanted]
        if audience.mode == "region":
            if not audience.region_code:
                raise FieldValidationError("Укажите регион", field="audience")
            houses = await self._managed_houses(session, [company.id for company in companies])
            profiles = await self._profiles(session, [house.id for house, _, _ in houses])
            tenants = {
                tenant
                for house, _, tenant in houses
                if (profile := profiles.get(house.id)) is not None
                and profile.region_code == audience.region_code
            }
            return [company for company in companies if company.id in tenants]
        return companies

    async def plan(
        self, session: AsyncSession, broadcast: Broadcast, scope: Scope, *, strict: bool
    ) -> Plan:
        """Аудитория и цели по каналам на текущий момент."""
        audience = BroadcastAudience.model_validate(broadcast.audience)
        channels = set(broadcast.channels)
        plan = Plan()
        if broadcast.origin == "company":
            assert broadcast.tenant_id is not None
            candidates = await self._managed_houses(session, [broadcast.tenant_id])
            if not scope.admin:
                candidates = [row for row in candidates if row[0].id in scope.house_ids]
            rows = await self._select_houses(session, audience, candidates, strict=strict)
        else:
            plan.companies = await self._platform_companies(session, audience, strict=strict)
            rows = await self._managed_houses(session, [company.id for company in plan.companies])
            if audience.region_code or audience.municipality_code:
                rows = await self._select_houses(
                    session,
                    BroadcastAudience(
                        mode="region",
                        region_code=audience.region_code,
                        municipality_code=audience.municipality_code,
                    ),
                    rows,
                    strict=False,
                )
        plan.houses = [house for house, _, _ in rows]
        managements = {house.id: management for house, management, _ in rows}
        if "chat" in channels:
            bindings = await self._active_bindings(session, managements)
            kind = broadcast_kind(broadcast.origin, broadcast.kind)
            for house in plan.houses:
                for binding in bindings.get(house.id, []):
                    plan.chats.append(
                        (binding, None if allows(binding, kind) else SKIP_CHAT_SETTING)
                    )
        if "dm" in channels and broadcast.origin == "company":
            pairs = await AccessRepository(session).resident_ids(
                list(managements), now=datetime.now(UTC)
            )
            user_ids = list(dict.fromkeys(user_id for user_id, _ in pairs))
            users = {
                user.id: user
                for user in await session.scalars(select(User).where(User.id.in_(user_ids)))
            }
            for user_id in user_ids:
                user = users[user_id]
                reason = (
                    SKIP_UNSUBSCRIBED
                    if user.broadcast_opt_out_at is not None
                    else None
                    if dialog_ready(user)
                    else SKIP_NO_DIALOG
                )
                plan.residents.append((user, reason))
        if "staff" in channels and broadcast.origin == "platform":
            tenant_ids = [company.id for company in plan.companies]
            staff = (
                list(
                    await session.scalars(
                        select(User)
                        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
                        .where(
                            OrganizationMembership.tenant_id.in_(tenant_ids),
                            OrganizationMembership.status == "active",
                        )
                        .distinct()
                        .order_by(User.id)
                    )
                )
                if tenant_ids
                else []
            )
            for user in staff:
                plan.staff.append((user, None if dialog_ready(user) else SKIP_NO_DIALOG))
        return plan

    # ============================================================= кабинет: чтение

    async def house_options(
        self, session: AsyncSession, *, actor_id: UUID, company_id: UUID
    ) -> list[BroadcastHouseOption]:
        scope = await self.company_scope(session, actor_id=actor_id, company_id=company_id)
        rows = await self._managed_houses(session, [company_id])
        if not scope.admin:
            rows = [row for row in rows if row[0].id in scope.house_ids]
        profiles = await self._profiles(session, [house.id for house, _, _ in rows])
        bindings = await self._active_bindings(
            session, {house.id: management for house, management, _ in rows}
        )
        return [
            BroadcastHouseOption(
                house_id=house.id,
                address=house.address,
                region_code=profiles[house.id].region_code if house.id in profiles else None,
                municipality_code=profiles[house.id].municipality_code
                if house.id in profiles
                else None,
                has_chat=bool(bindings.get(house.id)),
                open_access=house.open_resident_access,
            )
            for house, _, _ in rows
        ]

    async def list_company(
        self, session: AsyncSession, *, actor_id: UUID, company_id: UUID, limit: int, offset: int
    ) -> BroadcastList:
        await self.company_scope(session, actor_id=actor_id, company_id=company_id)
        return await self._list(
            session, Broadcast.tenant_id == company_id, limit=limit, offset=offset
        )

    async def list_platform(
        self, session: AsyncSession, *, actor_id: UUID, limit: int, offset: int
    ) -> BroadcastList:
        await require_platform(session, actor_id)
        return await self._list(session, Broadcast.origin == "platform", limit=limit, offset=offset)

    async def _list(
        self, session: AsyncSession, condition: Any, *, limit: int, offset: int
    ) -> BroadcastList:
        total = await session.scalar(select(func.count()).select_from(Broadcast).where(condition))
        rows = list(
            await session.scalars(
                select(Broadcast)
                .where(condition)
                .order_by(Broadcast.created_at.desc(), Broadcast.id)
                .limit(limit)
                .offset(offset)
            )
        )
        names = await self._names(session, [row.author_id for row in rows])
        return BroadcastList(
            items=[
                BroadcastSummary(
                    id=row.id,
                    kind=row.kind,
                    title=row.title,
                    status=row.status,
                    created_at=row.created_at,
                    scheduled_at=row.scheduled_at,
                    sent_at=row.sent_at,
                    retracted_at=row.retracted_at,
                    author_name=names.get(row.author_id),
                )
                for row in rows
            ],
            page=PageMeta(limit=limit, offset=offset, total=total or 0),
        )

    async def detail(
        self, session: AsyncSession, *, actor_id: UUID, broadcast_id: UUID
    ) -> BroadcastView:
        broadcast, scope = await self._load(session, broadcast_id, actor_id)
        return await self.view(session, broadcast, scope)

    async def preview(
        self, session: AsyncSession, *, actor_id: UUID, broadcast_id: UUID
    ) -> BroadcastPreview:
        broadcast, scope = await self._load(session, broadcast_id, actor_id)
        plan = await self.plan(session, broadcast, scope, strict=True)
        return self._preview(broadcast, plan)

    @staticmethod
    def _preview(broadcast: Broadcast, plan: Plan) -> BroadcastPreview:
        channels: list[ChannelPreview] = []

        def count(targets: list[tuple[Any, str | None]], channel: str) -> None:
            skipped: dict[str, int] = {}
            for _, reason in targets:
                if reason:
                    skipped[reason] = skipped.get(reason, 0) + 1
            channels.append(
                ChannelPreview(
                    channel=channel,
                    targets=len(targets),
                    will_send=len(targets) - sum(skipped.values()),
                    skipped=skipped,
                )
            )

        for channel in broadcast.channels:
            if channel == "chat":
                count(plan.chats, "chat")
            elif channel == "dm":
                count(plan.residents, "dm")
            elif channel == "staff":
                count(plan.staff, "staff")
            elif channel == "feed":
                channels.append(
                    ChannelPreview(
                        channel="feed", targets=len(plan.houses), will_send=len(plan.houses)
                    )
                )
        return BroadcastPreview(
            houses=len(plan.houses), companies=len(plan.companies), channels=channels
        )

    async def _names(self, session: AsyncSession, ids: list[UUID | None]) -> dict[UUID, str]:
        wanted = [item for item in dict.fromkeys(ids) if item is not None]
        if not wanted:
            return {}
        return {
            user.id: user.display_name
            for user in await session.scalars(select(User).where(User.id.in_(wanted)))
        }

    async def sender(self, session: AsyncSession, broadcast: Broadcast) -> str:
        name = None
        if broadcast.tenant_id is not None:
            company = await session.get(ManagementCompany, broadcast.tenant_id)
            name = company.name if company else None
        return sender_label(broadcast.origin, name)

    async def view(
        self, session: AsyncSession, broadcast: Broadcast, scope: Scope
    ) -> BroadcastView:
        names = await self._names(session, [broadcast.author_id, broadcast.confirmed_by])
        poll = await session.scalar(select(Poll).where(Poll.broadcast_id == broadcast.id))
        houses = list(
            await session.scalars(
                select(House.address)
                .join(BroadcastHouse, BroadcastHouse.house_id == House.id)
                .where(BroadcastHouse.broadcast_id == broadcast.id)
                .order_by(House.address)
                .limit(50)
            )
        )
        actions: list[str] = []
        if broadcast.status == "draft":
            actions = ["edit", "preview", "confirm", "cancel"]
        elif broadcast.status == "scheduled":
            actions = ["cancel"]
        elif broadcast.status == "sent" and broadcast.retracted_at is None:
            actions = ["retract"]
            if broadcast.kind != "poll":
                actions.insert(0, "edit_content")
            elif poll is not None and poll.closed_at is None:
                actions.insert(0, "close_poll")
        return BroadcastView(
            id=broadcast.id,
            origin=broadcast.origin,
            company_id=broadcast.tenant_id,
            kind=broadcast.kind,
            topic=broadcast.topic,
            title=broadcast.title,
            body=broadcast.body,
            audience=BroadcastAudience.model_validate(broadcast.audience),
            channels=list(broadcast.channels),
            status=broadcast.status,
            scheduled_at=broadcast.scheduled_at,
            confirmed_at=broadcast.confirmed_at,
            sent_at=broadcast.sent_at,
            cancelled_at=broadcast.cancelled_at,
            retracted_at=broadcast.retracted_at,
            edited_at=broadcast.edited_at,
            created_at=broadcast.created_at,
            version=broadcast.version,
            author_name=names.get(broadcast.author_id),
            confirmed_by_name=names.get(broadcast.confirmed_by) if broadcast.confirmed_by else None,
            sender=await self.sender(session, broadcast),
            poll=await self.poll_results(session, poll) if poll is not None else None,
            houses=houses,
            stats=await self.stats(session, broadcast) if broadcast.status == "sent" else [],
            allowed_actions=actions,
        )

    async def stats(self, session: AsyncSession, broadcast: Broadcast) -> list[ChannelStats]:
        """accepted / failed / unknown / ожидают / перенесены тихими часами / пропущены."""
        channel_of = {
            BROADCAST_CHAT_PURPOSE: "chat",
            BROADCAST_DM_PURPOSE: "dm",
            BROADCAST_STAFF_PURPOSE: "staff",
        }
        result: dict[str, ChannelStats] = {}
        for channel in broadcast.channels:
            result[channel] = ChannelStats(channel=channel)
        rows = await session.execute(
            select(
                NotificationDelivery.purpose,
                NotificationDelivery.status,
                NotificationDelivery.last_error_code,
                func.count(),
            )
            .where(NotificationDelivery.broadcast_id == broadcast.id)
            .group_by(
                NotificationDelivery.purpose,
                NotificationDelivery.status,
                NotificationDelivery.last_error_code,
            )
        )
        for purpose, status, code, count in rows:
            target = channel_of.get(purpose)
            if target is None or target not in result:
                continue
            stats = result[target]
            stats.total += count
            if status == "accepted":
                stats.accepted += count
            elif status == "failed":
                stats.failed += count
            elif status == "unknown":
                stats.unknown += count
            elif status in {"skipped", "superseded"}:
                reason = code or "SKIPPED"
                stats.skipped[reason] = stats.skipped.get(reason, 0) + count
            elif code == QUIET_HOURS_CODE:
                stats.deferred_quiet_hours += count
            else:
                stats.pending += count
        if "feed" in result:
            houses = await session.scalar(
                select(func.count())
                .select_from(BroadcastHouse)
                .where(BroadcastHouse.broadcast_id == broadcast.id)
            )
            result["feed"].total = houses or 0
            result["feed"].accepted = houses or 0
        return list(result.values())

    # ============================================================ кабинет: команды

    def _validate(self, payload: BroadcastCreate, origin: str) -> None:
        allowed = COMPANY_CHANNELS if origin == "company" else PLATFORM_CHANNELS
        if any(channel not in allowed for channel in payload.channels):
            raise FieldValidationError("Этот канал недоступен для сообщения", field="channels")
        if origin == "platform" and payload.kind == "poll":
            raise FieldValidationError("Опросы проводят управляющие компании", field="kind")
        modes = (
            {"all", "houses", "filter"} if origin == "company" else {"all", "companies", "region"}
        )
        if payload.audience.mode not in modes:
            raise FieldValidationError("Такой выбор аудитории недоступен", field="audience")
        if payload.poll is not None and payload.poll.closes_at <= datetime.now(UTC) + MIN_POLL_OPEN:
            raise FieldValidationError("Опрос должен быть открыт хотя бы 10 минут", field="poll")

    async def create(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        company_id: UUID | None,
        payload: BroadcastCreate,
        idempotency_key: str,
    ) -> BroadcastView:
        """Черновик. `company_id` пуст — сообщение платформы. Транзакция — у вызывающего."""
        origin = "company" if company_id is not None else "platform"
        if company_id is not None:
            scope = await self.company_scope(session, actor_id=actor_id, company_id=company_id)
        else:
            await require_platform(session, actor_id)
            scope = Scope(origin="platform", company_id=None)
        self._validate(payload, origin)
        reliability = ReliabilityRepository(session)
        action = f"broadcast.create:{company_id or 'platform'}"
        digest = stable_hash(payload.model_dump(mode="json"))
        await reliability.lock_idempotency(actor_id=actor_id, action=action, key=idempotency_key)
        receipt = await reliability.idempotency_record(
            actor_id=actor_id, action=action, key=idempotency_key
        )
        if receipt is not None:
            if receipt.request_hash != digest:
                raise IdempotencyConflict("Idempotency-Key was already used with a different body")
            existing = await session.get(Broadcast, UUID(receipt.response_body["id"]))
            assert existing is not None
            return await self.view(session, existing, scope)
        broadcast = Broadcast(
            id=uuid4(),
            origin=origin,
            tenant_id=company_id,
            kind=payload.kind,
            topic=payload.topic if payload.kind == "announcement" else None,
            title=payload.title.strip(),
            body=payload.body.strip(),
            audience=payload.audience.model_dump(mode="json"),
            channels=list(payload.channels),
            status="draft",
            author_id=actor_id,
            version=1,
            content_version=1,
        )
        session.add(broadcast)
        await session.flush()
        await self._replace_poll(session, broadcast, payload)
        # Аудитория проверяется сразу: чужой дом — 422, а не тихое сужение.
        await self.plan(session, broadcast, scope, strict=True)
        reliability.add_idempotency(
            actor_id=actor_id,
            action=action,
            key=idempotency_key,
            request_hash=digest,
            response_status=201,
            response_body={"id": str(broadcast.id)},
        )
        audit(session, "broadcast.created", actor_id, broadcast.id)
        await session.flush()
        return await self.view(session, broadcast, scope)

    async def _replace_poll(
        self, session: AsyncSession, broadcast: Broadcast, payload: BroadcastCreate
    ) -> None:
        existing = await session.scalar(select(Poll).where(Poll.broadcast_id == broadcast.id))
        if existing is not None:
            await session.delete(existing)
            await session.flush()
        if payload.poll is None:
            return
        poll = Poll(
            id=uuid4(),
            broadcast_id=broadcast.id,
            question=payload.poll.question.strip(),
            multiple=payload.poll.multiple,
            closes_at=payload.poll.closes_at,
        )
        session.add(poll)
        await session.flush()
        for position, label in enumerate(payload.poll.options, start=1):
            session.add(PollOption(poll_id=poll.id, position=position, label=label))
        await session.flush()

    def _expect(self, broadcast: Broadcast, version: int, *statuses: str) -> None:
        if broadcast.version != version:
            raise BroadcastConflict("Сообщение изменилось. Обновите страницу и повторите.")
        if broadcast.status not in statuses:
            raise BroadcastConflict("Это действие недоступно в текущем состоянии сообщения.")

    async def update_draft(
        self, session: AsyncSession, *, actor_id: UUID, broadcast_id: UUID, payload: BroadcastUpdate
    ) -> BroadcastView:
        broadcast, scope = await self._load(session, broadcast_id, actor_id, lock=True)
        self._expect(broadcast, payload.expected_version, "draft")
        self._validate(payload, broadcast.origin)
        broadcast.kind = payload.kind
        broadcast.topic = payload.topic if payload.kind == "announcement" else None
        broadcast.title = payload.title.strip()
        broadcast.body = payload.body.strip()
        broadcast.audience = payload.audience.model_dump(mode="json")
        broadcast.channels = list(payload.channels)
        broadcast.version += 1
        await self._replace_poll(session, broadcast, payload)
        await self.plan(session, broadcast, scope, strict=True)
        await session.flush()
        return await self.view(session, broadcast, scope)

    async def confirm(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        broadcast_id: UUID,
        payload: BroadcastConfirm,
    ) -> BroadcastView:
        """Подтверждение: сразу или по расписанию. Отправляет задача `broadcast.send`."""
        broadcast, scope = await self._load(session, broadcast_id, actor_id, lock=True)
        self._expect(broadcast, payload.expected_version, "draft")
        now = datetime.now(UTC)
        send_at = payload.send_at or now
        if send_at < now - timedelta(minutes=1):
            raise FieldValidationError("Время отправки уже прошло", field="send_at")
        if send_at > now + MAX_SCHEDULE_AHEAD:
            raise FieldValidationError(
                "Отложить отправку можно не дальше чем на 30 дней", field="send_at"
            )
        poll = await session.scalar(select(Poll).where(Poll.broadcast_id == broadcast.id))
        if poll is not None and poll.closes_at <= max(send_at, now) + MIN_POLL_OPEN:
            raise FieldValidationError(
                "Опрос должен закрыться не раньше чем через 10 минут после отправки",
                field="poll",
            )
        plan = await self.plan(session, broadcast, scope, strict=True)
        if not plan.houses and not plan.companies:
            raise FieldValidationError("В аудитории нет ни одного дома", field="audience")
        broadcast.status = "scheduled"
        broadcast.scheduled_at = max(send_at, now)
        broadcast.confirmed_at = now
        broadcast.confirmed_by = actor_id
        broadcast.version += 1
        delay = max(0, int((broadcast.scheduled_at - now).total_seconds()))
        await ReliabilityRepository(session).add_job(
            kind=SEND_JOB,
            payload={"broadcast_id": str(broadcast.id)},
            priority=40,
            delay_seconds=delay,
            now=now,
        )
        audit(
            session,
            "broadcast.confirmed" if delay == 0 else "broadcast.scheduled",
            actor_id,
            broadcast.id,
        )
        await session.flush()
        return await self.view(session, broadcast, scope)

    async def cancel(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        broadcast_id: UUID,
        payload: BroadcastCommand,
    ) -> BroadcastView:
        """Отмена до отправки: черновик или запланированное сообщение."""
        broadcast, scope = await self._load(session, broadcast_id, actor_id, lock=True)
        if broadcast.status == "sent":
            raise BroadcastConflict(
                "Сообщение уже отправлено — отменить нельзя. Его можно удалить."
            )
        self._expect(broadcast, payload.expected_version, "draft", "scheduled")
        broadcast.status = "cancelled"
        broadcast.cancelled_at = datetime.now(UTC)
        broadcast.cancelled_by = actor_id
        broadcast.version += 1
        audit(session, "broadcast.cancelled", actor_id, broadcast.id)
        await session.flush()
        return await self.view(session, broadcast, scope)

    async def edit_content(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        broadcast_id: UUID,
        payload: BroadcastContentEdit,
    ) -> BroadcastView:
        """Правка отправленного: тот же пост в чате правится, заново не отправляется."""
        broadcast, scope = await self._load(session, broadcast_id, actor_id, lock=True)
        self._expect(broadcast, payload.expected_version, "sent")
        if broadcast.retracted_at is not None or broadcast.kind == "poll":
            raise BroadcastConflict("Это сообщение нельзя изменить.")
        if broadcast.kind != "poll" and not payload.body.strip():
            raise FieldValidationError("Текст сообщения обязателен", field="body")
        broadcast.title = payload.title.strip()
        broadcast.body = payload.body.strip()
        broadcast.edited_at = datetime.now(UTC)
        broadcast.version += 1
        broadcast.content_version += 1
        await self._reconcile_chat(session, broadcast, immediate=True)
        audit(session, "broadcast.edited", actor_id, broadcast.id)
        await session.flush()
        return await self.view(session, broadcast, scope)

    async def retract(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        broadcast_id: UUID,
        payload: BroadcastCommand,
    ) -> BroadcastView:
        """Удаление отправленного: пост в чате правится на пометку, неотправленное не уходит."""
        broadcast, scope = await self._load(session, broadcast_id, actor_id, lock=True)
        self._expect(broadcast, payload.expected_version, "sent")
        if broadcast.retracted_at is not None:
            raise BroadcastConflict("Сообщение уже удалено.")
        now = datetime.now(UTC)
        broadcast.retracted_at = now
        broadcast.retracted_by = actor_id
        broadcast.version += 1
        broadcast.content_version += 1
        await session.execute(
            update(NotificationDelivery)
            .where(
                NotificationDelivery.broadcast_id == broadcast.id,
                NotificationDelivery.provider_message_id.is_(None),
                NotificationDelivery.status.in_(["pending", "retry_wait"]),
            )
            .values(
                status="superseded",
                superseded_at=now,
                last_error_code="RETRACTED",
                last_error_at=now,
                next_attempt_at=None,
            )
        )
        await self._reconcile_chat(session, broadcast, immediate=True)
        poll = await session.scalar(select(Poll).where(Poll.broadcast_id == broadcast.id))
        if poll is not None and poll.closed_at is None:
            poll.closed_at = now
        audit(session, "broadcast.retracted", actor_id, broadcast.id)
        await session.flush()
        return await self.view(session, broadcast, scope)

    async def close_poll(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        broadcast_id: UUID,
        payload: BroadcastCommand,
    ) -> BroadcastView:
        broadcast, scope = await self._load(session, broadcast_id, actor_id, lock=True)
        self._expect(broadcast, payload.expected_version, "sent")
        poll = await session.scalar(
            select(Poll).where(Poll.broadcast_id == broadcast.id).with_for_update()
        )
        if poll is None or poll.closed_at is not None:
            raise BroadcastConflict("Опрос уже закрыт.")
        await self._close(session, broadcast, poll)
        broadcast.version += 1
        audit(session, "broadcast.poll_closed", actor_id, broadcast.id)
        await session.flush()
        return await self.view(session, broadcast, scope)

    async def _close(self, session: AsyncSession, broadcast: Broadcast, poll: Poll) -> None:
        poll.closed_at = datetime.now(UTC)
        broadcast.content_version += 1
        # Итоги при закрытии правятся сразу, без паузы в 5 минут.
        await self._reconcile_chat(session, broadcast, immediate=True)

    async def _reconcile_chat(
        self, session: AsyncSession, broadcast: Broadcast, *, immediate: bool
    ) -> None:
        """Отправленные посты в чатах догоняют текущее содержимое правкой."""
        now = datetime.now(UTC)
        rows = list(
            await session.scalars(
                select(NotificationDelivery)
                .where(
                    NotificationDelivery.broadcast_id == broadcast.id,
                    NotificationDelivery.purpose == BROADCAST_CHAT_PURPOSE,
                    NotificationDelivery.provider_message_id.is_not(None),
                )
                .with_for_update()
            )
        )
        for delivery in rows:
            in_sync = delivery.desired_version <= delivery.applied_version
            delivery.desired_version = broadcast.content_version
            if delivery.status == "failed":
                delivery.status = "accepted"
                delivery.retry_count = 0
            if immediate:
                delivery.next_attempt_at = None
            elif in_sync:
                # Итоги опроса — не чаще раза в 5 минут после последней правки.
                last = delivery.updated_at or now
                delivery.next_attempt_at = max(now, last + POLL_EDIT_INTERVAL)

    # ================================================================ отправка

    async def send_due(self, payload: dict[str, Any]) -> None:
        """Задача `broadcast.send`: разрешить аудиторию и создать доставки.

        Строка сообщения блокируется: отмена и отправка не проходят обе.
        Повтор задачи после отправки ничего не делает; уникальные индексы
        доставок не дают второго поста или сообщения.
        """
        broadcast_id = UUID(str(payload["broadcast_id"]))
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            broadcast = await session.get(
                Broadcast, broadcast_id, with_for_update=True, populate_existing=True
            )
            if broadcast is None or broadcast.status != "scheduled":
                return
            assert broadcast.scheduled_at is not None and broadcast.confirmed_by is not None
            if broadcast.scheduled_at > now + timedelta(seconds=1):
                raise RescheduleJob(broadcast.scheduled_at)
            # Полномочия подтвердившего проверяются заново перед отправкой.
            try:
                scope = await self._scope_for(session, broadcast, broadcast.confirmed_by)
            except (AccessDenied, ResourceNotFound):
                broadcast.status = "cancelled"
                broadcast.cancelled_at = now
                broadcast.version += 1
                audit(session, "broadcast.cancelled_no_authority", None, broadcast.id)
                return
            plan = await self.plan(session, broadcast, scope, strict=False)
            outbox = OutboxMessage(
                id=uuid4(),
                kind=FANOUT_OUTBOX_KIND,
                aggregate_id=broadcast.id,
                payload={"broadcast_id": str(broadcast.id)},
                status="processed",
                dedupe_key=f"broadcast:{broadcast.id}",
            )
            session.add(outbox)
            await session.flush()
            for house in plan.houses:
                session.add(BroadcastHouse(broadcast_id=broadcast.id, house_id=house.id))
            for company in plan.companies:
                session.add(BroadcastCompany(broadcast_id=broadcast.id, tenant_id=company.id))
            for binding, reason in plan.chats:
                session.add(
                    self._delivery(
                        outbox.id,
                        broadcast.id,
                        BROADCAST_CHAT_PURPOSE,
                        CHAT_POST_REF_PREFIX,
                        reason,
                        now,
                        chat_binding_id=binding.id,
                    )
                )
            for user, reason in plan.residents:
                session.add(
                    self._delivery(
                        outbox.id,
                        broadcast.id,
                        BROADCAST_DM_PURPOSE,
                        RESIDENT_DM_REF_PREFIX,
                        reason,
                        now,
                        recipient_user_id=user.id,
                    )
                )
            for user, reason in plan.staff:
                session.add(
                    self._delivery(
                        outbox.id,
                        broadcast.id,
                        BROADCAST_STAFF_PURPOSE,
                        STAFF_DM_REF_PREFIX,
                        reason,
                        now,
                        recipient_user_id=user.id,
                    )
                )
            broadcast.status = "sent"
            broadcast.sent_at = now
            broadcast.version += 1
            poll = await session.scalar(select(Poll).where(Poll.broadcast_id == broadcast.id))
            if poll is not None:
                await ReliabilityRepository(session).add_job(
                    kind=POLL_CLOSE_JOB,
                    payload={"poll_id": str(poll.id)},
                    priority=45,
                    delay_seconds=max(0, int((poll.closes_at - now).total_seconds())),
                    now=now,
                )
            audit(session, "broadcast.sent", broadcast.confirmed_by, broadcast.id)
            await session.flush()
        logger.info(
            "broadcast_fanned_out",
            extra={
                "broadcast_id": str(broadcast_id),
                "houses": len(plan.houses),
                "chats": len(plan.chats),
                "residents": len(plan.residents),
                "staff": len(plan.staff),
            },
        )

    @staticmethod
    def _delivery(
        outbox_id: UUID,
        broadcast_id: UUID,
        purpose: str,
        prefix: str,
        reason: str | None,
        now: datetime,
        *,
        chat_binding_id: UUID | None = None,
        recipient_user_id: UUID | None = None,
    ) -> NotificationDelivery:
        return NotificationDelivery(
            id=uuid4(),
            outbox_message_id=outbox_id,
            recipient_user_id=recipient_user_id,
            channel="max",
            purpose=purpose,
            broadcast_id=broadcast_id,
            chat_binding_id=chat_binding_id,
            launch_ref=_ref(prefix),
            status="skipped" if reason else "pending",
            last_error_code=reason,
            last_error_at=now if reason else None,
            desired_version=0,
        )

    async def close_due(self, payload: dict[str, Any]) -> None:
        """Задача `poll.close`: закрыть опрос в срок и поправить итоги в чате."""
        poll_id = UUID(str(payload["poll_id"]))
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            poll = await session.get(Poll, poll_id, populate_existing=True)
            if poll is None:
                return
            broadcast = await session.get(
                Broadcast, poll.broadcast_id, with_for_update=True, populate_existing=True
            )
            poll = await session.get(Poll, poll_id, with_for_update=True, populate_existing=True)
            if broadcast is None or poll is None or poll.closed_at is not None:
                return
            if poll.closes_at > now + timedelta(seconds=1):
                raise RescheduleJob(poll.closes_at)
            await self._close(session, broadcast, poll)
            audit(session, "broadcast.poll_closed", None, broadcast.id)

    # ===================================================================== жители

    async def feed(
        self, session: AsyncSession, *, actor_id: UUID, house_id: UUID, limit: int, offset: int
    ) -> AnnouncementList:
        context = await self.memberships.require_house(session, user_id=actor_id, house_id=house_id)
        self.memberships.require_permission(context, "incident.read")
        visible = and_(
            BroadcastHouse.house_id == house_id,
            Broadcast.status == "sent",
            Broadcast.retracted_at.is_(None),
            or_(
                Broadcast.kind == "poll",
                Broadcast.channels.cast(JSONB).contains(["feed"]),
            ),
        )
        base = select(Broadcast).join(BroadcastHouse, BroadcastHouse.broadcast_id == Broadcast.id)
        total = await session.scalar(
            select(func.count()).select_from(base.where(visible).subquery())
        )
        rows = list(
            await session.scalars(
                base.where(visible)
                .order_by(Broadcast.sent_at.desc(), Broadcast.id)
                .limit(limit)
                .offset(offset)
            )
        )
        items = []
        for broadcast in rows:
            summary = None
            poll = await session.scalar(select(Poll).where(Poll.broadcast_id == broadcast.id))
            if poll is not None:
                voters = await session.scalar(
                    select(func.count())
                    .select_from(PollBallot)
                    .where(PollBallot.poll_id == poll.id)
                )
                voted = await session.scalar(
                    select(
                        exists().where(
                            PollBallot.poll_id == poll.id, PollBallot.user_id == actor_id
                        )
                    )
                )
                summary = PollSummary(
                    poll_id=poll.id,
                    closes_at=poll.closes_at,
                    closed=self._closed(poll),
                    voters=voters or 0,
                    voted=bool(voted),
                )
            assert broadcast.sent_at is not None
            items.append(
                AnnouncementItem(
                    id=broadcast.id,
                    kind=broadcast.kind,
                    topic=broadcast.topic,
                    topic_label=TOPIC_LABELS.get(broadcast.topic or ""),
                    title=broadcast.title,
                    body=broadcast.body,
                    sender=await self.sender(session, broadcast),
                    sent_at=broadcast.sent_at,
                    edited_at=broadcast.edited_at,
                    poll=summary,
                )
            )
        user = await session.get(User, actor_id)
        return AnnouncementList(
            items=items,
            page=PageMeta(limit=limit, offset=offset, total=total or 0),
            broadcast_opt_out=bool(user and user.broadcast_opt_out_at),
        )

    @staticmethod
    def _closed(poll: Poll) -> bool:
        return poll_closed(poll)

    async def poll_results(self, session: AsyncSession, poll: Poll) -> PollResults:
        options, voters = await self._tally(session, poll)
        return PollResults(
            poll_id=poll.id,
            question=poll.question,
            multiple=poll.multiple,
            closes_at=poll.closes_at,
            closed=self._closed(poll),
            voters=voters,
            options=options,
        )

    async def _tally(self, session: AsyncSession, poll: Poll) -> tuple[list[PollOptionResult], int]:
        return await tally(session, poll)

    async def _poll_access(
        self, session: AsyncSession, poll: Poll, actor_id: UUID
    ) -> tuple[Broadcast, UUID | None, bool]:
        """Опрос виден жителю и сотруднику домов аудитории; голосует житель."""
        broadcast = await session.get(Broadcast, poll.broadcast_id)
        if broadcast is None or broadcast.status != "sent" or broadcast.retracted_at is not None:
            raise ResourceNotFound("Resource was not found")
        audience = set(
            await session.scalars(
                select(BroadcastHouse.house_id).where(BroadcastHouse.broadcast_id == broadcast.id)
            )
        )
        resident_house: UUID | None = None
        visible = False
        for house, context in await self.memberships.contexts_with(
            session, user_id=actor_id, permission="incident.read"
        ):
            if house.id not in audience:
                continue
            visible = True
            if context.resident_access and resident_house is None:
                resident_house = house.id
        if not visible:
            raise ResourceNotFound("Resource was not found")
        return broadcast, resident_house, visible

    async def poll_view(self, session: AsyncSession, *, actor_id: UUID, poll_id: UUID) -> PollView:
        poll = await session.get(Poll, poll_id, populate_existing=True)
        if poll is None:
            raise ResourceNotFound("Resource was not found")
        broadcast, house, _ = await self._poll_access(session, poll, actor_id)
        return await self._poll_view(session, poll, broadcast, actor_id, house)

    async def _poll_view(
        self,
        session: AsyncSession,
        poll: Poll,
        broadcast: Broadcast,
        actor_id: UUID,
        house: UUID | None,
    ) -> PollView:
        options, voters = await self._tally(session, poll)
        mine = list(
            await session.scalars(
                select(PollChoice.option_id).where(
                    PollChoice.poll_id == poll.id, PollChoice.user_id == actor_id
                )
            )
        )
        closed = self._closed(poll)
        reason = (
            "Опрос закрыт."
            if closed
            else None
            if house is not None
            else "Голосуют жители домов, которым адресован опрос."
        )
        return PollView(
            id=poll.id,
            broadcast_id=broadcast.id,
            question=poll.question,
            multiple=poll.multiple,
            closes_at=poll.closes_at,
            closed=closed,
            voters=voters,
            options=options,
            my_choice=mine,
            can_vote=not closed and house is not None,
            reason=reason,
            sender=await self.sender(session, broadcast),
            disclaimer=POLL_DISCLAIMER,
        )

    async def vote(
        self, session: AsyncSession, *, actor_id: UUID, poll_id: UUID, payload: PollVote
    ) -> PollView:
        """Один голос на человека; до закрытия его можно изменить. Транзакция — у вызывающего."""
        poll = await session.get(Poll, poll_id, populate_existing=True)
        if poll is None:
            raise ResourceNotFound("Resource was not found")
        broadcast = await session.get(
            Broadcast, poll.broadcast_id, with_for_update=True, populate_existing=True
        )
        poll = await session.get(Poll, poll_id, with_for_update=True, populate_existing=True)
        assert poll is not None and broadcast is not None
        broadcast, house, _ = await self._poll_access(session, poll, actor_id)
        if self._closed(poll):
            raise PollClosed("Опрос закрыт — голос не принят.")
        if house is None:
            raise AccessDenied("Голосуют жители домов, которым адресован опрос")
        valid = set(
            await session.scalars(select(PollOption.id).where(PollOption.poll_id == poll.id))
        )
        if any(option not in valid for option in payload.option_ids):
            raise FieldValidationError("Такого варианта нет в опросе", field="option_ids")
        if not poll.multiple and len(payload.option_ids) != 1:
            raise FieldValidationError("В этом опросе выбирается один вариант", field="option_ids")
        ballot = await session.get(PollBallot, (poll.id, actor_id), with_for_update=True)
        current = set(
            await session.scalars(
                select(PollChoice.option_id).where(
                    PollChoice.poll_id == poll.id, PollChoice.user_id == actor_id
                )
            )
        )
        if ballot is not None and current == set(payload.option_ids):
            return await self._poll_view(session, poll, broadcast, actor_id, house)
        now = datetime.now(UTC)
        if ballot is None:
            ballot = PollBallot(poll_id=poll.id, user_id=actor_id, house_id=house, revision=1)
            session.add(ballot)
        else:
            ballot.revision += 1
            ballot.updated_at = now
            ballot.house_id = house
            for choice in await session.scalars(
                select(PollChoice).where(
                    PollChoice.poll_id == poll.id, PollChoice.user_id == actor_id
                )
            ):
                await session.delete(choice)
        await session.flush()
        for option in payload.option_ids:
            session.add(PollChoice(poll_id=poll.id, user_id=actor_id, option_id=option))
        broadcast.content_version += 1
        await self._reconcile_chat(session, broadcast, immediate=False)
        await session.flush()
        return await self._poll_view(session, poll, broadcast, actor_id, house)

    async def preferences(self, session: AsyncSession, *, actor_id: UUID) -> ResidentPreferences:
        user = await session.get(User, actor_id)
        if user is None:
            raise ResourceNotFound("Resource was not found")
        return ResidentPreferences(broadcast_opt_out=user.broadcast_opt_out_at is not None)

    async def set_preferences(
        self, session: AsyncSession, *, actor_id: UUID, payload: ResidentPreferences
    ) -> ResidentPreferences:
        user = await session.get(User, actor_id, with_for_update=True)
        if user is None:
            raise ResourceNotFound("Resource was not found")
        if payload.broadcast_opt_out and user.broadcast_opt_out_at is None:
            user.broadcast_opt_out_at = datetime.now(UTC)
        elif not payload.broadcast_opt_out:
            user.broadcast_opt_out_at = None
        await session.flush()
        return ResidentPreferences(broadcast_opt_out=user.broadcast_opt_out_at is not None)

    # ======================================================== уведомления платформы

    async def platform_notices(
        self, session: AsyncSession, *, actor_id: UUID, company_id: UUID, limit: int, offset: int
    ) -> PlatformNoticeList:
        await require_company(session, actor_id, company_id, admin=False)
        condition = and_(
            BroadcastCompany.tenant_id == company_id,
            Broadcast.origin == "platform",
            Broadcast.status == "sent",
            Broadcast.retracted_at.is_(None),
            Broadcast.channels.cast(JSONB).contains(["staff"]),
        )
        base = select(Broadcast).join(
            BroadcastCompany, BroadcastCompany.broadcast_id == Broadcast.id
        )
        total = await session.scalar(
            select(func.count()).select_from(base.where(condition).subquery())
        )
        rows = await session.scalars(
            base.where(condition)
            .order_by(Broadcast.sent_at.desc(), Broadcast.id)
            .limit(limit)
            .offset(offset)
        )
        return PlatformNoticeList(
            items=[
                PlatformNotice(
                    id=row.id,
                    title=row.title,
                    body=row.body,
                    sent_at=row.sent_at or row.created_at,
                    edited_at=row.edited_at,
                )
                for row in rows
            ],
            page=PageMeta(limit=limit, offset=offset, total=total or 0),
        )


async def tally(session: AsyncSession, poll: Poll) -> tuple[list[PollOptionResult], int]:
    """Итоги опроса: только числа и доли, без имён."""
    options = list(
        await session.scalars(
            select(PollOption).where(PollOption.poll_id == poll.id).order_by(PollOption.position)
        )
    )
    counts = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(PollChoice.option_id, func.count())
                .where(PollChoice.poll_id == poll.id)
                .group_by(PollChoice.option_id)
            )
        )
    }
    voters = (
        await session.scalar(
            select(func.count()).select_from(PollBallot).where(PollBallot.poll_id == poll.id)
        )
        or 0
    )
    return (
        [
            PollOptionResult(
                id=option.id,
                position=option.position,
                label=option.label,
                votes=counts.get(option.id, 0),
                share=round(counts.get(option.id, 0) / voters, 4) if voters else 0.0,
            )
            for option in options
        ],
        voters,
    )


def poll_closed(poll: Poll, now: datetime | None = None) -> bool:
    return poll.closed_at is not None or poll.closes_at <= (now or datetime.now(UTC))


def dm_quiet_until(
    at: datetime,
    window: tuple[int, int] | None = (DEFAULT_QUIET_START, DEFAULT_QUIET_END),
    zone: tzinfo = MSK,
) -> datetime | None:
    """Личные рассылки ночью не приходят: `BROADCAST_DM_QUIET_HOURS`, по умолчанию
    22:00–08:00 местного времени (D4: пояс домов рассылки), как у чатов.
    `None` — без окна."""
    return quiet_until(window[0], window[1], at, zone) if window else None


__all__ = [
    "BroadcastConflict",
    "BroadcastService",
    "CHAT_POST_REF_PREFIX",
    "POLL_CLOSE_JOB",
    "PollClosed",
    "QUIET_HOURS_CODE",
    "RESIDENT_DM_REF_PREFIX",
    "SEND_JOB",
    "STAFF_DM_REF_PREFIX",
    "dialog_ready",
    "dm_quiet_until",
    "poll_closed",
    "tally",
]
