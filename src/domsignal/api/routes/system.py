from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from domsignal.api.dependencies import ContainerDep, DbDep
from domsignal.contracts.capabilities import CapabilitiesResponse, CapabilityFlags

router = APIRouter(tags=["system"])


@router.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", include_in_schema=False)
async def ready(session: DbDep) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.get("/version", include_in_schema=False)
async def version(container: ContainerDep) -> dict[str, str]:
    return {
        "version": "0.1.0",
        "commit": container.settings.build_commit,
        "region_pack": "demo-1",
    }


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
    )
