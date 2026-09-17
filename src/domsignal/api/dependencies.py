from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.bootstrap import Container
from domsignal.services.errors import AuthenticationRequired
from domsignal.services.sessions import AuthenticatedUser

bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


async def get_db(
    container: Annotated[Container, Depends(get_container)],
) -> AsyncIterator[AsyncSession]:
    async with container.session_factory() as session:
        yield session


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    container: Annotated[Container, Depends(get_container)],
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationRequired("A bearer session is required")
    async with container.session_factory() as auth_session:
        return await container.session_service.authenticate(
            auth_session, token=credentials.credentials
        )


ContainerDep = Annotated[Container, Depends(get_container)]
DbDep = Annotated[AsyncSession, Depends(get_db)]
CurrentUserDep = Annotated[AuthenticatedUser, Depends(get_current_user)]
