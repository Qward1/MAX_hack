"""Личный бот ДомСигнала (B-04, срез D1).

Бот в личке — такой же вход в продукт, как mini app и домовой чат:

* `bot_started` без токена подключения A-07 (или с чужим параметром) и
  `/start` — приветствие: что это и как работает, кнопки «Открыть ДомСигнал»
  и, если у человека нет домов, а открытые есть, «Выбрать дом». Поток
  подключения чата по токену `connect_…` не меняется.
* `/help`, `/version` (короткий SHA сборки).
* Свободный текст и `/report …` — запись приёма `dm_report` и тот же путь,
  что у `/report` в группе: окно из одной реплики, AI-пул и сторож правил
  30 с (при опасности по правилам — сразу), общий роутер и ActionCard.
* Выбор дома: один — сразу; несколько — кнопки с адресами, текст ждёт до
  30 минут и стирается; нет домов — объяснение и «Выбрать дом», если есть
  открытые.

Приём в вебхуке только пишет в БД и ставит задачу; проверка членства по MAX
API, ответы и нажатия кнопок — в операционном пуле. Ответы идут через
существующий outbox с ключом по `event_id`, поэтому повтор события не даёт
второго ответа. В журналах нет ни текста, ни MAX id.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.ai import WindowAnalyzer, WindowInput, WindowLine, decide_explicit_report
from domsignal.bot.max_updates import MaxEvent
from domsignal.bot.messaging import MessagingError
from domsignal.contracts.routing import DangerKind
from domsignal.core.routing import HouseRoutingContext
from domsignal.db.models import (
    ChatBinding,
    CompanyOnboardingRequest,
    ConnectionRequest,
    ExplicitIntake,
    House,
    User,
)
from domsignal.db.repositories.access import AccessRepository
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.services.bot_replies import (
    CALLBACK_JOB,
    CHOOSE_HOUSE,
    CHOOSE_HOUSE_LABEL,
    CONNECT_BUSY,
    CONNECT_CLAIMED,
    CONNECT_INVALID,
    DM_JOB,
    EXPIRED,
    GREETING,
    GROUP_ACK,
    GROUP_ACK_LINK,
    HELP,
    HOLD_JOB,
    HOUSE_JOINED,
    HOUSE_PICKED,
    HOUSE_UNAVAILABLE,
    JOINED,
    LIMIT,
    NO_ACCESS,
    NO_HOUSES,
    NO_HOUSES_OPEN,
    NO_OPEN_HOUSES,
    NOT_A_PROBLEM,
    OPEN_HOUSES_LEAD,
    OTHER_CHOSEN,
    VERSION,
    ReplyButton,
    as_message,
    callback_button,
    enqueue_reply,
    open_app_button,
)
from domsignal.services.chat_voice import (
    CHAT_MESSAGE_INTENT_KIND,
    REPORT_ACK_PURPOSE,
    ChatMessageIntent,
)
from domsignal.services.errors import AccessDenied, RescheduleJob, ResourceNotFound
from domsignal.services.explicit_reports import ExplicitReportService
from domsignal.services.group_messages import (
    ANALYZE_JOB,
    ANALYZE_PRIORITY,
    FALLBACK_DELAY_SECONDS,
    FALLBACK_JOB,
    FALLBACK_PRIORITY,
)
from domsignal.services.membership import MembershipService
from domsignal.services.notifications import TicketNotificationHandler
from domsignal.services.reports import IncidentClosed, ReportService
from domsignal.services.resident_access import ResidentAccessService, ensure_max_user
from domsignal.services.route_card_render import safety_lines
from domsignal.services.routing import RoutingService

logger = logging.getLogger(__name__)

#: Короче — не описание проблемы, а подсказка по использованию.
MIN_TEXT = 5

#: Ответ в группе на `/report` автору без диалога — не чаще раза за это время.
GROUP_ACK_PAUSE = timedelta(minutes=10)

#: Сколько открытых домов показывается кнопками.
MAX_HOUSE_BUTTONS = 10

_COMMAND = re.compile(r"(/[a-z_]{1,20})(?:@[A-Za-z0-9_]{1,100})?(?:\s+(.*))?", re.S)


def split_command(text: str) -> tuple[str | None, str]:
    """`/help` → ("/help", ""); `/report лифт` → ("/report", "лифт"); текст → (None, текст)."""
    match = _COMMAND.fullmatch(text)
    if not match:
        return None, text
    return match[1], (match[2] or "").strip()


#: Запрос подключения, который ещё ждёт группу или подтверждения УК.
CONNECT_OPEN = frozenset(
    {"connector_claimed", "chat_detected", "max_verified", "awaiting_approval"}
)


def _touch_dialog(user: User, at: datetime) -> None:
    if user.max_dialog_at is None or user.max_dialog_at < at:
        user.max_dialog_at = at


class PersonalBotService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        resident_access: ResidentAccessService,
        explicit_reports: ExplicitReportService,
        reports: ReportService,
        notifications: TicketNotificationHandler,
        rules_analyzer: WindowAnalyzer,
        routing: RoutingService,
        answer_enabled: bool,
        build_commit: str = "dev",
        bot_username: str | None = None,
        daily_limit: int = 10,
        hold_seconds: int = 1800,
        application_digest: Callable[[str], str] | None = None,
    ) -> None:
        self.sessions = session_factory
        self.resident_access = resident_access
        self.explicit_reports = explicit_reports
        self.reports = reports
        # Ответ на нажатие — тем же провайдером сообщений, что и доставка.
        self.notifications = notifications
        self.rules_analyzer = rules_analyzer
        self.routing = routing
        self.answer_enabled = answer_enabled
        self.build_commit = build_commit
        self.bot_username = bot_username
        self.daily_limit = daily_limit
        self.hold = timedelta(seconds=hold_seconds)
        self.memberships = MembershipService()
        # Хэш кода `ca_…` ссылки «Получать уведомления в MAX» (D2).
        self.application_digest = application_digest

    # ============================================================ вебхук

    async def on_started(self, session: AsyncSession, event: MaxEvent) -> UUID | None:
        """`bot_started`: диалог начат; без токена A-07 — приветствие."""
        assert event.actor
        user = await ensure_max_user(session, event.actor, None)
        _touch_dialog(user, event.occurred_at)
        if event.token and event.token.startswith("connect_"):
            return None  # Поток подключения чата A-07 не меняется.
        if event.token and event.token.startswith("ca_") and self.application_digest:
            await self._subscribe_application(session, event, user)
            return None
        return await self._job(session, event.event_id, user.id, "start")

    async def on_connect(
        self, session: AsyncSession, event: MaxEvent, request: ConnectionRequest | None
    ) -> None:
        """Код подключения чата (A-07) — по ссылке или набранной командой.

        Отвечает, что делать дальше: без ответа администратор чата не знает,
        принят ли код. Сам токен в ответ и в журнал не попадает.
        """
        assert event.actor
        user = await ensure_max_user(session, event.actor, None)
        _touch_dialog(user, event.occurred_at)
        if (
            request is not None
            and request.connector_max_user_id == event.actor
            and (request.status in CONNECT_OPEN)
        ):
            text = CONNECT_CLAIMED
        elif request is not None and (
            request.last_error_code == "connector_connection_in_progress"
        ):
            text = CONNECT_BUSY
        else:
            text = CONNECT_INVALID
        await enqueue_reply(
            session, user_id=user.id, event_id=event.event_id, key="connect", text=text
        )

    async def _subscribe_application(
        self, session: AsyncSession, event: MaxEvent, user: User
    ) -> None:
        """Код `ca_…` со страницы статуса заявки УК: писать сюда о смене статуса.

        Код одноразовый; сама ссылка статуса боту не передаётся и в сообщениях
        не упоминается. Повтор события не даёт второго ответа (ключ — событие).
        """
        from domsignal.services.company_signup import NOTIFY_INVALID, NOTIFY_LINKED

        assert event.token and self.application_digest
        row = await session.scalar(
            select(CompanyOnboardingRequest)
            .where(
                CompanyOnboardingRequest.notify_code_hash
                == self.application_digest(event.token.removeprefix("ca_"))
            )
            .with_for_update()
        )
        if row is not None:
            row.notify_user_id, row.notify_code_hash = user.id, None
        await enqueue_reply(
            session,
            user_id=user.id,
            event_id=event.event_id,
            key="application",
            text=NOTIFY_LINKED.format(name=row.short_name) if row else NOTIFY_INVALID,
        )

    @staticmethod
    async def on_stopped(session: AsyncSession, event: MaxEvent) -> None:
        """`bot_stopped`: бот больше не пишет этому человеку первым."""
        if not event.actor:
            return
        user = await AccessRepository(session).user_by_max_id(event.actor)
        if user is not None and (
            user.max_dialog_stopped_at is None or user.max_dialog_stopped_at < event.occurred_at
        ):
            user.max_dialog_stopped_at = event.occurred_at

    async def on_dialog_message(self, session: AsyncSession, event: MaxEvent) -> UUID | None:
        """Сообщение в личке: команда, подсказка или запись приёма `dm_report`."""
        assert event.actor and event.chat_id
        user = await ensure_max_user(session, event.actor, None)
        _touch_dialog(user, event.occurred_at)
        text = (event.text or "").strip()
        command, body = split_command(text)
        if command in {"/start", "/help", "/version"}:
            return await self._job(session, event.event_id, user.id, command[1:])
        if command is not None and command != "/report":
            return await self._job(session, event.event_id, user.id, "help")
        body = body if command == "/report" else text
        if len(body) < MIN_TEXT:
            return await self._job(session, event.event_id, user.id, "short")
        if await self._today(session, user.id, event.occurred_at) >= self.daily_limit:
            return await self._job(session, event.event_id, user.id, "limit")
        session.add(
            ExplicitIntake(
                event_id=event.event_id,
                channel="dm_report",
                chat_id=event.chat_id,
                user_id=user.id,
                external_user_id=event.actor,
                text=body,
                occurred_at=event.occurred_at,
                state="awaiting_house",
                hold_until=event.occurred_at + self.hold,
            )
        )
        return await self._job(session, event.event_id, user.id, "text")

    async def on_callback(self, session: AsyncSession, event: MaxEvent) -> UUID | None:
        """Нажатие кнопки бота. Кто нажал — из подписанного события MAX."""
        callback = event.bot_callback
        assert callback is not None
        user = await ensure_max_user(session, callback.actor, None)
        _touch_dialog(user, event.occurred_at)
        job = await ReliabilityRepository(session).add_job(
            kind=CALLBACK_JOB,
            payload={
                "event_id": event.event_id,
                "user_id": str(user.id),
                "callback_id": callback.callback_id,
                "action": callback.action,
                "argument": callback.argument,
            },
            priority=15,
        )
        return job.id

    async def on_group_report(
        self,
        session: AsyncSession,
        *,
        binding: ChatBinding,
        actor: str,
        event_id: str,
        occurred_at: datetime,
    ) -> bool:
        """Ответ в группе на явный `/report`, если бот не может написать в личку.

        Бот не пишет первым тому, кто не начинал с ним диалог. Такому автору —
        одно короткое сообщение в группе, не чаще раза в 10 минут; после
        `bot_started` последняя карточка досылается в личку.
        """
        user = await ensure_max_user(session, actor, None)
        if user.dialog_open:
            return False
        if user.group_ack_at is not None and occurred_at - user.group_ack_at < GROUP_ACK_PAUSE:
            return False
        user.group_ack_at = occurred_at
        text = GROUP_ACK
        if self.bot_username:
            text = f"{GROUP_ACK}\n{GROUP_ACK_LINK.format(bot=self.bot_username)}"
        intent = ChatMessageIntent(
            purpose=REPORT_ACK_PURPOSE,
            chat_binding_id=binding.id,
            binding_version=binding.binding_version,
            text=text,
        )
        ReliabilityRepository(session).add_outbox(
            kind=CHAT_MESSAGE_INTENT_KIND,
            aggregate_id=binding.id,
            payload=intent.model_dump(mode="json"),
            dedupe_key=f"report_ack:{event_id}"[:100],
        )
        return True

    async def _job(self, session: AsyncSession, event_id: str, user_id: UUID, kind: str) -> UUID:
        job = await ReliabilityRepository(session).add_job(
            kind=DM_JOB,
            payload={"event_id": event_id, "user_id": str(user_id), "kind": kind},
            priority=20,
        )
        return job.id

    @staticmethod
    async def _today(session: AsyncSession, user_id: UUID, at: datetime) -> int:
        """Сообщения о проблемах за сутки; болтовня в предел не входит."""
        return int(
            await session.scalar(
                select(func.count())
                .select_from(ExplicitIntake)
                .where(
                    ExplicitIntake.user_id == user_id,
                    ExplicitIntake.channel == "dm_report",
                    ExplicitIntake.created_at > at - timedelta(days=1),
                    or_(
                        ExplicitIntake.result_kind.is_(None),
                        ExplicitIntake.result_kind != "not_a_problem",
                    ),
                )
            )
            or 0
        )

    # ============================================================ задачи

    async def handle_dm(self, payload: dict[str, Any]) -> None:
        """Задача `bot.dm`: ответ на событие лички."""
        event_id = str(payload["event_id"])
        user_id = UUID(str(payload["user_id"]))
        kind = str(payload["kind"])
        if kind == "text":
            await self._route_text(event_id, user_id)
        elif kind == "start":
            await self.resident_access.refresh(user_id)
            async with self.sessions() as session, session.begin():
                buttons = [[open_app_button()]]
                if await self._offer_open_houses(session, user_id):
                    buttons.append([callback_button(CHOOSE_HOUSE_LABEL, "b:houses")])
                await enqueue_reply(
                    session,
                    user_id=user_id,
                    event_id=event_id,
                    key="start",
                    text=GREETING,
                    buttons=buttons,
                )
                # Карточка по `/report`, которая не ушла без диалога (≤ 24 ч).
                await self.notifications.rearm_route_card(
                    session, user_id=user_id, now=datetime.now(UTC)
                )
        else:
            text, buttons = {
                "help": (HELP, [[open_app_button()]]),
                "version": (VERSION.format(version=self.version), []),
                "short": (f"{NOT_A_PROBLEM}\n\n{HELP}", []),
                "limit": (LIMIT.format(limit=self.daily_limit), []),
            }.get(kind, (HELP, []))
            async with self.sessions() as session, session.begin():
                await enqueue_reply(
                    session,
                    user_id=user_id,
                    event_id=event_id,
                    key=kind,
                    text=text,
                    buttons=buttons,
                )
        logger.info("bot_dm_handled", extra={"kind": kind})

    @property
    def version(self) -> str:
        return self.build_commit[:7] if self.build_commit else "dev"

    async def _offer_open_houses(self, session: AsyncSession, user_id: UUID) -> bool:
        """«Выбрать дом» — только тем, у кого нет домов, и если открытые есть."""
        houses = await self.memberships.contexts_with(
            session, user_id=user_id, permission="report.create"
        )
        return not houses and await self.resident_access.has_open_houses(session)

    async def _route_text(self, event_id: str, user_id: UUID) -> None:
        """Сообщение о проблеме: членство, дом, затем тот же разбор, что у группы."""
        await self.resident_access.refresh(user_id)
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            intake = await session.get(ExplicitIntake, event_id, with_for_update=True)
            if (
                intake is None
                or intake.user_id != user_id
                or intake.state != "awaiting_house"
                or intake.house_id is not None
            ):
                return  # Повтор задачи: дом уже выбран или время вышло.
            danger = await self._rules_danger(intake.text, now)
            houses = await self.memberships.contexts_with(
                session, user_id=user_id, permission="report.create"
            )
            if len(houses) == 1:
                await self._start_analysis(session, intake, houses[0][0].id, danger=bool(danger))
                return
            if danger:
                # Опасность — блок безопасности первым, до выбора дома.
                await self._safety_reply(session, user_id, event_id, danger)
            if not houses:
                text = NO_HOUSES
                buttons: list[list[ReplyButton]] = [[open_app_button()]]
                if await self.resident_access.has_open_houses(session):
                    text = f"{NO_HOUSES}\n{NO_HOUSES_OPEN}"
                    buttons.append([callback_button(CHOOSE_HOUSE_LABEL, "b:houses")])
                await enqueue_reply(
                    session,
                    user_id=user_id,
                    event_id=event_id,
                    key="nohouse",
                    text=text,
                    buttons=buttons,
                )
                self._finish(intake, "ignored", now)
                return
            await enqueue_reply(
                session,
                user_id=user_id,
                event_id=event_id,
                key="choose",
                text=CHOOSE_HOUSE,
                buttons=[
                    [callback_button(house.address, f"b:pick:{event_id}:{house.id}")]
                    for house, _ in houses[:MAX_HOUSE_BUTTONS]
                ],
            )
            intake.hold_until = now + self.hold
            await ReliabilityRepository(session).add_job(
                kind=HOLD_JOB,
                payload={"event_id": event_id},
                priority=90,
                delay_seconds=int(self.hold.total_seconds()),
            )

    async def _rules_danger(self, text: str, now: datetime) -> tuple[DangerKind, ...]:
        """Опасность по правилам — без сети и без модели, за миллисекунды."""
        analysis = await self.rules_analyzer.analyze(
            WindowInput(
                channel="dm_report",
                lines=(WindowLine(line_id="m1", author_ref="a1", text=text, sent_at=now),),
            )
        )
        return tuple(decide_explicit_report(analysis).emergency.kinds)

    async def _safety_reply(
        self, session: AsyncSession, user_id: UUID, event_id: str, danger: tuple[DangerKind, ...]
    ) -> None:
        # Памятка федерального слоя: дом ещё не выбран.
        block = self.routing.safety(HouseRoutingContext(), danger)
        if block is None:
            return
        await enqueue_reply(
            session,
            user_id=user_id,
            event_id=event_id,
            key="safety",
            text="\n".join(safety_lines(block)),
        )

    @staticmethod
    async def _start_analysis(
        session: AsyncSession, intake: ExplicitIntake, house_id: UUID, *, danger: bool
    ) -> None:
        """Дом выбран: запись идёт в общий разбор (AI-пул + сторож правил)."""
        intake.house_id = house_id
        intake.state = "pending"
        intake.hold_until = None
        payload = {"event_id": intake.event_id}
        now = datetime.now(UTC)
        reliability = ReliabilityRepository(session)
        await reliability.add_job(
            kind=ANALYZE_JOB, payload=payload, priority=ANALYZE_PRIORITY, now=now
        )
        # Опасность по правилам — сторож сразу: ответ не ждёт AI-пул.
        await reliability.add_job(
            kind=FALLBACK_JOB,
            payload=payload,
            priority=FALLBACK_PRIORITY,
            delay_seconds=0 if danger else FALLBACK_DELAY_SECONDS,
            now=now,
        )

    @staticmethod
    def _finish(intake: ExplicitIntake, result_kind: str, now: datetime) -> None:
        """Закрыть запись без разбора; слова жителя не сохраняются."""
        intake.state = "done"
        intake.result_kind = result_kind
        intake.claimed_at = intake.claimed_at or now
        intake.claimed_by = intake.claimed_by or "bot.dm"
        intake.text = ""
        intake.clean_description = None
        intake.pending_analysis = None
        intake.hold_until = None

    async def expire_hold(self, payload: dict[str, Any]) -> None:
        """Задача `bot.hold.expire`: текст ждал выбора 30 минут — стираем."""
        event_id = str(payload["event_id"])
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            intake = await session.get(ExplicitIntake, event_id, with_for_update=True)
            if intake is None or intake.state not in {"awaiting_house", "awaiting_choice"}:
                return
            if intake.hold_until is not None and intake.hold_until > now:
                raise RescheduleJob(intake.hold_until)
            self._finish(intake, "expired", now)

    # ============================================================ кнопки

    async def handle_callback(self, payload: dict[str, Any]) -> None:
        """Задача `bot.callback`: действие и ответ на нажатие (`POST /answers`)."""
        user_id = UUID(str(payload["user_id"]))
        action = str(payload["action"])
        argument = payload.get("argument")
        text, buttons = await self._callback(user_id, action, argument)
        logger.info("bot_callback_handled", extra={"action": action})
        if not self.answer_enabled:
            return
        try:
            await self.notifications.provider.answer_callback(
                str(payload["callback_id"]), as_message(text, buttons)
            )
        except MessagingError:
            # Действие уже сохранено и идемпотентно; повтор задачи ответит снова.
            raise

    async def _callback(
        self, user_id: UUID, action: str, argument: str | None
    ) -> tuple[str, list[list[ReplyButton]]]:
        if action == "houses":
            async with self.sessions() as session, session.begin():
                houses = await self.resident_access.open_houses(session, user_id=user_id)
            if not houses:
                return NO_OPEN_HOUSES, [[open_app_button()]]
            return OPEN_HOUSES_LEAD, [
                [callback_button(house.address, f"b:join:{house.id}")]
                for house in houses[:MAX_HOUSE_BUTTONS]
            ]
        if action == "join" and argument:
            try:
                house_id = UUID(argument)
                async with self.sessions() as session, session.begin():
                    await self.resident_access.join_open_house(
                        session, user_id=user_id, house_id=house_id
                    )
                    house = await session.get(House, house_id)
                    address = house.address if house else ""
            except (ValueError, ResourceNotFound):
                return HOUSE_UNAVAILABLE, []
            return HOUSE_JOINED.format(address=address), [[open_app_button()]]
        if action == "pick" and argument and ":" in argument:
            return await self._pick(user_id, *argument.rsplit(":", 1))
        if action == "same" and argument and ":" in argument:
            return await self._same(user_id, *argument.rsplit(":", 1))
        if action == "new" and argument:
            outcome = await self.explicit_reports.choose_other(event_id=argument, user_id=user_id)
            return (OTHER_CHOSEN if outcome else EXPIRED), []
        return EXPIRED, []

    async def _pick(
        self, user_id: UUID, event_id: str, house_ref: str
    ) -> tuple[str, list[list[ReplyButton]]]:
        try:
            house_id = UUID(house_ref)
        except ValueError:
            return EXPIRED, []
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            intake = await session.get(ExplicitIntake, event_id, with_for_update=True)
            if intake is None or intake.user_id != user_id or intake.channel != "dm_report":
                return EXPIRED, []
            house = await session.get(House, house_id)
            if intake.house_id == house_id and house is not None:
                # Повтор нажатия или задачи: дом уже выбран.
                return HOUSE_PICKED.format(address=house.address), []
            if intake.state != "awaiting_house" or (
                intake.hold_until is not None and intake.hold_until <= now
            ):
                return EXPIRED, []
            try:
                context = await self.memberships.require_house(
                    session, user_id=user_id, house_id=house_id, source="max_dm"
                )
                self.memberships.require_permission(context, "report.create")
            except (AccessDenied, ResourceNotFound):
                return NO_ACCESS, []
            assert house is not None
            danger = await self._rules_danger(intake.text, now)
            await self._start_analysis(session, intake, house_id, danger=bool(danger))
            return HOUSE_PICKED.format(address=house.address), []

    async def _same(
        self, user_id: UUID, event_id: str, incident_ref: str
    ) -> tuple[str, list[list[ReplyButton]]]:
        try:
            incident_id = UUID(incident_ref)
        except ValueError:
            return EXPIRED, []
        if not await self.explicit_reports.pending_choice(event_id=event_id, user_id=user_id):
            return EXPIRED, []
        async with self.sessions() as session:
            try:
                detail = await self.reports.join(
                    session,
                    actor_id=user_id,
                    incident_id=incident_id,
                    idempotency_key=f"dm-join:{event_id}"[:200],
                )
            except IncidentClosed:
                detail = None
            except (AccessDenied, ResourceNotFound):
                return NO_ACCESS, []
        if detail is None:
            # Проблему закрыли, пока житель думал: это новая проблема.
            outcome = await self.explicit_reports.choose_other(event_id=event_id, user_id=user_id)
            return (OTHER_CHOSEN if outcome else EXPIRED), []
        await self.explicit_reports.joined(event_id=event_id, user_id=user_id)
        return JOINED.format(title=detail.title or "Проблема дома"), [[open_app_button()]]


__all__ = ["GROUP_ACK_PAUSE", "MIN_TEXT", "PersonalBotService", "split_command"]
