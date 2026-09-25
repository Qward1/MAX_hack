"""Дашборды платформы и УК (D2): агрегаты событий и данных БД.

Правила:
* только счётчики и длительности — ни текста жителей, ни цитат, ни авторов;
* сутки считаются по московскому времени (Казань и Москва — UTC+3), границы
  периода вычисляет PostgreSQL, а не часовой пояс процесса;
* область УК — управления этой УК (`management_id`), а не адрес дома: заявки
  прежней УК того же дома в её обзор не попадают; оператор видит только
  назначенные ему дома.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.community import PollResults
from domsignal.contracts.dashboards import (
    CategoryCount,
    CompanyDashboard,
    CompanyDay,
    DayActivity,
    DeliveryTotals,
    Funnel,
    HouseStats,
    ModelCompany,
    ModelDay,
    ModelUsage,
    PeriodDays,
    PlatformCompanyRow,
    PlatformDashboard,
    PlatformTotals,
)
from domsignal.db.models import (
    Broadcast,
    ChatBinding,
    ChatQuotaRequest,
    CompanyOnboardingRequest,
    House,
    HouseAssignment,
    HouseManagement,
    ManagementCompany,
    Poll,
)
from domsignal.services.broadcasts import poll_closed, tally
from domsignal.services.chat_quota import quota_state
from domsignal.services.onboarding import OPEN, current_management, require_company

TIMEZONE = "Europe/Moscow"
CATEGORY_LABELS = {
    "elevator": "Лифт",
    "water": "Вода",
    "lighting": "Освещение",
    "waste": "Отходы",
    "other": "Другое",
}

_PERIOD = text(
    """
    SELECT d::date AS day
    FROM generate_series(
        date_trunc('day', now() AT TIME ZONE :tz) - (:days - 1) * interval '1 day',
        date_trunc('day', now() AT TIME ZONE :tz),
        interval '1 day'
    ) AS d
    ORDER BY d
    """
)
_START = text(
    "SELECT (date_trunc('day', now() AT TIME ZONE :tz) - (:days - 1) * interval '1 day') "
    "AT TIME ZONE :tz"
)


async def period(db: AsyncSession, days: int) -> tuple[list[date], datetime]:
    params = {"tz": TIMEZONE, "days": days}
    day_list = [row.day for row in await db.execute(_PERIOD, params)]
    start = cast(datetime, await db.scalar(_START, params))
    return day_list, start


def _count_map(rows: Any) -> dict[Any, int]:
    return {row[0]: int(row[1] or 0) for row in rows}


class DashboardService:
    def __init__(self, daily_call_budget: int) -> None:
        self.daily_call_budget = daily_call_budget

    # --- платформа ----------------------------------------------------------------

    async def platform(self, db: AsyncSession, days: PeriodDays) -> PlatformDashboard:
        day_list, start = await period(db, days)
        params = {"tz": TIMEZONE, "start": start}
        return PlatformDashboard(
            period_days=days,
            generated_at=datetime.now(UTC),
            timezone=TIMEZONE,
            totals=await self._totals(db),
            companies=await self._companies(db),
            funnel=await self._funnel(db),
            activity=await self._activity(db, day_list, params),
            model=await self._model(db, day_list, params),
            delivery=await self._delivery(db, params),
        )

    async def _totals(self, db: AsyncSession) -> PlatformTotals:
        statuses = _count_map(
            await db.execute(
                select(ManagementCompany.status, func.count()).group_by(ManagementCompany.status)
            )
        )
        current = select(HouseManagement.house_id).where(*current_management())
        return PlatformTotals(
            companies_active=statuses.get("active", 0),
            companies_suspended=statuses.get("suspended", 0),
            applications_pending=await db.scalar(
                select(func.count())
                .select_from(CompanyOnboardingRequest)
                .where(CompanyOnboardingRequest.status.in_(OPEN))
            )
            or 0,
            quota_requests_pending=await db.scalar(
                select(func.count())
                .select_from(ChatQuotaRequest)
                .where(ChatQuotaRequest.status == "pending")
            )
            or 0,
            chats_active=await db.scalar(
                select(func.count()).select_from(ChatBinding).where(ChatBinding.status == "active")
            )
            or 0,
            chats_total=await db.scalar(select(func.count(func.distinct(ChatBinding.max_chat_id))))
            or 0,
            houses=await db.scalar(
                select(func.count(func.distinct(HouseManagement.house_id))).where(
                    *current_management()
                )
            )
            or 0,
            open_houses=await db.scalar(
                select(func.count())
                .select_from(House)
                .where(House.open_resident_access.is_(True), House.id.in_(current))
            )
            or 0,
        )

    async def _companies(self, db: AsyncSession) -> list[PlatformCompanyRow]:
        companies = list(
            await db.scalars(select(ManagementCompany).order_by(ManagementCompany.name).limit(200))
        )
        houses = _count_map(
            await db.execute(
                select(HouseManagement.tenant_id, func.count())
                .where(*current_management())
                .group_by(HouseManagement.tenant_id)
            )
        )
        chats = _count_map(
            await db.execute(
                select(HouseManagement.tenant_id, func.count())
                .select_from(ChatBinding)
                .join(HouseManagement, HouseManagement.id == ChatBinding.management_id)
                .where(ChatBinding.status == "active")
                .group_by(HouseManagement.tenant_id)
            )
        )
        pending = _count_map(
            await db.execute(
                select(ChatQuotaRequest.company_id, func.count())
                .where(ChatQuotaRequest.status == "pending")
                .group_by(ChatQuotaRequest.company_id)
            )
        )
        return [
            PlatformCompanyRow(
                company_id=c.id,
                name=c.name,
                status=c.status,
                quota=(await quota_state(db, c.id)).view(),
                houses=houses.get(c.id, 0),
                chats_active=chats.get(c.id, 0),
                pending_quota_requests=pending.get(c.id, 0),
            )
            for c in companies
        ]

    async def _funnel(self, db: AsyncSession) -> Funnel:
        row = (
            await db.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM company_onboarding_requests) AS applications,
                      (SELECT count(*) FROM company_onboarding_requests
                         WHERE status = 'approved') AS approved,
                      (SELECT count(DISTINCT r.company_id)
                         FROM company_onboarding_requests r
                         JOIN house_managements m ON m.tenant_id = r.company_id
                         JOIN chat_bindings b ON b.management_id = m.id
                         WHERE b.activated_at IS NOT NULL) AS first_chat,
                      (SELECT count(DISTINCT r.company_id)
                         FROM company_onboarding_requests r
                         JOIN house_managements m ON m.tenant_id = r.company_id
                         JOIN tickets t ON t.management_id = m.id) AS first_ticket
                    """
                )
            )
        ).one()
        return Funnel(
            applications=row.applications,
            approved=row.approved,
            first_chat=row.first_chat,
            first_ticket=row.first_ticket,
        )

    async def _activity(
        self, db: AsyncSession, day_list: list[date], params: dict[str, Any]
    ) -> list[DayActivity]:
        windows = {
            row.day: (int(row.windows), int(row.lines))
            for row in await db.execute(
                text(
                    "SELECT (first_line_at AT TIME ZONE :tz)::date AS day, count(*) AS windows, "
                    "coalesce(sum(line_count), 0) AS lines FROM conversation_windows "
                    "WHERE first_line_at >= :start GROUP BY 1"
                ),
                params,
            )
        }
        signals: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in await db.execute(
            text(
                "SELECT (created_at AT TIME ZONE :tz)::date AS day, strength, disposition, "
                "count(*) AS n FROM signals WHERE created_at >= :start GROUP BY 1, 2, 3"
            ),
            params,
        ):
            key = "audit" if row.disposition == "audit_pool" else row.strength
            signals[row.day][key] += int(row.n)
        created = _count_map(
            await db.execute(
                text(
                    "SELECT (created_at AT TIME ZONE :tz)::date, count(*) FROM tickets "
                    "WHERE created_at >= :start GROUP BY 1"
                ),
                params,
            )
        )
        closed = _count_map(
            await db.execute(
                text(
                    "SELECT (created_at AT TIME ZONE :tz)::date, count(DISTINCT ticket_id) "
                    "FROM ticket_events WHERE to_status = 'closed' "
                    "AND from_status IS DISTINCT FROM 'closed' AND created_at >= :start "
                    "GROUP BY 1"
                ),
                params,
            )
        )
        return [
            DayActivity(
                day=day,
                lines=windows.get(day, (0, 0))[1],
                windows=windows.get(day, (0, 0))[0],
                signals_critical=signals[day]["critical"],
                signals_strong=signals[day]["strong"],
                signals_medium=signals[day]["medium"],
                signals_weak=signals[day]["weak"],
                signals_audit=signals[day]["audit"] + signals[day]["filtered"],
                tickets_created=created.get(day, 0),
                tickets_closed=closed.get(day, 0),
            )
            for day in day_list
        ]

    _CALLS = """
        WITH calls AS (
          SELECT w.house_id, coalesce(w.completed_at, w.created_at) AS at,
                 (w.analysis ->> 'cost_rub')::numeric AS cost
          FROM conversation_windows w
          WHERE w.analysis ->> 'provider_called' = 'true'
            AND coalesce(w.completed_at, w.created_at) >= :start
          UNION ALL
          SELECT coalesce(i.house_id, b.house_id), i.created_at,
                 (i.analysis ->> 'cost_rub')::numeric
          FROM explicit_intakes i
          LEFT JOIN chat_bindings b ON b.id = i.chat_binding_id
          WHERE i.analysis ->> 'provider_called' = 'true' AND i.created_at >= :start
        )
    """

    async def _model(
        self, db: AsyncSession, day_list: list[date], params: dict[str, Any]
    ) -> ModelUsage:
        per_day = {
            row.day: (int(row.calls), float(row.cost), int(row.with_cost))
            for row in await db.execute(
                text(
                    self._CALLS + "SELECT (at AT TIME ZONE :tz)::date AS day, count(*) AS calls, "
                    "coalesce(sum(cost), 0) AS cost, count(cost) AS with_cost "
                    "FROM calls GROUP BY 1"
                ),
                params,
            )
        }
        budget = _count_map(
            await db.execute(
                text(
                    "SELECT day, calls FROM ai_call_budget WHERE scope_key = '' "
                    "AND day >= (:start AT TIME ZONE :tz)::date"
                ),
                params,
            )
        )
        by_company = [
            ModelCompany(
                company_id=row.company_id,
                company_name=row.company_name or "Дом не определён",
                calls=int(row.calls),
                cost_rub=round(float(row.cost), 4),
            )
            for row in await db.execute(
                text(
                    self._CALLS
                    + """
                    SELECT c.id AS company_id, c.name AS company_name, count(*) AS calls,
                           coalesce(sum(calls.cost), 0) AS cost
                    FROM calls
                    LEFT JOIN house_managements m
                      ON m.house_id = calls.house_id AND m.valid_from <= calls.at
                     AND (m.valid_to IS NULL OR m.valid_to > calls.at)
                    LEFT JOIN management_companies c ON c.id = m.tenant_id
                    GROUP BY c.id, c.name
                    ORDER BY count(*) DESC
                    """
                ),
                params,
            )
        ]
        days = [
            ModelDay(
                day=day,
                calls=per_day.get(day, (0, 0.0, 0))[0],
                cost_rub=round(per_day.get(day, (0, 0.0, 0))[1], 4),
                budget_used=budget.get(day, 0),
                budget_share=(
                    round(budget.get(day, 0) / self.daily_call_budget, 4)
                    if self.daily_call_budget
                    else None
                ),
            )
            for day in day_list
        ]
        return ModelUsage(
            calls=sum(d.calls for d in days),
            cost_rub=round(sum(d.cost_rub for d in days), 4),
            calls_with_cost=sum(v[2] for v in per_day.values()),
            daily_budget=self.daily_call_budget,
            days=days,
            by_company=by_company,
        )

    async def _delivery(self, db: AsyncSession, params: dict[str, Any]) -> DeliveryTotals:
        statuses = _count_map(
            await db.execute(
                text(
                    "SELECT status, count(*) FROM notification_deliveries "
                    "WHERE created_at >= :start GROUP BY status"
                ),
                params,
            )
        )
        return DeliveryTotals(
            accepted=statuses.get("accepted", 0),
            failed=statuses.get("failed", 0),
            unknown=statuses.get("unknown", 0),
            in_flight=sum(statuses.get(s, 0) for s in ("pending", "processing", "retry_wait")),
        )

    # --- УК ----------------------------------------------------------------------

    async def company_scope(
        self, db: AsyncSession, actor: UUID, company: UUID
    ) -> tuple[Literal["company", "assigned"], list[tuple[UUID, UUID, str]]]:
        """Дома обзора: все текущие у администратора, назначенные — у оператора."""
        member = await require_company(db, actor, company, admin=False)
        query = (
            select(HouseManagement.id, House.id, House.address)
            .join(House, House.id == HouseManagement.house_id)
            .where(HouseManagement.tenant_id == company, *current_management())
        )
        scope: Literal["company", "assigned"] = "company"
        if member.role != "company_admin":
            scope = "assigned"
            query = query.join(
                HouseAssignment, HouseAssignment.management_id == HouseManagement.id
            ).where(HouseAssignment.user_id == actor, HouseAssignment.status == "active")
        rows = (await db.execute(query.order_by(House.address))).all()
        return scope, [(r[0], r[1], r[2]) for r in rows]

    async def company(
        self, db: AsyncSession, actor: UUID, company: UUID, days: PeriodDays
    ) -> CompanyDashboard:
        scope, houses = await self.company_scope(db, actor, company)
        day_list, start = await period(db, days)
        managements = [m for m, _, _ in houses]
        params: dict[str, Any] = {"tz": TIMEZONE, "start": start, "ms": managements}
        by_management: dict[UUID, dict[str, Any]] = {m: defaultdict(int) for m in managements}
        activity: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        if managements:
            for row in await db.execute(
                text(
                    "SELECT b.management_id, (s.created_at AT TIME ZONE :tz)::date AS day, "
                    "count(*) AS n FROM signals s JOIN chat_bindings b ON b.id = s.chat_binding_id "
                    "WHERE b.management_id = ANY(:ms) AND s.disposition = 'inbox' "
                    "AND s.created_at >= :start GROUP BY 1, 2"
                ),
                params,
            ):
                by_management[row.management_id]["signals"] += int(row.n)
                activity[row.day]["signals"] += int(row.n)
            for row in await db.execute(
                text(
                    "SELECT management_id, count(*) AS n FROM tickets "
                    "WHERE management_id = ANY(:ms) AND status NOT IN ('closed', 'cancelled') "
                    "GROUP BY 1"
                ),
                params,
            ):
                by_management[row.management_id]["open"] = int(row.n)
            for row in await db.execute(
                text(
                    "SELECT management_id, (created_at AT TIME ZONE :tz)::date AS day, "
                    "count(*) AS n FROM tickets WHERE management_id = ANY(:ms) "
                    "AND created_at >= :start GROUP BY 1, 2"
                ),
                params,
            ):
                by_management[row.management_id]["created"] += int(row.n)
                activity[row.day]["created"] += int(row.n)
            for row in await db.execute(
                text(
                    "SELECT t.management_id, (e.created_at AT TIME ZONE :tz)::date AS day, "
                    "count(DISTINCT e.ticket_id) AS n FROM ticket_events e "
                    "JOIN tickets t ON t.id = e.ticket_id WHERE t.management_id = ANY(:ms) "
                    "AND e.to_status = 'closed' AND e.from_status IS DISTINCT FROM 'closed' "
                    "AND e.created_at >= :start GROUP BY 1, 2"
                ),
                params,
            ):
                by_management[row.management_id]["closed"] += int(row.n)
                activity[row.day]["closed"] += int(row.n)
            for row in await db.execute(
                text(
                    """
                    SELECT t.management_id,
                           percentile_cont(0.5) WITHIN GROUP (
                             ORDER BY extract(epoch FROM a.first_accept - t.created_at) / 60
                           ) AS median
                    FROM tickets t
                    JOIN (SELECT ticket_id, min(created_at) AS first_accept
                          FROM ticket_events WHERE kind = 'accepted' GROUP BY ticket_id) a
                      ON a.ticket_id = t.id
                    WHERE t.management_id = ANY(:ms) AND t.created_at >= :start
                    GROUP BY 1
                    """
                ),
                params,
            ):
                by_management[row.management_id]["median"] = (
                    round(float(row.median), 1) if row.median is not None else None
                )
            for row in await db.execute(
                text(
                    "SELECT t.management_id, e.kind, count(*) AS n FROM ticket_events e "
                    "JOIN tickets t ON t.id = e.ticket_id WHERE t.management_id = ANY(:ms) "
                    "AND e.kind IN ('result_confirmed', 'result_objected') "
                    "AND e.created_at >= :start GROUP BY 1, 2"
                ),
                params,
            ):
                key = "confirmed" if row.kind == "result_confirmed" else "returned"
                by_management[row.management_id][key] = int(row.n)
            categories: dict[UUID, list[CategoryCount]] = defaultdict(list)
            for row in await db.execute(
                text(
                    "SELECT t.management_id, i.category, count(*) AS n FROM tickets t "
                    "JOIN incidents i ON i.id = t.incident_id WHERE t.management_id = ANY(:ms) "
                    "AND t.created_at >= :start GROUP BY 1, 2 ORDER BY 1, 3 DESC, 2"
                ),
                params,
            ):
                if len(categories[row.management_id]) < 3:
                    categories[row.management_id].append(
                        CategoryCount(category=row.category, count=int(row.n))
                    )
            for management in managements:
                by_management[management]["categories"] = categories.get(management, [])
        return CompanyDashboard(
            period_days=days,
            generated_at=datetime.now(UTC),
            timezone=TIMEZONE,
            scope=scope,
            quota=(await quota_state(db, company)).view(),
            houses=[
                HouseStats(
                    house_id=house_id,
                    address=address,
                    signals=by_management[m]["signals"],
                    tickets_open=by_management[m]["open"],
                    tickets_created=by_management[m]["created"],
                    tickets_closed=by_management[m]["closed"],
                    median_accept_minutes=by_management[m].get("median"),
                    verification_confirmed=by_management[m]["confirmed"],
                    verification_returned=by_management[m]["returned"],
                    top_categories=by_management[m].get("categories", []),
                )
                for m, house_id, address in houses
            ],
            activity=[
                CompanyDay(
                    day=day,
                    signals=activity[day]["signals"],
                    tickets_created=activity[day]["created"],
                    tickets_closed=activity[day]["closed"],
                )
                for day in day_list
            ],
            polls=await self._polls(db, company),
        )

    @staticmethod
    async def _polls(db: AsyncSession, company: UUID) -> list[PollResults]:
        """Итоги пяти последних отправленных опросов УК."""
        rows = await db.scalars(
            select(Poll)
            .join(Broadcast, Broadcast.id == Poll.broadcast_id)
            .where(
                Broadcast.tenant_id == company,
                Broadcast.status == "sent",
                Broadcast.retracted_at.is_(None),
            )
            .order_by(Broadcast.sent_at.desc())
            .limit(5)
        )
        results = []
        for poll in rows:
            options, voters = await tally(db, poll)
            results.append(
                PollResults(
                    poll_id=poll.id,
                    question=poll.question,
                    multiple=poll.multiple,
                    closes_at=poll.closes_at,
                    closed=poll_closed(poll),
                    voters=voters,
                    options=options,
                )
            )
        return results


def csv_cell(value: object) -> object:
    """Текст, начинающийся с `= + - @`, Excel исполнил бы как формулу: экранируем."""
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + value
    return value


def company_csv(dashboard: CompanyDashboard) -> str:
    """Агрегаты обзора УК по домам. UTF-8 с BOM — Excel открывает кириллицу."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        [
            "Адрес",
            f"Сигналы за {dashboard.period_days} дн.",
            "Заявки открыто сейчас",
            "Заявки создано",
            "Заявки закрыто",
            "Медиана до принятия, мин",
            "Подтверждено жителями",
            "Возвращено в работу",
            "Частые категории",
        ]
    )
    for house in dashboard.houses:
        writer.writerow(
            [
                csv_cell(house.address),
                house.signals,
                house.tickets_open,
                house.tickets_created,
                house.tickets_closed,
                "" if house.median_accept_minutes is None else house.median_accept_minutes,
                house.verification_confirmed,
                house.verification_returned,
                ", ".join(
                    f"{CATEGORY_LABELS.get(c.category, c.category)} ({c.count})"
                    for c in house.top_categories
                ),
            ]
        )
    return "﻿" + buffer.getvalue()
