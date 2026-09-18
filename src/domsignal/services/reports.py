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
    Provenance,
    ReportCreate,
    ReportCreated,
    ReportSummary,
    RuleProvenance,
)
from domsignal.core.incidents import CATEGORY_TITLES, IncidentStatus, ReportCategory
from domsignal.db.models import Incident, Report
from domsignal.db.repositories.incidents import IncidentRepository
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.services.context import OperationSource
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
        provenance: OperationSource = "api",
    ) -> ReportCreated:
        request_hash = _stable_hash(payload.model_dump(mode="json"))
        action = "report.create"
        async with session.begin():
            reliability = ReliabilityRepository(session)
            context = await self.memberships.require_house(
                session,
                user_id=actor_id,
                house_id=payload.house_id,
                source=provenance,
                for_write=True,
            )
            self.memberships.require_permission(context, "report.create")
            existing = await reliability.idempotency_record(
                actor_id=actor_id, action=action, key=idempotency_key
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise IdempotencyConflict(
                        "This Idempotency-Key was already used with a different request body"
                    )
                # Stored C0 receipts contain the old read DTO. Preserve the effect/IDs,
                # but publish the current authorized representation on every replay.
                return ReportCreated(
                    report_id=UUID(existing.response_body["report_id"]),
                    incident=await self.detail(
                        session,
                        actor_id=context.actor_user_id,
                        incident_id=UUID(existing.response_body["incident"]["id"]),
                        house_id=context.house_id,
                    ),
                )

            repo = IncidentRepository(session)
            incident = await repo.create_incident(
                context=context,
                category=payload.category.value,
                title=CATEGORY_TITLES[payload.category],
                description=payload.description,
            )
            report = await repo.create_report(
                incident_id=incident.id,
                house_id=context.house_id,
                author_id=context.actor_user_id,
                category=payload.category.value,
                description=payload.description,
                classification_mode=payload.classification_mode.value,
                provenance=context.source,
            )
            response = ReportCreated(
                report_id=report.id,
                incident=self._detail(
                    incident, [report], is_demo=await repo.house_is_demo(context.house_id)
                ),
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
        context = await self.memberships.require_house(session, user_id=actor_id, house_id=house_id)
        repo = IncidentRepository(session)
        self.memberships.require_permission(context, "incident.read")
        incidents, total = await repo.list_for_house(context, limit=limit, offset=offset)
        counts = await repo.counts([item.id for item in incidents])
        is_demo = await repo.house_is_demo(context.house_id)
        return IncidentList(
            items=[
                self._summary(incident, counts=counts.get(incident.id, (0, 0)), is_demo=is_demo)
                for incident in incidents
            ],
            page=PageMeta(limit=limit, offset=offset, total=total),
        )

    async def detail(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        incident_id: UUID,
        house_id: UUID | None = None,
    ) -> IncidentDetail:
        repo = IncidentRepository(session)
        resolved_house = house_id or await repo.incident_house_id(incident_id)
        if resolved_house is None:
            raise ResourceNotFound("Resource was not found")
        context = await self.memberships.require_house(
            session,
            user_id=actor_id,
            house_id=resolved_house,
        )
        self.memberships.require_permission(context, "incident.read")
        incident = await repo.incident(incident_id, context=context)
        if incident is None:
            raise ResourceNotFound("Resource was not found")
        reports = await repo.reports(incident_id)
        return self._detail(incident, reports, is_demo=await repo.house_is_demo(context.house_id))

    def _summary(
        self, incident: Incident, *, counts: tuple[int, int], is_demo: bool
    ) -> IncidentSummary:
        return IncidentSummary(
            id=incident.id,
            house_id=incident.house_id,
            category=ReportCategory(incident.category),
            title=incident.title,
            description=incident.description,
            status=IncidentStatus(incident.status),
            created_at=incident.created_at,
            updated_at=None,  # C0 stores no update event/time; do not substitute created_at.
            due_at=None,
            location=None,  # C0 stores free text only, never extract at read time.
            report_count=counts[0],
            participant_count=counts[1],
            is_demo=is_demo,
            provenance=Provenance(
                origin="demo" if is_demo else "user_reported",
                recorded_at=incident.created_at,
            ),
        )

    def _detail(
        self, incident: Incident, reports: list[Report], *, is_demo: bool
    ) -> IncidentDetail:
        summary = self._summary(
            incident,
            counts=(len(reports), len({item.author_id for item in reports})),
            is_demo=is_demo,
        )
        detail = IncidentDetail(
            **summary.model_dump(),
            reports=[
                ReportSummary(id=item.id, description=item.description, created_at=item.created_at)
                for item in reports
            ],
            rule=RuleProvenance(
                origin="demo",  # This is explicitly DemoRule, not a routing engine result.
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
