from fastapi import APIRouter

from domsignal.api.dependencies import ContainerDep, CurrentUserDep, DbDep
from domsignal.contracts.capabilities import CapabilityFlags
from domsignal.contracts.identity import MeResponse

router = APIRouter(prefix="/api/v1", tags=["identity"])


@router.get("/me", response_model=MeResponse)
async def me(current_user: CurrentUserDep, session: DbDep, container: ContainerDep) -> MeResponse:
    return await container.membership_service.me(
        session,
        user_id=current_user.id,
        capabilities=CapabilityFlags(
            test_auth=container.settings.test_session_enabled,
            ai_analysis=container.ai_analysis_enabled,
            routes=container.routes_enabled,
            appeals=container.appeals_enabled,
            passive_capture=container.settings.passive_capture_enabled,
        ),
    )
