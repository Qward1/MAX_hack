import hmac
from typing import Any

from fastapi import APIRouter, Header
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from domsignal.api.dependencies import ContainerDep, DbDep
from domsignal.contracts.capabilities import CapabilitiesResponse, CapabilityFlags
from domsignal.services import showcase
from domsignal.services.errors import ResourceNotFound
from domsignal.services.privacy import PRIVACY_PATH, render_privacy_page

router = APIRouter(tags=["system"])


@router.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", include_in_schema=False)
async def ready(session: DbDep) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.get("/version", include_in_schema=False)
async def version(container: ContainerDep) -> dict[str, Any]:
    """Сборка и версии загруженных слоёв справочника (D4): `{"_federal": "2", …}`.

    Справочник не загрузился — `region_packs` пуст, маршруты `unknown`.
    """
    directory = container.routing.directory
    return {
        "version": "0.1.0",
        "commit": container.settings.build_commit,
        "region_packs": directory.versions() if directory is not None else {},
    }


@router.get(PRIVACY_PATH, include_in_schema=False, response_class=HTMLResponse)
async def privacy(container: ContainerDep) -> HTMLResponse:
    """Публичная страница «Как ДомСигнал обращается с данными» (D4)."""
    base = (container.settings.public_base_url or "").rstrip("/")
    return HTMLResponse(
        render_privacy_page(contact=container.settings.privacy_contact, site_url=f"{base}/site")
    )


@router.get("/api/v1/capabilities", response_model=CapabilitiesResponse)
async def capabilities(container: ContainerDep) -> Any:
    return CapabilitiesResponse(
        environment=container.settings.app_env.value,
        features=CapabilityFlags(
            test_auth=container.settings.test_session_enabled,
            ai_analysis=container.ai_analysis_enabled,
            routes=container.routes_enabled,
            appeals=container.appeals_enabled,
            passive_capture=container.settings.passive_capture_enabled,
            passive_ai_analysis=container.passive_ai_analysis_enabled,
        ),
        bot_url=(
            f"https://max.ru/{container.settings.max_bot_username}"
            if container.settings.max_bot_username
            else None
        ),
    )


@router.get("/api/v1/showcase/health", include_in_schema=False)
async def showcase_health(
    session: DbDep,
    container: ContainerDep,
    token: str | None = Header(default=None, alias="X-Showcase-Check-Token"),
) -> dict[str, Any]:
    """Самопроверка витрины жюри (F1 §5.5): только да/нет по инвариантам, без данных.

    Доступ — по отдельному токену `SHOWCASE_CHECK_TOKEN`; без него адрес не существует.
    """
    expected = container.settings.showcase_check_token
    if not expected or not token or not hmac.compare_digest(token.encode(), expected.encode()):
        raise ResourceNotFound("Not found")
    checks = await showcase.health(session, container.chat_connections.provider)
    return {"ok": all(checks.values()), "checks": checks}
