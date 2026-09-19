from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from domsignal.contracts.common import FieldError, Problem
from domsignal.services.errors import ServiceError


class InvitationLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                re.sub(r"/admin/invite/[^ ?]+", "/admin/invite/[redacted]", arg)
                if isinstance(arg, str)
                else arg
                for arg in record.args
            )
        return True


logging.getLogger("uvicorn.access").addFilter(InvitationLogFilter())


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Correlation IDs are server generated; never echo arbitrary client/auth text.
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith(("/api/", "/admin", "/platform-admin", "/company")):
            response.headers["Cache-Control"] = "no-store"
        if request.url.path.startswith(("/admin", "/platform-admin", "/company")):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
                "base-uri 'self'; form-action 'self'"
            )
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
        problem = Problem(
            type=f"https://domsignal.local/problems/{exc.code}",
            title=exc.title,
            status=exc.status,
            detail=exc.detail,
            code=exc.code,
            trace_id=_request_id(request),
            retryable=getattr(exc, "retryable", False),
        )
        return _problem_response(problem)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        problem = Problem(
            type="https://domsignal.local/problems/validation_error",
            title="Request validation failed",
            status=422,
            detail="One or more request fields are invalid",
            code="validation_error",
            trace_id=_request_id(request),
            retryable=False,
            field_errors=[
                FieldError(
                    field=(
                        "request"
                        if item["type"] == "extra_forbidden"
                        else ".".join(str(part) for part in item["loc"])
                    ),
                    code=item["type"],
                    message="Invalid value",
                )
                for item in exc.errors()
            ],
        )
        return _problem_response(problem)

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        del exc
        problem = Problem(
            type="https://domsignal.local/problems/internal_error",
            title="Internal server error",
            status=500,
            detail="The request could not be completed",
            code="internal_error",
            trace_id=_request_id(request),
            retryable=True,
        )
        return _problem_response(problem)

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return _problem_response(
            Problem(
                type="about:blank",
                title="Request could not be completed",
                status=exc.status_code,
                code=f"http_{exc.status_code}",
                detail="The requested resource or method is unavailable",
                retryable=exc.status_code in {408, 429} or exc.status_code >= 500,
                trace_id=_request_id(request),
            )
        )


def _problem_response(problem: Problem) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
        headers={"X-Request-ID": problem.trace_id},
    )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")
