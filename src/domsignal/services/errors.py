from __future__ import annotations

from datetime import datetime
from typing import Any


class ServiceError(Exception):
    status = 400
    code = "service_error"
    title = "Request could not be completed"

    def __init__(self, detail: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.context = context


class AuthenticationRequired(ServiceError):
    status = 401
    code = "authentication_required"
    title = "Authentication required"


class AccessDenied(ServiceError):
    status = 403
    code = "house_access_denied"
    title = "Access denied"


class ResourceNotFound(ServiceError):
    status = 404
    code = "resource_not_found"
    title = "Resource not found"


class FeatureUnavailable(ServiceError):
    status = 503
    code = "feature_unavailable"
    title = "Feature unavailable"


class IdempotencyConflict(ServiceError):
    status = 409
    code = "idempotency_conflict"
    title = "Idempotency key conflict"


class InvalidInitData(ServiceError):
    status = 401
    code = "invalid_init_data"
    title = "Invalid MAX initialization data"


class RescheduleJob(Exception):  # noqa: N818 - это сигнал воркеру, а не ошибка
    """Задача переносит сама себя на более позднее время, не расходуя попытку.

    Тик окна ждёт тишины, очистка буфера повторяется по расписанию: вместо
    новой задачи на каждый шаг воркер возвращает ту же задачу в очередь.
    """

    def __init__(self, until: datetime) -> None:
        super().__init__("reschedule")
        self.until = until
