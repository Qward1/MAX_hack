"""Дашборды платформы и УК (D2): только агрегаты событий и данных БД.

Ни одно поле не несёт текста жителей, цитат, имён авторов или MAX id.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from domsignal.contracts.common import ContractModel
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
