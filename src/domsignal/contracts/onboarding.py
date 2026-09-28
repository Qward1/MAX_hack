from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from domsignal.contracts.chat_connections import ConnectionView
from domsignal.contracts.common import ContractModel
from domsignal.contracts.quota import ChatQuotaView
from domsignal.contracts.routing import TerritoryPolicy

Role = Literal["operator", "company_admin"]
ReviewStatus = Literal[
    "submitted", "under_review", "needs_info", "approved", "rejected", "cancelled"
]
Surface = Literal[
    "overview",
    "tickets",
    "signals",
    "assigned_houses",
    "houses",
    "staff",
    "chat_connections",
    "organization",
    # D3: объявления, рассылки и опросы; уведомления платформы и сводка; приём.
    "mailings",
    "notices",
    "reception",
]
Plain = Annotated[str, Field(min_length=1, max_length=2000)]
#: Телефон заявки УК: цифры с обычными разделителями и необязательный добавочный.
PHONE = re.compile(r"\+?[0-9() .\-–]{5,30}(?:\s*(?:доб\.?|ext\.?|#)\s*[0-9]{1,6})?", re.IGNORECASE)


class PlainInput(ContractModel):
    @field_validator("*", mode="before")
    @classmethod
    def plain_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if any(c in value for c in "<>") or any(
                ord(c) < 32 and c not in "\n\r\t" for c in value
            ):
                raise ValueError("Plain text required")
        return value


def plain_line(value: str) -> str:
    value = value.strip()
    if any(c in value for c in "<>") or any(ord(c) < 32 for c in value):
        raise ValueError("Plain text required")
    return value


class CompanyApplicationCreate(PlainInput):
    legal_name: str = Field(min_length=2, max_length=300)
    short_name: str = Field(min_length=2, max_length=200)
    inn: str = Field(pattern=r"^(?:[0-9]{10}|[0-9]{12})$")
    contact_name: str = Field(min_length=2, max_length=200)
    #: Должность контактного лица (D2), необязательно.
    contact_position: str | None = Field(default=None, max_length=200)
    contact_email: str | None = Field(default=None, max_length=254)
    contact_phone: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=2000)
    #: Сколько домовых чатов УК хочет подключить (D2). Итоговую квоту задаёт платформа.
    requested_chat_count: int = Field(ge=1, le=1000)
    #: Необязательный список адресов домов — подсказка платформе, не доступ.
    house_addresses: list[Annotated[str, Field(min_length=5, max_length=500)]] = Field(
        default_factory=list, max_length=50
    )

    @field_validator("house_addresses", mode="before")
    @classmethod
    def plain_addresses(cls, value: object) -> object:
        if isinstance(value, list):
            cleaned = [plain_line(item) if isinstance(item, str) else item for item in value]
            return [item for item in cleaned if item != ""]
        return value

    # Формат почты и телефона проверяется на своём поле: ошибка 422 называет
    # поле, и форма показывает, что именно исправить.
    @field_validator("contact_email")
    @classmethod
    def email_syntax(cls, value: str | None) -> str | None:
        if not value:
            return None
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Invalid email syntax")
        return value

    @field_validator("contact_phone")
    @classmethod
    def phone_syntax(cls, value: str | None) -> str | None:
        if not value:
            return None
        if not PHONE.fullmatch(value) or sum(c.isdigit() for c in value) < 5:
            raise ValueError("Invalid phone syntax")
        return value

    @model_validator(mode="after")
    def contact(self) -> Self:
        if not self.contact_email and not self.contact_phone:
            raise ValueError("Phone or email required")
        return self


class ApplicationReceived(ContractModel):
    received: Literal[True] = True
    message: str = (
        "Заявка принята. Сохраните ссылку на страницу статуса: по ней вы увидите решение, "
        "ответите на вопросы и создадите аккаунт администратора."
    )
    #: Секретная ссылка на страницу статуса (D2). Показывается один раз.
    status_url: str | None = None


class ReviewDecision(PlainInput):
    reason: Plain


class ApplicationDecision(ReviewDecision):
    """Решение по заявке УК. При одобрении платформа задаёт квоту чатов (D2).

    `chat_quota` не задан и `unlimited` ложно — квота равна запрошенному числу
    чатов (у заявок до D2 без числа — без ограничения).
    """

    chat_quota: int | None = Field(default=None, ge=0, le=10000)
    unlimited: bool = False


class CompanyContext(ContractModel):
    company_id: UUID
    name: str
    surfaces: list[Surface]
    #: Роль в этой УК (D2, аддитивно): интерфейс прячет действия администратора.
    role: Role | None = None
    #: F1 §5.5: проверочный аккаунт в демо-УК — разрушающие действия над витриной
    #: закрыты (API отвечает 403 `showcase_protected`), интерфейс их выключает.
    protected: bool = False


class AdminBootstrap(ContractModel):
    user_id: UUID
    display_name: str
    companies: list[CompanyContext]


class PlatformBootstrap(ContractModel):
    display_name: str
    surfaces: list[str]
    #: F1 §5.5: проверочный аккаунт платформы — действия над витриной закрыты.
    reviewer: bool = False


class AuditView(ContractModel):
    event: str
    occurred_at: datetime
    actor_id: str | None = None
    object_id: str | None = None
    reason: str | None = None


class ApplicationMessageView(ContractModel):
    author: Literal["platform", "applicant"]
    text: str
    created_at: datetime


class ApplicationView(ContractModel):
    id: UUID
    legal_name: str
    short_name: str
    inn: str
    contact_name: str
    contact_email: str | None
    contact_phone: str | None
    comment: str | None
    status: ReviewStatus
    submitted_at: datetime
    reviewed_at: datetime | None
    decision_reason: str | None
    company_id: UUID | None
    history: list[AuditView] = Field(default_factory=list)
    # D2, аддитивно.
    contact_position: str | None = None
    requested_chat_count: int | None = None
    house_addresses: list[str] | None = None
    #: У заявителя есть ссылка статуса: приглашение передавать вручную не нужно.
    status_link_issued: bool = False
    #: Совпадение ИНН: такая УК уже создана или есть другая открытая заявка.
    inn_conflict: Literal["company_exists", "open_application"] | None = None
    messages: list[ApplicationMessageView] = Field(default_factory=list)
    #: Квота чатов, выданная при одобрении; `null` — без ограничения или не одобрено.
    granted_chat_quota: int | None = None


class ApplicationStatusToken(ContractModel):
    token: str = Field(min_length=32, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class ApplicationReply(ApplicationStatusToken):
    text: str = Field(min_length=1, max_length=2000, pattern=r"^[^<>]+$")


class ApplicationStatusView(ContractModel):
    """Страница статуса заявки по секретной ссылке: только своя заявка."""

    status: ReviewStatus
    short_name: str
    submitted_at: datetime
    requested_chat_count: int | None
    house_addresses: list[str]
    messages: list[ApplicationMessageView]
    #: Ответить на вопросы платформы можно, пока заявка в статусе «Нужны уточнения».
    can_reply: bool
    #: Основание одобрения или отказа.
    decision_reason: str | None
    granted_chat_quota: int | None
    quota_unlimited: bool
    #: `create` — можно создать аккаунт администратора; `active` — он уже создан.
    admin_account: Literal["unavailable", "create", "active"]
    #: Бот уже пишет в MAX о смене статуса (кто-то открыл его по коду заявки).
    max_notifications: bool = False


class NotifyLink(ContractModel):
    """Ссылка на бота с одноразовым кодом `ca_…` — «Получать уведомления в MAX»."""

    bot_url: str


class AdminInvitationLink(ContractModel):
    invitation_url: str


class InvitationCreate(ContractModel):
    organization_role: Role


class InvitationView(ContractModel):
    id: UUID
    company_id: UUID
    organization_role: Role
    status: Literal["pending", "claimed", "accepted", "expired", "revoked"]
    expires_at: datetime
    created_at: datetime
    claimed_by_user_id: UUID | None
    invitation_url: str | None = None


class CompanyApproved(ContractModel):
    application: ApplicationView
    #: `null` — у заявителя есть ссылка статуса, аккаунт он создаёт сам (D2).
    invitation: InvitationView | None = None


class InvitationToken(ContractModel):
    token: str = Field(min_length=32, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class InvitationRegister(InvitationToken):
    display_name: str = Field(min_length=2, max_length=200, pattern=r"^[^<>]+$")
    login_name: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=12, max_length=1024)


class InvitationPreview(ContractModel):
    company_name: str
    organization_role: Role
    expires_at: datetime


class MembershipView(ContractModel):
    user_id: UUID
    display_name: str
    role: Role
    status: str
    #: Сотрудник зарегистрировался по открытой ссылке УК (D2).
    open_registration: bool = False


class AssignmentView(ContractModel):
    management_id: UUID
    role: Literal["operator", "responsible"]


class StaffDetail(MembershipView):
    assignments: list[AssignmentView]


class AssignmentChange(ContractModel):
    management_id: UUID
    role: Literal["operator", "responsible"] | None


class HouseRequestCreate(PlainInput):
    requested_address: str = Field(min_length=5, max_length=500)
    requested_valid_from: AwareDatetime
    basis_text: Plain


class HouseRequestView(ContractModel):
    id: UUID
    company_id: UUID
    requested_address: str
    requested_valid_from: datetime
    basis_text: str
    candidate_house_id: UUID | None
    status: ReviewStatus
    reviewed_at: datetime | None
    decision_reason: str | None
    created_at: datetime
    management_id: UUID | None
    history: list[AuditView] = Field(default_factory=list)
    #: D5: заявка создана из адресов одобренной заявки УК.
    source_application_id: UUID | None = None
    #: F-10: название УК — на экране название, а не идентификатор.
    company_name: str | None = None


#: D5: сколько адресов принимает одна пачка (вставка списка, одобрение).
HOUSE_BATCH_LIMIT = 200


class HouseBatchCreate(PlainInput):
    """Список адресов от администратора УК (D5, аудит Р-1): каждый — заявка на дом.

    Квота остаётся на чатах: заявка на дом слот не расходует.
    """

    addresses: list[Annotated[str, Field(min_length=5, max_length=500)]] = Field(
        min_length=1, max_length=HOUSE_BATCH_LIMIT
    )
    requested_valid_from: AwareDatetime
    basis_text: Plain

    @field_validator("addresses", mode="before")
    @classmethod
    def plain_addresses(cls, value: object) -> object:
        if isinstance(value, list):
            cleaned = [plain_line(item) if isinstance(item, str) else item for item in value]
            return [item for item in cleaned if item != ""]
        return value


HouseBatchSubmitOutcome = Literal["created", "duplicate", "already_open", "already_managed"]


class HouseBatchSubmitItem(ContractModel):
    address: str
    outcome: HouseBatchSubmitOutcome
    request_id: UUID | None = None


class HouseBatchSubmitted(ContractModel):
    created: int
    skipped: int
    items: list[HouseBatchSubmitItem]


HouseBatchApproveOutcome = Literal[
    "approved", "already_approved", "conflict", "not_found", "failed"
]


class HouseBatchDecision(ContractModel):
    request_id: UUID
    outcome: HouseBatchApproveOutcome
    message: str | None = None
    house_id: UUID | None = None
    management_id: UUID | None = None


class HouseBatchApproved(ContractModel):
    approved: int
    already_approved: int
    failed: int
    items: list[HouseBatchDecision]


class HouseRegionChoice(ContractModel):
    """Регион дома из загруженного справочника (D4, В-1).

    Регион обязателен: без него сервис отвечает 422 с объяснением. Варианты —
    `GET /api/v1/platform/region-packs`.
    """

    region_code: str | None = Field(default=None, max_length=20)
    municipality_code: str | None = Field(default=None, max_length=60)
    territory_policy: TerritoryPolicy = "mixed"


class HouseApproval(ReviewDecision, HouseRegionChoice):
    resolution: Literal["existing", "new"]
    house_id: UUID | None = None
    valid_from: AwareDatetime
    confirm_backdate: bool = False

    @model_validator(mode="after")
    def explicit_identity(self) -> Self:
        if (self.resolution == "existing") != (self.house_id is not None):
            raise ValueError("Choose an explicit existing house or create a new house")
        return self


class HouseBatchApproval(ReviewDecision, HouseRegionChoice):
    """Одобрить выбранные заявки на дома одним действием с одним регионом (D5).

    Дом выбирается как при одиночном одобрении, но без вопросов: найденный по
    адресу при подаче или существующий с тем же адресом — иначе новый.
    """

    request_ids: list[UUID] = Field(min_length=1, max_length=HOUSE_BATCH_LIMIT)
    valid_from: AwareDatetime
    confirm_backdate: bool = False


class ChatSummary(ContractModel):
    id: UUID
    title: str | None
    max_chat_id: str
    status: str
    scope_type: str
    scope_value: str | None
    suspension_reason: str | None
    # Чтение чата включено у привязки. `None` — поверхность этого не сообщает.
    passive_capture_enabled: bool | None = None
    #: U-01: когда чат подключён.
    activated_at: datetime | None = None


class CompanyHouseView(ContractModel):
    house_id: UUID
    management_id: UUID
    address: str
    name: str
    valid_from: datetime
    valid_to: datetime | None
    operator_count: int
    responsible_count: int
    open_ticket_count: int
    bindings: list[ChatSummary]
    connection_requests: list[ConnectionView]
    warning: str | None = None
    #: Открытый доступ к дому (OPEN-HOUSE-ACCESS-2026-09-25, аддитивно).
    open_resident_access: bool = False
    open_access_changed_at: datetime | None = None
    #: Может ли текущий сотрудник подключать чаты этого дома (`chat.connect`, D2).
    can_connect_chats: bool = False
    #: Сведения о доме «по данным УК» (D3, аддитивно).
    entrance_count: int | None = None
    floor_count: int | None = None
    facts_updated_at: datetime | None = None


class OpenAccessChange(ContractModel):
    """Включить или выключить открытый доступ к дому.

    Включение требует явного подтверждения: «Любой пользователь MAX сможет
    выбрать этот дом, сообщать о проблемах и видеть доску дома».
    """

    enabled: bool
    confirm: bool = False

    @model_validator(mode="after")
    def confirmed(self) -> Self:
        if self.enabled and not self.confirm:
            raise ValueError("Включение открытого доступа требует подтверждения")
        return self


class OpenAccessView(ContractModel):
    house_id: UUID
    open_resident_access: bool
    open_access_changed_at: datetime | None
    #: Сколько действующих членств по открытому доступу завершено сейчас.
    ended_memberships: int = 0


class PlatformOpenHouseView(ContractModel):
    house_id: UUID
    address: str
    name: str
    company_id: UUID
    company_name: str
    open_access_changed_at: datetime | None
    #: Дом демо-УК (витрина для жюри, F1 §5.5).
    showcase: bool = False


class OpenAccessClose(ContractModel):
    reason: str = Field(min_length=3, max_length=500)


class CompanyView(ContractModel):
    id: UUID
    name: str
    legal_name: str | None
    inn: str | None
    status: str
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    house_count: int = 0
    employee_count: int = 0
    binding_problems: int = 0
    # D2, аддитивно.
    chat_quota: ChatQuotaView | None = None
    pending_quota_requests: int = 0
    open_registration_enabled: bool = False
    #: Демо-УК для жюри (F1 §5.5): проверочные аккаунты её не меняют.
    showcase: bool = False


class CompanyOverview(ContractModel):
    open_tickets: int
    unassigned_tickets: int
    verification_pending: int
    house_count: int
    active_employees: int
    binding_problems: int


class PlatformHouseView(ContractModel):
    id: UUID
    address: str
    name: str
    #: Профиль маршрутизации дома (D4). `None` — «регион не задан».
    region_code: str | None = None
    municipality_code: str | None = None
    territory_policy: TerritoryPolicy | None = None


class HouseRegionChange(ReviewDecision, HouseRegionChoice):
    """«Задать регион» дому без профиля — тот же сервис, что у CLI."""


class RegionMunicipality(ContractModel):
    code: str
    name: str


class RegionPackView(ContractModel):
    """Регион загруженного справочника — вариант выбора при одобрении дома."""

    region_code: str
    name: str
    timezone: str
    version: str
    municipalities: list[RegionMunicipality]


class PlatformBindingView(ChatSummary):
    house_id: UUID
    management_id: UUID
    company_id: UUID
    #: F1: адрес дома и название УК — вместо идентификаторов на экране.
    house_address: str | None = None
    company_name: str | None = None


class PlatformHealth(ContractModel):
    database: Literal["ready"]
    pending_jobs: int
    failed_jobs: int
    pending_deliveries: int


class CredentialResetCreate(ContractModel):
    """`password` — новый пароль, аутентификатор прежний; `password_mfa` — оба заново."""

    kind: Literal["password", "password_mfa"]


class CredentialResetIssued(ContractModel):
    kind: Literal["password", "password_mfa"]
    reset_url: str
    expires_at: datetime


class CredentialResetToken(ContractModel):
    token: str = Field(min_length=32, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class CredentialResetPreview(ContractModel):
    company_name: str
    login_name: str
    kind: Literal["password", "password_mfa"]
    expires_at: datetime


class CredentialResetComplete(CredentialResetToken):
    password: str = Field(min_length=12, max_length=1024)


class OpenRegistrationChange(PlainInput):
    enabled: bool
    reason: Plain


class OpenRegistrationEmployee(ContractModel):
    user_id: UUID
    display_name: str
    login_name: str | None
    status: str
    registered_at: datetime | None


class OpenRegistrationView(ContractModel):
    enabled: bool
    changed_at: datetime | None
    #: Публичная ссылка `/join/<код>` — только в ответе на включение.
    join_url: str | None = None
    employees: list[OpenRegistrationEmployee] = Field(default_factory=list)


class JoinCode(ContractModel):
    code: str = Field(min_length=20, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class JoinPreview(ContractModel):
    company_name: str


class JoinRegister(JoinCode):
    display_name: str = Field(min_length=2, max_length=200, pattern=r"^[^<>]+$")
    login_name: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=12, max_length=1024)


class CompanyDestination(ContractModel):
    company_id: UUID
    name: str
    role: Role


class EmployeeDestinations(ContractModel):
    """Куда вести сотрудника после единого входа `/login`."""

    platform: bool
    companies: list[CompanyDestination]
