"""Черновик обращения: собрать, прочитать, поправить, отметить подачу.

Житель отправляет обращение сам в официальном сервисе. Отметка подачи —
утверждение жителя, а не подтверждение внешней регистрации.
"""

from uuid import UUID

from fastapi import APIRouter, status

from domsignal.api.dependencies import ContainerDep, CurrentUserDep, DbDep
from domsignal.contracts.appeals import (
    AppealDraftCreate,
    AppealDraftUpdate,
    AppealDraftView,
    AppealFiledMark,
)

router = APIRouter(prefix="/api/v1", tags=["appeals"])


@router.post(
    "/appeal-drafts", response_model=AppealDraftView, status_code=status.HTTP_201_CREATED
)
async def create_draft(
    payload: AppealDraftCreate,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> AppealDraftView:
    return await container.appeal_drafts.create(
        session, actor_id=current_user.id, payload=payload
    )


@router.get("/appeal-drafts/{draft_id}", response_model=AppealDraftView)
async def read_draft(
    draft_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> AppealDraftView:
    return await container.appeal_drafts.detail(
        session, actor_id=current_user.id, draft_id=draft_id
    )


@router.patch("/appeal-drafts/{draft_id}", response_model=AppealDraftView)
async def update_draft(
    draft_id: UUID,
    payload: AppealDraftUpdate,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> AppealDraftView:
    return await container.appeal_drafts.update(
        session, actor_id=current_user.id, draft_id=draft_id, payload=payload
    )


@router.post("/appeal-drafts/{draft_id}/mark-filed", response_model=AppealDraftView)
async def mark_filed(
    draft_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    payload: AppealFiledMark | None = None,
) -> AppealDraftView:
    """Записать отметку жителя «я отправил». Номер необязателен и не проверяется."""
    return await container.appeal_drafts.mark_filed(
        session,
        actor_id=current_user.id,
        draft_id=draft_id,
        payload=payload or AppealFiledMark(),
    )
