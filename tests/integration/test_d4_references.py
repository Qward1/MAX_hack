"""D4: «Где посмотреть тарифы и капремонт» — только официальные страницы региона."""

from __future__ import annotations

import pytest
from sqlalchemy import update

from domsignal.db.models import HouseRoutingProfile
from tests.integration.explicit_harness import ex  # noqa: F401


@pytest.mark.integration
async def test_my_house_lists_the_region_reference_pages_without_numbers(ex) -> None:  # noqa: F811
    path = f"/api/v1/houses/{ex.ids['h1']}/overview"
    body = (await ex.client.get(path, headers=ex.headers["resident"])).json()
    links = {item["kind"]: item for item in body["reference_links"]}
    assert set(links) == {"tariffs", "capital_repair"}
    assert links["tariffs"]["url"] == "https://kt.tatarstan.ru/ntarif.htm"
    assert all(item["source"]["verified_at"] for item in links.values())
    # Нет региона — нет и блока: ссылки только с официальным источником региона.
    async with ex.container.session_factory() as session, session.begin():
        await session.execute(
            update(HouseRoutingProfile)
            .where(HouseRoutingProfile.house_id == ex.ids["h1"])
            .values(region_code=None, municipality_code=None)
        )
    body = (await ex.client.get(path, headers=ex.headers["resident"])).json()
    assert body["reference_links"] == []
