from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from domsignal.api.errors import RequestIdMiddleware, install_error_handlers
from domsignal.api.routes import (
    administration,
    appeals,
    auth,
    chat_connections,
    employee_auth,
    incidents,
    max_ingress,
    me,
    system,
    tickets,
)
from domsignal.bootstrap import build_container
from domsignal.contracts.common import Problem
from domsignal.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    container = build_container(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        yield
        await container.engine.dispose()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        openapi_version="3.1.0",
        lifespan=lifespan,
        responses={
            code: {"model": Problem} for code in (401, 403, 404, 405, 409, 422, 429, 500, 503)
        },
    )
    app.state.container = container
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )
    install_error_handlers(app)
    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(employee_auth.router)
    app.include_router(administration.router)
    app.include_router(me.router)
    app.include_router(incidents.router)
    app.include_router(appeals.router)
    app.include_router(max_ingress.router)
    app.include_router(chat_connections.router)
    app.include_router(tickets.router)

    def problem_openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            for path in schema["paths"].values():
                for operation in path.values():
                    for code, response in operation.get("responses", {}).items():
                        response.setdefault("headers", {})["X-Request-ID"] = {
                            "description": "Server generated correlation ID",
                            "schema": {"type": "string"},
                        }
                        if code.isdigit() and int(code) >= 400:
                            response["content"] = {
                                "application/problem+json": {
                                    "schema": {"$ref": "#/components/schemas/Problem"}
                                }
                            }
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = problem_openapi  # type: ignore[method-assign]

    static_dir = Path(resolved_settings.static_dir)
    if static_dir.is_dir():

        @app.get("/admin/{path:path}", include_in_schema=False)
        async def admin_login() -> FileResponse:
            return FileResponse(static_dir / "admin" / "index.html")

        @app.get("/platform-admin/{path:path}", include_in_schema=False)
        async def platform_shell() -> FileResponse:
            return FileResponse(static_dir / "platform-admin" / "index.html")

        @app.get("/company/apply", include_in_schema=False)
        async def company_apply() -> FileResponse:
            return FileResponse(static_dir / "company" / "index.html")

        app.mount("/", StaticFiles(directory=static_dir, html=True), name="miniapp")
    return app


app = create_app()
