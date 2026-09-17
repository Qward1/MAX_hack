from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from domsignal.contracts.common import Problem
from domsignal.services.errors import ServiceError


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id[:100]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
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
            request_id=_request_id(request),
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
            request_id=_request_id(request),
            errors=jsonable_encoder(exc.errors()),
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
            request_id=_request_id(request),
        )
        return _problem_response(problem)


def _problem_response(problem: Problem) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(mode="json", exclude_none=True),
        media_type="application/problem+json",
    )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")
