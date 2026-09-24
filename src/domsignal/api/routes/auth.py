import logging

from fastapi import APIRouter

from domsignal.api.dependencies import ContainerDep, DbDep
from domsignal.api.init_data import start_param_of, validate_init_data
from domsignal.contracts.identity import MaxSessionRequest, SessionResponse, TestSessionRequest
from domsignal.db.repositories.access import AccessRepository
from domsignal.services.errors import FeatureUnavailable

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = logging.getLogger(__name__)


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
    issued = await container.session_service.issue_max_session(
        session,
        max_user_id=str(user.id),
        display_name=user.display_name,
    )
    # Житель = участник домового чата: при входе проверяется участие в чатах-
    # кандидатах. Ссылка `c_…` из кнопки чата только сужает, какой чат
    # проверить. Сбой проверки не мешает входу и нового доступа не даёт.
    async with container.session_factory() as lookup:
        known = await AccessRepository(lookup).user_by_max_id(str(user.id))
    if known is not None:
        try:
            await container.resident_access.refresh(
                known.id, launch_ref=start_param_of(payload.init_data)
            )
        except Exception as exc:  # noqa: BLE001 - вход не зависит от проверки членства
            logger.warning("resident_refresh_failed", extra={"error_type": type(exc).__name__})
    return issued
