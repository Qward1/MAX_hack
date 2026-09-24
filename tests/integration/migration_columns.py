"""Столбцы, добавленные срезами P3b, P4, D1 и D2 к уже существующим таблицам.

Проверки миграций сравнивают строки до и после обновления до head. Новые
столбцы перечислены здесь явно, чтобы сравнение оставалось осмысленным: оно
доказывает, что миграция аддитивна и ни одно существующее значение не
переписано, а не просто игнорирует расхождение.
"""

from __future__ import annotations

P3B_COLUMNS: dict[str, tuple[str, ...]] = {
    "incidents": (
        "location_entrance",
        "location_floor",
        "location_label",
        "observed_since",
    ),
    "reports": ("analysis",),
    "notification_deliveries": (
        "route_outcome_id",
        "signal_id",
        "chat_binding_id",
        # D1: ответ личного бота.
        "reply_event_id",
    ),
    # P4: пассивное чтение чата.
    "chat_bindings": ("passive_capture_enabled",),
    "route_outcomes": ("signal_id",),
    # D1: открытый доступ к дому, диалог с ботом, членство по чату, личка.
    "houses": ("open_resident_access", "open_access_changed_at", "open_access_changed_by"),
    "users": ("max_dialog_at", "max_dialog_stopped_at", "group_ack_at"),
    "resident_memberships": (
        "chat_binding_id",
        "binding_version",
        "checked_at",
        "ended_at",
        "end_reason",
    ),
    "explicit_intakes": ("channel", "house_id", "user_id", "hold_until", "pending_analysis"),
    # D2: открытая регистрация сотрудников, заявка УК со ссылкой статуса,
    # источник приглашения.
    "management_companies": (
        "open_registration_enabled",
        "open_registration_code_hash",
        "open_registration_changed_at",
        "open_registration_changed_by",
    ),
    "company_onboarding_requests": (
        "requested_chat_count",
        "house_addresses",
        "contact_position",
        "status_token_hash",
        "admin_invite_generation",
        "notify_code_hash",
        "notify_user_id",
    ),
    "employee_invitations": ("source",),
}


#: Значение, которое миграция ставит существующим строкам. Столбцы, которых
#: здесь нет, обязаны остаться пустыми. Чтение чата у прежних привязок
#: выключено — это и есть значение по умолчанию.
ADDED_DEFAULTS: dict[str, object] = {
    "passive_capture_enabled": False,
    # D1: открытого доступа у прежних домов нет; прежний приём — `/report` группы.
    "open_resident_access": False,
    "channel": "group_report",
    # D2: регистрация по ссылке у прежних УК закрыта; прежние приглашения —
    # обычные; ссылка «Создать аккаунт» ещё не выпускалась.
    "open_registration_enabled": False,
    "source": "invitation",
    "admin_invite_generation": 0,
}


def added_default(column: str) -> object:
    """Что миграция обязана оставить в добавленном столбце прежней строки."""
    return ADDED_DEFAULTS.get(column)


def added_by_p3b(table: str) -> tuple[str, ...]:
    """Столбцы, которых в этой таблице до среза P3b не было (включая P4)."""
    return P3B_COLUMNS.get(table, ())


def without_added_columns(table: str, *extra: str) -> str:
    """SQL-выражение строки таблицы без столбцов, добавленных после базы сравнения.

    Вычитание отсутствующего ключа в `jsonb` — не ошибка, поэтому одно и то же
    выражение работает и до обновления, и после.
    """
    columns = (*added_by_p3b(table), *extra)
    if not columns:
        return "row_to_json(t)"
    return "to_jsonb(t)" + "".join(f" - '{name}'" for name in columns)
