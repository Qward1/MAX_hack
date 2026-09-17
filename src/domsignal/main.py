from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from domsignal.api.errors import RequestIdMiddleware, install_error_handlers
from domsignal.api.routes import auth, incidents, max_ingress, me, system
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
            401: {"model": Problem, "description": "Authentication failed"},
            403: {"model": Problem, "description": "House access denied"},
            409: {"model": Problem, "description": "Idempotency conflict"},
            422: {"model": Problem, "description": "Request validation failed"},
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
    app.include_router(me.router)
    app.include_router(incidents.router)
    app.include_router(max_ingress.router)

    static_dir = Path(resolved_settings.static_dir)
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="miniapp")
    return app


app = create_app()
