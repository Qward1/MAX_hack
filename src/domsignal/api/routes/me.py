import logging
from uuid import UUID

from fastapi import APIRouter

from domsignal.api.dependencies import ContainerDep, CurrentUserDep, DbDep
from domsignal.contracts.capabilities import CapabilityFlags
from domsignal.contracts.identity import MeResponse, OpenHouse, OpenHouseList

router = APIRouter(prefix="/api/v1", tags=["identity"])
logger = logging.getLogger(__name__)


@router.get("/me", response_model=MeResponse)
async def me(current_user: CurrentUserDep, session: DbDep, container: ContainerDep) -> MeResponse:
    """Профиль и дома. Перед списком — проверка участия в домовых чатах.

    Проверка не чаще раза в 15 минут на пару «пользователь, чат» и только
    когда членство отсутствует или истекло. Её сбой списка не ломает.
    """
    try:
        await container.resident_access.refresh(current_user.id)
    except Exception as exc:  # noqa: BLE001 - список домов не зависит от MAX
        logger.warning("resident_refresh_failed", extra={"error_type": type(exc).__name__})
    return await container.membership_service.me(
        session,
        user_id=current_user.id,
        capabilities=CapabilityFlags(
            test_auth=container.settings.test_session_enabled,
            ai_analysis=container.ai_analysis_enabled,
            routes=container.routes_enabled,
            appeals=container.appeals_enabled,
            passive_capture=container.settings.passive_capture_enabled,
            passive_ai_analysis=container.passive_ai_analysis_enabled,
        ),
    )


@router.get("/open-houses", response_model=OpenHouseList)
async def open_houses(
    current_user: CurrentUserDep, session: DbDep, container: ContainerDep
) -> OpenHouseList:
    """Дома с открытым доступом: их может выбрать любой вошедший через MAX."""
    async with session.begin():
        items = await container.resident_access.open_houses(session, user_id=current_user.id)
    return OpenHouseList(items=items)


@router.post("/open-houses/{house_id}/join", response_model=OpenHouse)
async def join_open_house(
    house_id: UUID, current_user: CurrentUserDep, session: DbDep, container: ContainerDep
) -> OpenHouse:
    """Выбрать открытый дом. Закрытый и несуществующий неотличимы (404)."""
    async with session.begin():
        await container.resident_access.join_open_house(
            session, user_id=current_user.id, house_id=house_id
        )
        house = next(
            item
            for item in await container.resident_access.open_houses(
                session, user_id=current_user.id
            )
            if item.id == house_id
        )
    return house
