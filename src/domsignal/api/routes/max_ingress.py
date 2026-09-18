import hmac
import json

from fastapi import APIRouter, Request, status

from domsignal.api.dependencies import ContainerDep, CurrentUserDep, DbDep
from domsignal.bot.max_updates import InvalidMaxUpdate, parse_update
from domsignal.contracts.jobs import InboundAccepted, NormalizedInboundEvent
from domsignal.services.errors import AuthenticationRequired, FeatureUnavailable
from domsignal.settings import MaxTransportMode

router = APIRouter(prefix="/max", tags=["max"])


@router.post("/webhook", response_model=InboundAccepted)
async def webhook(request: Request, session: DbDep, container: ContainerDep) -> InboundAccepted:
    settings = container.settings
    if settings.max_transport != MaxTransportMode.WEBHOOK or not settings.max_webhook_secret:
        raise FeatureUnavailable("MAX webhook is disabled")
    supplied = request.headers.getlist("X-Max-Bot-Api-Secret")
    if len(supplied) != 1 or not hmac.compare_digest(
        supplied[0].encode(),
        settings.max_webhook_secret.encode(),
    ):
        raise AuthenticationRequired("Invalid webhook credentials")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 65536:
            raise InvalidMaxUpdate("MAX update is too large")
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Expected an object")
    except ValueError:
        raise InvalidMaxUpdate("Invalid MAX update") from None
    return await container.max_webhook.accept(session, parse_update(payload))


@router.post("/replay", response_model=InboundAccepted, status_code=status.HTTP_202_ACCEPTED)
async def replay(
    event: NormalizedInboundEvent,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> InboundAccepted:
    if not container.settings.replay_enabled:
        raise FeatureUnavailable("Normalized replay is disabled in production")
    return await container.inbound_service.accept(session, event=event, actor_id=current_user.id)
