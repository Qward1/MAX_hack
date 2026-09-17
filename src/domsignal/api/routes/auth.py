from fastapi import APIRouter

from domsignal.api.dependencies import ContainerDep, DbDep
from domsignal.api.init_data import validate_init_data
from domsignal.contracts.identity import MaxSessionRequest, SessionResponse, TestSessionRequest
from domsignal.services.errors import FeatureUnavailable

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/test-session", response_model=SessionResponse)
async def test_session(
    payload: TestSessionRequest, session: DbDep, container: ContainerDep
) -> SessionResponse:
    if not container.settings.test_session_enabled:
        raise FeatureUnavailable("Local test sessions are disabled in this environment")
    return await container.session_service.issue_test_session(session, alias=payload.actor)


@router.post("/max", response_model=SessionResponse)
async def max_session(
    payload: MaxSessionRequest, session: DbDep, container: ContainerDep
) -> SessionResponse:
    bot_token = container.settings.max_bot_token
    if not bot_token:
        raise FeatureUnavailable("MAX authentication is not configured")
    user = validate_init_data(
        payload.init_data,
        bot_token=bot_token,
        max_age_seconds=container.settings.init_data_max_age_seconds,
    )
    return await container.session_service.issue_max_session(
        session,
        max_user_id=str(user.id),
        display_name=user.display_name,
    )
