"""D4, В-2: пояс дома — из пакета региона, через настоящую привязку чата.

Один момент UTC: во Владивостоке 23:30 — пост рассылки ждёт утра, в Москве
16:30 — уходит сразу. Код не знает регионов: пояс лежит в `regions/RU-PRI`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from domsignal.db.models import ChatBinding
from domsignal.db.models.notifications import BROADCAST_CHAT_PURPOSE
from domsignal.db.repositories.routing import RoutingRepository
from domsignal.services.community_delivery import defer_until
from tests.integration.passive_harness import build_harness, passive_settings

#: 13:30 UTC — 23:30 во Владивостоке, 16:30 в Москве.
MOMENT = datetime(2026, 9, 27, 13, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("region", "municipality", "until"),
    [
        ("RU-PRI", "vladivostok", datetime(2026, 9, 27, 22, 0, tzinfo=UTC)),  # 08:00 ВЛАД
        ("RU-MOW", "moscow", None),
    ],
)
async def test_the_chat_post_waits_for_the_morning_of_the_house_zone(
    integration_settings: Any, region: str, municipality: str, until: datetime | None
) -> None:
    harness, _ = await build_harness(passive_settings(integration_settings))
    try:
        binding_id = await harness.bind(enable=False)
        async with harness.container.session_factory() as session, session.begin():
            binding = await session.get(ChatBinding, binding_id)
            assert binding is not None
            assert (binding.quiet_start_minute, binding.quiet_end_minute) == (22 * 60, 8 * 60)
            await RoutingRepository(session).upsert_profile(
                house_id=binding.house_id,
                region_code=region,
                municipality_code=municipality,
                territory_policy="mixed",
                updated_by=None,
            )
        post = SimpleNamespace(
            purpose=BROADCAST_CHAT_PURPOSE, provider_message_id=None, chat_binding_id=binding_id
        )
        async with harness.container.session_factory() as session:
            deferred = await defer_until(
                session, post, MOMENT, zones=harness.container.zones  # type: ignore[arg-type]
            )
        assert deferred == until
    finally:
        await harness.client.aclose()
        await harness.container.aclose()

