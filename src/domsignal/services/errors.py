from __future__ import annotations

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
