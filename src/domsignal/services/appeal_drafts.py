"""Черновик обращения: собрать, отредактировать, отметить подачу (A-04).

Текст собирается детерминированно. Каркас — из проверенного справочника
(адресат, канал, обязательные поля, факты канала с источником). Абзац
описания — деловая переформулировка модели, если она есть и прошла guard
`no_new_facts`, иначе исходные слова жителя. Адрес дома, подъезд, этаж и
«с какого времени» берутся только из проверенных данных и значений с цитатой.

Продукт **не отправляет** обращение: житель открывает официальный канал сам.
`mark-filed` записывает его отметку как `user_reported` и не утверждает, что
обращение где-то зарегистрировано.

Требование канала «Госуслуги. Решаем вместе» — одна проблема, одно обращение,
поэтому на один исход маршрутизации у автора может быть только один черновик.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.appeals import (
    AppealDraftCreate,
    AppealDraftUpdate,
    AppealDraftView,
    AppealFiledMark,
)
from domsignal.contracts.incidents import ActionDescriptor, Provenance
from domsignal.contracts.routing import RouteChannel
from domsignal.core.routing import HouseRoutingContext
from domsignal.db.models import AppealDraft, ExplicitIntake, House, Incident, Report, RouteOutcome
from domsignal.services.context import OperationContext
from domsignal.services.errors import ResourceNotFound, ServiceError
from domsignal.services.membership import MembershipService
from domsignal.services.routing import RoutingService

AI_NOTE = "Абзац описания подготовлен с помощью ИИ — проверьте его перед отправкой."
SELF_FILING_NOTE = "ДомСигнал не отправляет обращения за вас — вы отправляете его сами."
PROBLEM_HEADING = "Суть проблемы или предложения:"
CHANNEL_FACTS_HEADING = "Что известно о канале:"

_ADDRESS_LABEL = "Адрес"
_ENTRANCE_LABEL = "Подъезд"
_FLOOR_LABEL = "Этаж"
_SINCE_LABEL = "Наблюдается с"
_RECIPIENT_LABEL = "Адресат"
_CHANNEL_LABEL = "Официальный канал"
_SOURCE_PREFIX = "Источник: "


class StaleDraftVersion(ServiceError):
    status = 409
    code = "stale_version"
    title = "Данные изменились"


class AppealDraftService:
    """Один и тот же сервис вызывают REST и (в будущем) бот."""

    def __init__(self, *, routing: RoutingService) -> None:
        self.routing = routing
        self.memberships = MembershipService()

    # --------------------------------------------------------------- команды

    async def create(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        payload: AppealDraftCreate,
    ) -> AppealDraftView:
        async with session.begin():
            context = await self.memberships.require_house(
                session, user_id=actor_id, house_id=payload.house_id, for_write=True
            )
            outcome = await self._outcome(session, context, payload)
            existing = await session.scalar(
                select(AppealDraft).where(
                    AppealDraft.route_outcome_id == outcome.id,
                    AppealDraft.author_id == actor_id,
                )
            )
            if existing is not None:
                # Одна проблема — одно обращение: повторный запрос отдаёт тот же
                # черновик, а не создаёт второй и не теряет правки жителя.
                return await self._view(session, existing, outcome, context)
            text, ai_assisted = await self._compose(session, outcome, context)
            draft = AppealDraft(
                house_id=context.house_id,
                route_outcome_id=outcome.id,
                author_id=actor_id,
                text=text,
                version=1,
                ai_assisted=ai_assisted,
            )
            session.add(draft)
            await session.flush()
            return await self._view(session, draft, outcome, context)

    async def detail(
        self, session: AsyncSession, *, actor_id: UUID, draft_id: UUID
    ) -> AppealDraftView:
        async with session.begin():
            draft, outcome, context = await self._own(session, actor_id, draft_id)
            return await self._view(session, draft, outcome, context)

    async def update(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        draft_id: UUID,
        payload: AppealDraftUpdate,
    ) -> AppealDraftView:
        async with session.begin():
            draft, outcome, context = await self._own(session, actor_id, draft_id, lock=True)
            if payload.version != draft.version:
                # Конфликт не затирает ввод: клиент получает свежую версию.
                raise StaleDraftVersion("Обновите черновик и повторите правку")
            draft.text = payload.text
            draft.version += 1
            await session.flush()
            # `updated_at` пересчитывает сервер, поэтому значение перечитывается
            # явно: неявная догрузка в асинхронной сессии запрещена.
            await session.refresh(draft)
            return await self._view(session, draft, outcome, context)

    async def mark_filed(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        draft_id: UUID,
        payload: AppealFiledMark,
    ) -> AppealDraftView:
        async with session.begin():
            draft, outcome, context = await self._own(session, actor_id, draft_id, lock=True)
            # Отметка жителя, а не подтверждение внешней регистрации. Повтор
            # не создаёт второго события и не меняет первую отметку.
            if draft.filed_at is None:
                draft.filed_at = datetime.now(UTC)
                draft.filed_reference = payload.reference
                await session.flush()
                await session.refresh(draft)
            return await self._view(session, draft, outcome, context)

    # ----------------------------------------------------------------- сборка

    async def _outcome(
        self,
        session: AsyncSession,
        context: OperationContext,
        payload: AppealDraftCreate,
    ) -> RouteOutcome:
        if payload.route_outcome_id is not None:
            outcome = await session.get(RouteOutcome, payload.route_outcome_id)
        elif payload.report_id is not None:
            outcome = await session.scalar(
                select(RouteOutcome).where(RouteOutcome.report_id == payload.report_id)
            )
        else:
            raise ResourceNotFound("Resource was not found")
        if outcome is None or outcome.house_id != context.house_id:
            raise ResourceNotFound("Resource was not found")
        return outcome

    async def _own(
        self,
        session: AsyncSession,
        actor_id: UUID,
        draft_id: UUID,
        *,
        lock: bool = False,
    ) -> tuple[AppealDraft, RouteOutcome, OperationContext]:
        """Чужой черновик неотличим от отсутствующего: всегда 404.

        Порядок блокировок тот же, что во всём продукте: authority → дом →
        строка. Поэтому до разрешения доступа читается только принадлежность
        черновика, а строка блокируется уже после взятия домовых блокировок.
        """
        draft = await session.scalar(select(AppealDraft).where(AppealDraft.id == draft_id))
        if draft is None or draft.author_id != actor_id:
            raise ResourceNotFound("Resource was not found")
        context = await self.memberships.require_house(
            session, user_id=actor_id, house_id=draft.house_id, for_write=lock
        )
        if lock:
            draft = await session.scalar(
                select(AppealDraft).where(AppealDraft.id == draft_id).with_for_update()
            )
            if draft is None or draft.author_id != actor_id or draft.house_id != context.house_id:
                raise ResourceNotFound("Resource was not found")
        outcome = await session.get(RouteOutcome, draft.route_outcome_id)
        if outcome is None or outcome.house_id != context.house_id:
            raise ResourceNotFound("Resource was not found")
        return draft, outcome, context

    async def _house_context(
        self, session: AsyncSession, house_id: UUID
    ) -> tuple[HouseRoutingContext, str]:
        house = await self.routing.house_context(session, house_id)
        address = await session.scalar(select(House.address).where(House.id == house_id))
        return house, address or ""

    async def _sources(
        self, session: AsyncSession, outcome: RouteOutcome
    ) -> tuple[str, str | None]:
        """Исходные слова жителя и проверенная переформулировка, если она есть."""
        original = ""
        clean: str | None = None
        if outcome.intake_event_id is not None:
            intake = await session.get(ExplicitIntake, outcome.intake_event_id)
            if intake is not None:
                original, clean = intake.text, intake.clean_description
        if not original and outcome.report_id is not None:
            report = await session.get(Report, outcome.report_id)
            if report is not None:
                original = report.description
        if not original and outcome.submitted_text:
            # Внешний маршрут из формы: записи приёма нет и заявки нет, поэтому
            # слова жителя приходят из самого исхода. Без них черновик
            # обращения остался бы без описания проблемы.
            original = outcome.submitted_text
        return original, clean

    async def _located(self, session: AsyncSession, outcome: RouteOutcome) -> Incident | None:
        if outcome.report_id is None:
            return None
        report = await session.get(Report, outcome.report_id)
        if report is None:
            return None
        return await session.get(Incident, report.incident_id)

    async def _compose(
        self, session: AsyncSession, outcome: RouteOutcome, context: OperationContext
    ) -> tuple[str, bool]:
        house, address = await self._house_context(session, outcome.house_id)
        organization, channel = self.routing.directory_entry(
            house,
            organization_id=outcome.organization_id,
            channel_id=outcome.channel_id,
        )
        original, clean = await self._sources(session, outcome)
        incident = await self._located(session, outcome)
        blocks: list[str] = []
        if organization:
            blocks.append(f"{_RECIPIENT_LABEL}: {organization}")
        if channel is not None:
            entry = channel.url or channel.entry_hint
            label = f"{_CHANNEL_LABEL}: {channel.label}"
            blocks.append(f"{label} ({entry})" if entry else label)
        blocks.append(f"{PROBLEM_HEADING}\n{clean or original}".rstrip())
        facts: list[str] = []
        if address:
            facts.append(f"{_ADDRESS_LABEL}: {address}")
        if incident is not None:
            if incident.location_entrance:
                facts.append(f"{_ENTRANCE_LABEL}: {incident.location_entrance}")
            if incident.location_floor:
                facts.append(f"{_FLOOR_LABEL}: {incident.location_floor}")
            if incident.observed_since:
                facts.append(f"{_SINCE_LABEL}: {incident.observed_since}")
        if facts:
            blocks.append("\n".join(facts))
        if channel is not None and channel.facts:
            lines = [
                f"— {fact.text} ({_SOURCE_PREFIX}{fact.source_title})" for fact in channel.facts
            ]
            blocks.append(CHANNEL_FACTS_HEADING + "\n" + "\n".join(lines))
        if clean:
            blocks.append(AI_NOTE)
        blocks.append(SELF_FILING_NOTE)
        return "\n\n".join(blocks), clean is not None

    # ------------------------------------------------------------------ чтение

    async def _view(
        self,
        session: AsyncSession,
        draft: AppealDraft,
        outcome: RouteOutcome,
        context: OperationContext,
    ) -> AppealDraftView:
        house, _ = await self._house_context(session, outcome.house_id)
        organization, channel = self.routing.directory_entry(
            house,
            organization_id=outcome.organization_id,
            channel_id=outcome.channel_id,
        )
        return AppealDraftView(
            id=draft.id,
            house_id=draft.house_id,
            route_outcome_id=draft.route_outcome_id,
            text=draft.text,
            version=draft.version,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
            ai_assisted=draft.ai_assisted,
            organization_name=organization,
            channel=channel,
            filed_at=draft.filed_at,
            filed_reference=draft.filed_reference,
            provenance=_provenance(draft),
            allowed_actions=_actions(draft, channel),
        )


def _provenance(draft: AppealDraft) -> Provenance:
    """Отметка подачи — утверждение жителя, не подтверждение системы."""
    if draft.filed_at is not None:
        return Provenance(
            origin="user_reported",
            recorded_at=draft.filed_at,
            note="Житель отметил подачу; внешней системой не подтверждено.",
        )
    return Provenance(
        origin="product_derived",
        recorded_at=draft.created_at,
        note="Текст собран ДомСигналом из проверенного справочника и слов жителя.",
    )


def _actions(draft: AppealDraft, channel: RouteChannel | None) -> list[ActionDescriptor]:
    url = channel.url if channel else None
    return [
        ActionDescriptor(code="edit_draft", enabled=draft.filed_at is None, reason=None)
        if draft.filed_at is None
        else ActionDescriptor(
            code="edit_draft", enabled=False, reason="Вы уже отметили подачу этого обращения."
        ),
        ActionDescriptor(code="copy_draft", enabled=True, reason=None),
        ActionDescriptor(
            code="open_official_channel",
            enabled=bool(url),
            reason=None
            if url
            else "Точная ссылка входа ещё не заполнена в справочнике."
            if channel is not None
            else "Проверенного канала для этого маршрута пока нет.",
        ),
        ActionDescriptor(
            code="mark_filed",
            enabled=draft.filed_at is None,
            reason=None if draft.filed_at is None else "Подача уже отмечена.",
        ),
    ]
