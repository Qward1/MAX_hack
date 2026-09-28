"""D-01 (живой прогон 28.09): кнопка «Открыть ДомСигнал» в чате ведёт на дом этого чата.

У жителя два дома. Ссылка `c_…` из сообщения бота в чате дома №2 отдаёт
`kind=house` с домом №2 — mini app открывается на нём, а не на первом доме
по алфавиту. Ссылка чата, к дому которого у человека нет доступа, — 404.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from domsignal.db.models import NotificationDelivery
from tests.integration.passive_harness import CHAT_1, CHAT_2
from tests.integration.test_d1_chat_membership import (  # noqa: F401
    NEWCOMER,
    STRANGER,
    d1,
    login,
    rows_user,
)


async def test_the_chat_button_opens_the_house_of_that_chat(d1: Any) -> None:  # noqa: F811
    b1 = await d1.bind()
    b2 = await d1.bind(chat=CHAT_2, house="h2", admin="admin2")
    await d1.deliver()
    refs = {
        row.chat_binding_id: row.launch_ref
        for row in await d1.all(
            select(NotificationDelivery).where(
                NotificationDelivery.purpose == "chat_reading_notice"
            )
        )
    }
    d1.fake.members[CHAT_1] = {str(NEWCOMER)}
    d1.fake.members[CHAT_2] = {str(NEWCOMER)}
    headers = await login(d1, NEWCOMER)
    user_id = (await rows_user(d1, NEWCOMER)).id
    for binding, house in ((b1, "h1"), (b2, "h2")):
        await d1.container.resident_access.refresh(user_id, launch_ref=refs[binding])
        response = await d1.client.get(
            f"/api/v1/notification-launch/{refs[binding]}", headers=headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["kind"] == "house" and body["house_id"] == str(d1.ids[house])

    stranger = await login(d1, STRANGER)
    denied = await d1.client.get(f"/api/v1/notification-launch/{refs[b2]}", headers=stranger)
    assert denied.status_code == 404
