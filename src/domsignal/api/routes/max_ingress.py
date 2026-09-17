from fastapi import APIRouter, status

from domsignal.api.dependencies import ContainerDep, CurrentUserDep, DbDep
from domsignal.contracts.jobs import InboundAccepted, NormalizedInboundEvent
from domsignal.services.errors import FeatureUnavailable

router = APIRouter(prefix="/max", tags=["max"])


@router.post("/webhook", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
async def webhook_not_configured() -> None:
    raise FeatureUnavailable(
        "Live MAX webhook payload handling is not implemented in FND-01; use explicit test replay"
    )


@router.post("/replay", response_model=InboundAccepted, status_code=status.HTTP_202_ACCEPTED)
async def replay(
    event: NormalizedInboundEvent,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> InboundAccepted:
    del current_user
    if not container.settings.replay_enabled:
        raise FeatureUnavailable("Normalized replay is disabled in production")
    return await container.inbound_service.accept(session, event=event)
