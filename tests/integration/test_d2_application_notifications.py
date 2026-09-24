"""D2: «Получать уведомления в MAX» — код `ca_…` в боте и сообщения о статусе заявки.

Настоящий вебхук (стенд A-07), PostgreSQL и outbox ответов бота.
"""

import json
from uuid import uuid4

from sqlalchemy import select

from domsignal.contracts.onboarding import CompanyApplicationCreate
from domsignal.db.models import CompanyOnboardingRequest, OutboxMessage, User
from domsignal.services.bot_replies import BOT_REPLY_INTENT_KIND
from domsignal.services.company_signup import NOTIFY_INVALID, CompanySignupService
from domsignal.services.onboarding import AdministrationService
from tests.integration.test_chat_bindings import cb  # noqa: F401 - стенд A-07

APPLICATION = CompanyApplicationCreate(
    legal_name="ООО Уведомления",
    short_name="Уведомления",
    inn="7700000044",
    contact_name="Контакт",
    contact_email="n@example.test",
    requested_chat_count=1,
)


async def replies(harness) -> list[dict]:
    async with harness.container.session_factory() as session:
        rows = await session.scalars(
            select(OutboxMessage)
            .where(OutboxMessage.kind == BOT_REPLY_INTENT_KIND)
            .order_by(OutboxMessage.created_at)
        )
        return [row.payload for row in rows]


async def test_application_status_reaches_max_through_a_one_time_code(cb):  # noqa: F811
    settings = cb.container.settings.model_copy(update={"max_bot_username": "synthetic_bot"})
    signup = CompanySignupService(settings)
    administration = AdministrationService(settings)
    platform = uuid4()
    async with cb.container.session_factory() as session, session.begin():
        session.add(User(id=platform, display_name="Платформа", platform_role="superadmin"))
        url = await administration.submit_company(session, APPLICATION)
    token = url.rsplit("/", 1)[-1]
    async with cb.container.session_factory() as session, session.begin():
        link = await signup.notify_link(session, token)
    assert link.startswith("https://max.ru/synthetic_bot?start=ca_")
    code = link.split("start=", 1)[1]
    await cb.webhook("bot_started", chat="104", actor=104, payload=code)
    async with cb.container.session_factory() as session:
        row = await session.scalar(select(CompanyOnboardingRequest))
        assert row.notify_user_id == cb.ids["outsider"] and row.notify_code_hash is None
        assert code not in json.dumps(row.house_addresses or []) and row.status_token_hash
        assert (await signup.status(session, token)).max_notifications is True
    linked = await replies(cb)
    assert len(linked) == 1 and "Буду присылать сюда изменения статуса" in linked[0]["text"]
    assert linked[0]["recipient_user_id"] == str(cb.ids["outsider"])
    # Статусы заявки приходят сообщениями без ссылки статуса.
    async with cb.container.session_factory() as session, session.begin():
        await administration.decide_company(
            session, row.id, platform, "needs_info", "Пришлите договор"
        )
    async with cb.container.session_factory() as session, session.begin():
        await administration.decide_company(session, row.id, platform, "approved", "Проверено")
    texts = [item["text"] for item in await replies(cb)]
    assert any("нужны уточнения" in text for text in texts)
    assert any("одобрена" in text for text in texts)
    assert not any(token in text for text in texts)
    # Код одноразовый: повтор чужим человеком не перехватывает уведомления.
    await cb.webhook("bot_started", chat="102", actor=102, payload=code)
    async with cb.container.session_factory() as session:
        again = await session.scalar(select(CompanyOnboardingRequest))
        assert again.notify_user_id == cb.ids["outsider"]
    assert (await replies(cb))[-1]["text"] == NOTIFY_INVALID
    # Код подключения чата A-07 и обычный старт идут прежним путём.
    await cb.webhook("bot_started", chat="103", actor=103, payload="ca_unknown-code")
    assert (await replies(cb))[-1]["text"] == NOTIFY_INVALID
