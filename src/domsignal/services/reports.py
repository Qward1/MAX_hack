from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.common import PageMeta
from domsignal.contracts.incidents import (
    IncidentDetail,
    IncidentList,
    IncidentSummary,
    ReportCreate,
    ReportCreated,
    ReportSummary,
    RuleProvenance,
)
from domsignal.core.incidents import CATEGORY_TITLES, IncidentStatus, ReportCategory
from domsignal.db.models import Incident, Report
from domsignal.db.repositories.incidents import IncidentRepository
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.services.errors import IdempotencyConflict, ResourceNotFound
from domsignal.services.membership import MembershipService


@dataclass(frozen=True)
class DemoRule:
    source_url: str
    source_title: str
    verification_status: str
    note: str


class ReportService:
    def __init__(self, *, demo_rule: DemoRule) -> None:
        self.demo_rule = demo_rule
        self.memberships = MembershipService()

    async def create(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        payload: ReportCreate,
        idempotency_key: str,
        provenance: str = "api",
    ) -> ReportCreated:
        request_hash = _stable_hash(payload.model_dump(mode="json"))
        action = "report.create"
        async with session.begin():
            reliability = ReliabilityRepository(session)
            await self.memberships.require_house(
                session, user_id=actor_id, house_id=payload.house_id
            )
            existing = await reliability.idempotency_record(
                actor_id=actor_id, action=action, key=idempotency_key
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise IdempotencyConflict(
                        "This Idempotency-Key was already used with a different request body"
                    )
                return ReportCreated.model_validate(existing.response_body)

            repo = IncidentRepository(session)
            incident = await repo.create_incident(
                house_id=payload.house_id,
                category=payload.category.value,
                title=CATEGORY_TITLES[payload.category],
                description=payload.description,
            )
            report = await repo.create_report(
                incident_id=incident.id,
                house_id=payload.house_id,
                author_id=actor_id,
                category=payload.category.value,
                description=payload.description,
                classification_mode=payload.classification_mode.value,
                provenance=provenance,
            )
            response = ReportCreated(
                report_id=report.id,
                incident=self._detail(incident, [report]),
            )
            response_body = response.model_dump(mode="json")
            reliability.add_idempotency(
                actor_id=actor_id,
                action=action,
                key=idempotency_key,
                request_hash=request_hash,
                response_status=201,
                response_body=response_body,
            )
            reliability.add_outbox(
                kind="incident.created",
                aggregate_id=incident.id,
                payload={"incident_id": str(incident.id), "house_id": str(incident.house_id)},
            )
        return response

    async def list_for_house(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        house_id: UUID,
        limit: int,
        offset: int,
    ) -> IncidentList:
        await self.memberships.require_house(session, user_id=actor_id, house_id=house_id)
        incidents, total = await IncidentRepository(session).list_for_house(
            house_id, limit=limit, offset=offset
        )
        return IncidentList(
            items=[self._summary(incident) for incident in incidents],
            page=PageMeta(limit=limit, offset=offset, total=total),
        )

    async def detail(
        self, session: AsyncSession, *, actor_id: UUID, incident_id: UUID
    ) -> IncidentDetail:
        repo = IncidentRepository(session)
        incident = await repo.incident(incident_id)
        if incident is None:
            raise ResourceNotFound("Incident was not found")
        await self.memberships.require_house(session, user_id=actor_id, house_id=incident.house_id)
        reports = await repo.reports(incident_id)
        return self._detail(incident, reports)

    def _summary(self, incident: Incident) -> IncidentSummary:
        return IncidentSummary(
            id=incident.id,
            house_id=incident.house_id,
            category=ReportCategory(incident.category),
            title=incident.title,
            description=incident.description,
            status=IncidentStatus(incident.status),
            created_at=incident.created_at,
        )

    def _detail(self, incident: Incident, reports: list[Report]) -> IncidentDetail:
        summary = self._summary(incident)
        detail = IncidentDetail(
            **summary.model_dump(),
            reports=[
                ReportSummary(id=item.id, description=item.description, created_at=item.created_at)
                for item in reports
            ],
            rule=RuleProvenance(
                verification_status=cast(
                    Literal["verified", "needs_verification", "demo"],
                    self.demo_rule.verification_status,
                ),
                source_url=self.demo_rule.source_url,
                source_title=self.demo_rule.source_title,
                due_at=None,
                note=self.demo_rule.note,
            ),
        )
        return detail


def _stable_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
