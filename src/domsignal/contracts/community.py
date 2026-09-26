"""Публичные контракты среза D3: жилищный навигатор и домовое сообщество.

Жителю отдаются только проекции: ни внутренних заметок, ни имён и контактов
сотрудников и соседей. Сведения УК подписаны «по данным УК» с датой, факты
справочника — источником и датой проверки; непроверенное не отдаётся.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from domsignal.contracts.common import ContractModel, PageMeta
from domsignal.contracts.onboarding import PHONE

HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_WEBSITE = re.compile(r"https?://[^\s/$.?#][^\s]*", re.IGNORECASE)

BroadcastKind = Literal["announcement", "mailing", "poll"]
BroadcastTopic = Literal["outage", "works", "meeting", "other"]
BroadcastStatus = Literal["draft", "scheduled", "sent", "cancelled"]
BroadcastChannel = Literal["chat", "dm", "feed", "staff"]
BroadcastOrigin = Literal["company", "platform", "council"]


def _phone(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    value = value.strip()
    if not PHONE.fullmatch(value) or sum(c.isdigit() for c in value) < 3:
        raise ValueError("Invalid phone syntax")
    return value


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


# ------------------------------------------------------------ настройки чата


class ChatSettingsChange(ContractModel):
    occurred_at: datetime
    actor_name: str | None
    summary: str


class ChatSettingsView(ContractModel):
    """Что бот может публиковать в чате по решению человека и тихие часы.

    Памятка безопасности и сообщение о чтении чата этими настройками не
    отключаются (BOT-VOICE-HUMAN-2026-09-27).
    """

    binding_id: UUID
    post_ticket_status: bool
    post_company_messages: bool
    post_polls: bool
    post_platform_messages: bool
    quiet_start: str
    quiet_end: str
    changed_at: datetime | None = None
    can_edit: bool = False
    history: list[ChatSettingsChange] = Field(default_factory=list)
    #: Подпись пояса дома чата для тихих часов: «МСК», «ВЛАД» (D4, аддитивно).
    timezone_label: str = "МСК"


class ChatSettingsUpdate(ContractModel):
    post_ticket_status: bool
    post_company_messages: bool
    post_polls: bool
    post_platform_messages: bool
    quiet_start: str = Field(pattern=HHMM)
    quiet_end: str = Field(pattern=HHMM)


# ----------------------------------------------------------- профиль УК


class CompanyProfileFields(ContractModel):
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=254)
    dispatcher_phone: str | None = Field(default=None, max_length=40)
    office_hours: str | None = Field(default=None, max_length=300)
    reception_hours: str | None = Field(default=None, max_length=300)
    website: str | None = Field(default=None, max_length=300)
    office_address: str | None = Field(default=None, max_length=500)


class CompanyProfileUpdate(CompanyProfileFields):
    @field_validator("phone", "dispatcher_phone")
    @classmethod
    def phone_syntax(cls, value: str | None) -> str | None:
        return _phone(value)

    @field_validator("email")
    @classmethod
    def email_syntax(cls, value: str | None) -> str | None:
        value = _text(value)
        if value and not _EMAIL.fullmatch(value):
            raise ValueError("Invalid email syntax")
        return value

    @field_validator("website")
    @classmethod
    def website_syntax(cls, value: str | None) -> str | None:
        value = _text(value)
        if value and not _WEBSITE.fullmatch(value):
            raise ValueError("Website must start with http:// or https://")
        return value

    @field_validator("office_hours", "reception_hours", "office_address")
    @classmethod
    def trimmed(cls, value: str | None) -> str | None:
        return _text(value)


class CompanyProfileView(CompanyProfileFields):
    company_id: UUID
    name: str
    updated_at: datetime | None = None
    can_edit: bool = False


class HouseFactsUpdate(ContractModel):
    entrance_count: int | None = Field(default=None, ge=1, le=100)
    floor_count: int | None = Field(default=None, ge=1, le=200)


class HouseFactsView(HouseFactsUpdate):
    house_id: UUID
    facts_updated_at: datetime | None = None


# -------------------------------------------------------------- «Мой дом»


class OverviewCompany(CompanyProfileFields):
    """Сведения УК для жителя. Подпись в интерфейсе — «по данным УК»."""

    name: str
    updated_at: datetime | None = None


class OverviewChat(ContractModel):
    connected: bool
    reading_enabled: bool


class VerifiedSource(ContractModel):
    """Происхождение факта справочника: только проверенные записи."""

    title: str
    url: str | None = None
    verified_at: str | None = None


class OverviewEmergency(ContractModel):
    title: str
    phone: str | None = None
    lines: list[str] = Field(default_factory=list)
    source: VerifiedSource


class OverviewChannel(ContractModel):
    id: str
    label: str
    channel_type: str
    url: str | None = None
    phone: str | None = None
    verification_status: Literal["verified"] = "verified"
    source: VerifiedSource


class OverviewStep(ContractModel):
    text: str
    #: `directory` — справочник с источником, `company` — по данным УК,
    #: `product` — что делает ДомСигнал.
    basis: Literal["directory", "company", "product"]
    phone: str | None = None
    source: VerifiedSource | None = None


class OverviewReference(ContractModel):
    """Где посмотреть тарифы и капремонт (D4): официальная страница, без цифр."""

    kind: Literal["tariffs", "capital_repair"]
    label: str
    url: str
    source: VerifiedSource


class HouseOverview(ContractModel):
    house_id: UUID
    name: str
    address: str
    entrance_count: int | None = None
    floor_count: int | None = None
    facts_updated_at: datetime | None = None
    company: OverviewCompany | None = None
    chat: OverviewChat
    emergency: list[OverviewEmergency] = Field(default_factory=list)
    channels: list[OverviewChannel] = Field(default_factory=list)
    accident_steps: list[OverviewStep] = Field(default_factory=list)
    reception_available: bool = False
    #: Официальные страницы тарифов и капремонта региона (D4); нет источника — пусто.
    reference_links: list[OverviewReference] = Field(default_factory=list)


# ------------------------------------------------------ выполненные работы


class CompletedWork(ContractModel):
    """Отчёт исполнителя и итог проверки жителями. Без имён и заметок."""

    attempt_id: UUID
    incident_id: UUID
    category: str
    category_title: str
    entrance: str | None = None
    public_description: str
    reported_at: datetime
    outcome: Literal["confirmed", "returned"]
    outcome_at: datetime | None = None


class CompletedWorkList(ContractModel):
    days: Literal[30, 90]
    items: list[CompletedWork]
    page: PageMeta


# ------------------------------------------------------- объявления и опросы


class PollOptionResult(ContractModel):
    id: UUID
    position: int
    label: str
    votes: int = Field(ge=0)
    share: float = Field(ge=0, le=1)


class PollView(ContractModel):
    """Опрос для жителя: только числа и доли, без имён голосовавших."""

    id: UUID
    broadcast_id: UUID
    question: str
    multiple: bool
    closes_at: datetime
    closed: bool
    voters: int = Field(ge=0)
    options: list[PollOptionResult]
    my_choice: list[UUID] = Field(default_factory=list)
    can_vote: bool = False
    reason: str | None = None
    sender: str
    disclaimer: str


class PollVote(ContractModel):
    option_ids: list[UUID] = Field(min_length=1, max_length=10)

    @field_validator("option_ids")
    @classmethod
    def distinct(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Options must be distinct")
        return value


class PollSummary(ContractModel):
    poll_id: UUID
    closes_at: datetime
    closed: bool
    voters: int = Field(ge=0)
    voted: bool = False


class AnnouncementItem(ContractModel):
    id: UUID
    kind: BroadcastKind
    topic: BroadcastTopic | None = None
    topic_label: str | None = None
    title: str
    body: str
    sender: str
    sent_at: datetime
    edited_at: datetime | None = None
    poll: PollSummary | None = None


class AnnouncementList(ContractModel):
    items: list[AnnouncementItem]
    page: PageMeta
    #: Житель отказался от рассылок в личные сообщения.
    broadcast_opt_out: bool = False


class ResidentPreferences(ContractModel):
    broadcast_opt_out: bool


# ------------------------------------------------------------- рассылки (кабинет)


class BroadcastAudience(ContractModel):
    """Кому. УК — только свои дома; платформа — УК и их домовые чаты."""

    mode: Literal["all", "houses", "filter", "companies", "region"] = "all"
    house_ids: list[UUID] = Field(default_factory=list, max_length=500)
    company_ids: list[UUID] = Field(default_factory=list, max_length=500)
    region_code: str | None = Field(default=None, max_length=20)
    municipality_code: str | None = Field(default=None, max_length=60)
    only_with_chat: bool = False
    only_open_access: bool = False


class PollDraft(ContractModel):
    question: str = Field(min_length=3, max_length=300)
    options: list[str] = Field(min_length=2, max_length=10)
    multiple: bool = False
    closes_at: datetime

    @field_validator("options")
    @classmethod
    def clean_options(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item or len(item) > 100 for item in cleaned):
            raise ValueError("Each option must have 1–100 characters")
        if len({item.lower() for item in cleaned}) != len(cleaned):
            raise ValueError("Options must be distinct")
        return cleaned


class BroadcastCreate(ContractModel):
    kind: BroadcastKind
    topic: BroadcastTopic | None = None
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(default="", max_length=3000)
    audience: BroadcastAudience = Field(default_factory=BroadcastAudience)
    channels: list[BroadcastChannel] = Field(min_length=1, max_length=4)
    poll: PollDraft | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if len(set(self.channels)) != len(self.channels):
            raise ValueError("Channels must be distinct")
        if (self.kind == "poll") != (self.poll is not None):
            raise ValueError("A poll needs its question and options")
        if self.kind == "announcement" and self.topic is None:
            raise ValueError("An announcement needs a topic")
        if self.kind != "poll" and not self.body.strip():
            raise ValueError("Body is required")
        return self


class BroadcastUpdate(BroadcastCreate):
    expected_version: int = Field(ge=1)


class BroadcastContentEdit(ContractModel):
    """Правка отправленного сообщения: пост в чате правится, не отправляется заново."""

    expected_version: int = Field(ge=1)
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(default="", max_length=3000)


class BroadcastConfirm(ContractModel):
    expected_version: int = Field(ge=1)
    #: Пусто — отправить сейчас.
    send_at: datetime | None = None
    #: «Только сервисные сообщения, реклама запрещена» — подтверждение автора.
    service_only: Literal[True]


class BroadcastCommand(ContractModel):
    expected_version: int = Field(ge=1)


class ChannelPreview(ContractModel):
    channel: BroadcastChannel
    targets: int = Field(ge=0)
    will_send: int = Field(ge=0)
    skipped: dict[str, int] = Field(default_factory=dict)


class BroadcastPreview(ContractModel):
    houses: int = Field(ge=0)
    companies: int = Field(ge=0)
    channels: list[ChannelPreview]


class ChannelStats(ContractModel):
    channel: BroadcastChannel
    total: int = 0
    accepted: int = 0
    failed: int = 0
    unknown: int = 0
    pending: int = 0
    deferred_quiet_hours: int = 0
    skipped: dict[str, int] = Field(default_factory=dict)


class PollResults(ContractModel):
    poll_id: UUID
    question: str
    multiple: bool
    closes_at: datetime
    closed: bool
    voters: int = Field(ge=0)
    options: list[PollOptionResult]


class BroadcastView(ContractModel):
    id: UUID
    origin: BroadcastOrigin
    company_id: UUID | None = None
    kind: BroadcastKind
    topic: BroadcastTopic | None = None
    title: str
    body: str
    audience: BroadcastAudience
    channels: list[BroadcastChannel]
    status: BroadcastStatus
    scheduled_at: datetime | None = None
    confirmed_at: datetime | None = None
    sent_at: datetime | None = None
    cancelled_at: datetime | None = None
    retracted_at: datetime | None = None
    edited_at: datetime | None = None
    created_at: datetime
    version: int
    author_name: str | None = None
    confirmed_by_name: str | None = None
    sender: str
    poll: PollResults | None = None
    houses: list[str] = Field(default_factory=list)
    stats: list[ChannelStats] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)


class BroadcastSummary(ContractModel):
    id: UUID
    kind: BroadcastKind
    title: str
    status: BroadcastStatus
    created_at: datetime
    scheduled_at: datetime | None = None
    sent_at: datetime | None = None
    retracted_at: datetime | None = None
    author_name: str | None = None


class BroadcastList(ContractModel):
    items: list[BroadcastSummary]
    page: PageMeta


class BroadcastHouseOption(ContractModel):
    """Дом, который сотрудник может выбрать в аудитории."""

    house_id: UUID
    address: str
    region_code: str | None = None
    municipality_code: str | None = None
    has_chat: bool = False
    open_access: bool = False


class PlatformNotice(ContractModel):
    id: UUID
    title: str
    body: str
    sent_at: datetime
    edited_at: datetime | None = None


class PlatformNoticeList(ContractModel):
    items: list[PlatformNotice]
    page: PageMeta


class StaffSettings(ContractModel):
    daily_digest_enabled: bool
    #: Бот может написать этому сотруднику: вход через MAX или начатый диалог.
    max_linked: bool


class StaffSettingsUpdate(ContractModel):
    daily_digest_enabled: bool


# -------------------------------------------------------------- «Мои обращения»


ActivityKind = Literal["route_card", "appeal_draft", "report", "joined"]


class ActivityItem(ContractModel):
    kind: ActivityKind
    id: UUID
    house_id: UUID
    house_address: str
    title: str
    status_label: str
    occurred_at: datetime
    incident_id: UUID | None = None
    route_outcome_id: UUID | None = None
    appeal_draft_id: UUID | None = None
    #: Отметка жителя «Я отправил» — не регистрация во внешней системе.
    filed_at: datetime | None = None
    ticket_number: str | None = None


class ActivityList(ContractModel):
    items: list[ActivityItem]
    page: PageMeta


# ------------------------------------------------------------ запись на приём


class ReceptionSlotCreate(ContractModel):
    starts_at: datetime
    duration_minutes: int = Field(default=30, ge=5, le=240)
    capacity: int = Field(ge=1, le=50)
    place: str | None = Field(default=None, max_length=500)


class ReceptionBookingStaffView(ContractModel):
    id: UUID
    topic: str
    house_address: str
    resident_name: str
    status: Literal["booked", "cancelled"]
    created_at: datetime


class ReceptionSlotView(ContractModel):
    id: UUID
    starts_at: datetime
    duration_minutes: int
    capacity: int
    booked: int = Field(ge=0)
    place: str | None = None
    status: Literal["open", "cancelled"]
    bookings: list[ReceptionBookingStaffView] = Field(default_factory=list)


class ResidentSlotView(ContractModel):
    id: UUID
    starts_at: datetime
    duration_minutes: int
    place: str | None = None
    free: int = Field(ge=0)
    my_booking_id: UUID | None = None


class ResidentBookingView(ContractModel):
    id: UUID
    slot_id: UUID
    starts_at: datetime
    duration_minutes: int
    place: str | None = None
    topic: str
    status: Literal["booked", "cancelled"]


class ReceptionOverview(ContractModel):
    company_name: str
    slots: list[ResidentSlotView]
    bookings: list[ResidentBookingView]


class ReceptionBookingCreate(ContractModel):
    slot_id: UUID
    topic: str = Field(min_length=3, max_length=300)


# ------------------------------------------------ совет дома и предложения (D4)

ProposalStatus = Literal["new", "converted"]


class ProposalCreate(ContractModel):
    """«Предложить вопрос»: тема для обсуждения или опроса."""

    text: str = Field(min_length=3, max_length=1000)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("Text must have at least 3 characters")
        return cleaned


class ProposalView(ContractModel):
    id: UUID
    house_id: UUID
    text: str
    #: `new` — ждёт совета или УК; `converted` — вынесено на опрос.
    status: ProposalStatus
    created_at: datetime
    #: Предложение текущего пользователя (автор видит статус своего).
    mine: bool = False
    #: Опрос, в который превратили предложение (ссылка `p_…` не нужна: экран опроса по id).
    poll_id: UUID | None = None


class CouncilView(ContractModel):
    """Совет дома глазами жителя: член ли он совета и предложения.

    Член совета видит все предложения дома, остальные — только свои.
    """

    house_id: UUID
    is_member: bool
    proposals: list[ProposalView] = Field(default_factory=list)


class CouncilAnnouncementCreate(ContractModel):
    """Объявление от совета дома: в чат дома (по настройкам чата) и в ленту."""

    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=1, max_length=3000)
    #: «Только сервисные сообщения, реклама запрещена» — подтверждение автора.
    service_only: Literal[True]


class CouncilPollCreate(ContractModel):
    """Опрос от совета дома; `proposal_id` — предложение, которое он закрывает."""

    poll: PollDraft
    proposal_id: UUID | None = None
    service_only: Literal[True]


class CouncilPublished(ContractModel):
    broadcast_id: UUID
    status: BroadcastStatus
    poll_id: UUID | None = None


class CouncilMemberView(ContractModel):
    user_id: UUID
    display_name: str
    since: datetime


class CouncilResident(ContractModel):
    """Житель дома — участник домового чата — для выбора в совет."""

    user_id: UUID
    display_name: str
    is_member: bool


class CouncilAdminView(ContractModel):
    """Совет дома в кабинете УК: члены, жители для выбора (только администратору), предложения."""

    house_id: UUID
    can_manage: bool
    members: list[CouncilMemberView] = Field(default_factory=list)
    residents: list[CouncilResident] = Field(default_factory=list)
    proposals: list[ProposalView] = Field(default_factory=list)


class CouncilMemberChange(ContractModel):
    user_id: UUID
    reason: str = Field(min_length=3, max_length=500)


class CouncilMemberRevoke(ContractModel):
    reason: str = Field(min_length=3, max_length=500)

