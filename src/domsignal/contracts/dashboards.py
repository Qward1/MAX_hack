"""Дашборды платформы и УК (D2): только агрегаты событий и данных БД.

Ни одно поле не несёт текста жителей, цитат, имён авторов или MAX id.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from domsignal.contracts.common import ContractModel
from domsignal.contracts.community import PollResults
from domsignal.contracts.quota import ChatQuotaView

PeriodDays = Literal[7, 14, 30]


class DayActivity(ContractModel):
    day: date
    #: Реплики, попавшие в окна разбора (сумма длины окон, открытых в этот день).
    lines: int
    windows: int
    signals_critical: int
    signals_strong: int
    signals_medium: int
    signals_weak: int
    #: Отсеяно в Audit Pool (оператору не показывается).
    signals_audit: int
    tickets_created: int
    tickets_closed: int


class ModelDay(ContractModel):
    day: date
    #: Вызовы модели по учёту разбора (окна чатов и явные сообщения).
    calls: int
    cost_rub: float
    #: Списано с дневного бюджета вызовов (счётчик PostgreSQL).
    budget_used: int
    #: Доля дневного бюджета; `null` — бюджет не задан.
    budget_share: float | None


class ModelCompany(ContractModel):
    company_id: UUID | None
    company_name: str
    calls: int
    cost_rub: float


class ModelUsage(ContractModel):
    calls: int
    cost_rub: float
    #: Вызовов, по которым провайдер сообщил стоимость.
    calls_with_cost: int
    daily_budget: int
    days: list[ModelDay]
    by_company: list[ModelCompany]


class DeliveryTotals(ContractModel):
    accepted: int
    failed: int
    unknown: int
    #: Ещё в работе: ожидает отправки, отправляется или ждёт повтора.
    in_flight: int


class Funnel(ContractModel):
    """Воронка подключения за всё время: заявка → одобрение → первый чат → первая заявка."""

    applications: int
    approved: int
    first_chat: int
    first_ticket: int


class PlatformCompanyRow(ContractModel):
    company_id: UUID
    name: str
    status: str
    quota: ChatQuotaView
    houses: int
    chats_active: int
    pending_quota_requests: int


class PlatformTotals(ContractModel):
    companies_active: int
    companies_suspended: int
    applications_pending: int
    quota_requests_pending: int
    chats_active: int
    #: Чаты, у которых когда-либо была привязка.
    chats_total: int
    houses: int
    #: Дома с открытым доступом жителей (D1).
    open_houses: int
    #: Текущие дома без профиля маршрутизации: «регион не задан» (D4).
    houses_without_region: int = 0


class QueuePoolHealth(ContractModel):
    pool: Literal["operational", "ai"]
    #: Ожидают и уже пора выполнять.
    due: int
    #: Отложены на будущее (периодические задачи, тихие часы, повторы).
    scheduled: int
    #: Взяты воркером в работу.
    leased: int
    #: Сколько секунд ждёт самая старая задача из тех, что пора выполнять.
    oldest_due_seconds: float | None


class WindowFallbacks(ContractModel):
    """Окна чатов, разобранные за 24 часа."""

    total: int
    by_model: int
    #: Правилами из-за перегрузки или бюджета: сторож (модель не успела),
    #: исчерпанный бюджет, переполненный семафор или открытый предохранитель.
    by_rules_overload_or_budget: int
    watchdog: int
    budget: int
    provider_overload: int
    share_rules_overload_or_budget: float | None


class ModelBudgetToday(ContractModel):
    """Дневной бюджет вызовов модели (сутки UTC, счётчик PostgreSQL)."""

    used: int
    limit: int
    share: float | None


class QueueHealth(ContractModel):
    """Здоровье очереди задач (D5): только агрегаты."""

    generated_at: datetime
    pools: list[QueuePoolHealth]
    #: Доставки в MAX, которые пора отправить или поправить.
    deliveries_due: int
    windows_24h: WindowFallbacks
    model_budget_today: ModelBudgetToday


class DirectoryPackReadiness(ContractModel):
    """Готовность пакета справочника (D5, аудит Р-3)."""

    pack: str
    name: str
    version: str
    timezone: str | None
    verified: int
    needs_verification: int
    #: Проверенные записи старше порога актуальности (180 дней).
    stale: int
    #: Каналы, недоступные в этом регионе (`unavailable_regions`).
    unavailable_channels: list[str]


class PlatformDashboard(ContractModel):
    period_days: PeriodDays
    generated_at: datetime
    timezone: str
    totals: PlatformTotals
    companies: list[PlatformCompanyRow]
    funnel: Funnel
    activity: list[DayActivity]
    model: ModelUsage
    delivery: DeliveryTotals
    #: D5: очередь задач и доля окон, ушедших правилам.
    queue: QueueHealth | None = None
    #: D5: готовность справочника по пакетам.
    directory: list[DirectoryPackReadiness] = Field(default_factory=list)


class CategoryCount(ContractModel):
    category: str
    count: int


class HouseStats(ContractModel):
    house_id: UUID
    address: str
    #: Сигналы очереди оператора за период (без Audit Pool).
    signals: int
    #: Открытые заявки сейчас.
    tickets_open: int
    tickets_created: int
    tickets_closed: int
    #: Медиана минут от создания заявки до её принятия (заявки периода).
    median_accept_minutes: float | None
    #: Итоги проверки жителями за период.
    verification_confirmed: int
    verification_returned: int
    top_categories: list[CategoryCount]


class CompanyDay(ContractModel):
    day: date
    signals: int
    tickets_created: int
    tickets_closed: int


class CompanyDashboard(ContractModel):
    period_days: PeriodDays
    generated_at: datetime
    timezone: str
    #: `company` — все дома УК (администратор); `assigned` — дома оператора.
    scope: Literal["company", "assigned"]
    quota: ChatQuotaView
    houses: list[HouseStats]
    activity: list[CompanyDay]
    #: Итоги последних опросов УК (D3): только числа и доли.
    polls: list[PollResults] = Field(default_factory=list)
