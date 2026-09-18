from dataclasses import replace

import pytest
from pydantic import ValidationError

from domsignal.bootstrap import build_container
from domsignal.bot.chat_provider import HttpMaxChatProvider, MaxProviderError
from domsignal.contracts.chat_connections import ConnectionCreate
from domsignal.core.access import AccessPolicy
from domsignal.core.chat_connections import binding_transition, connection_transition
from domsignal.settings import Settings
from tests.fakes.max_chat import FakeMaxChatProvider


def test_connection_state_machine_and_scope() -> None:
    path = [
        "created",
        "connector_claimed",
        "chat_detected",
        "max_verified",
        "awaiting_approval",
        "completed",
    ]
    for current, target in zip(path, path[1:], strict=False):
        assert connection_transition(current, target) == target
        assert connection_transition(current, current) == current
        assert connection_transition(current, "expired") == "expired"
    for source, target in [
        ("created", "completed"),
        ("rejected", "max_verified"),
        ("expired", "connector_claimed"),
        ("completed", "cancelled"),
    ]:
        with pytest.raises(ValueError):
            connection_transition(source, target)
    assert binding_transition("active", "suspended") == "suspended"
    with pytest.raises(ValueError):
        binding_transition("revoked", "active")
    for value in [
        {"scope_type": "entrance"},
        {"scope_value": "2"},
        {"scope_type": "multi-house"},
        {"scope_type": "entrance", "scope_value": " "},
    ]:
        with pytest.raises(ValidationError):
            ConnectionCreate.model_validate(value)


@pytest.mark.parametrize(
    "org,assignment,allowed",
    [
        ("company_admin", None, True),
        ("operator", "responsible", True),
        ("operator", "operator", False),
        (None, None, False),
        ("superadmin", None, False),
    ],
)
def test_connection_policy(org: str | None, assignment: str | None, allowed: bool) -> None:
    assert (
        "chat.connect"
        in AccessPolicy.permissions(
            organization_role=org,
            assignment_role=assignment,
            resident=True,
        )
    ) is allowed


async def test_adapter_admin_permissions_metadata() -> None:
    fake = FakeMaxChatProvider()
    fake.configure("-1")
    assert (await fake.get_chat_info("-1")).title == "Synthetic chat"
    assert (await fake.get_bot_membership("-1")).is_admin
    assert (await fake.get_chat_admins("-1"))[0].user_id == "101"
    fake.bots["-1"] = replace(fake.bots["-1"], is_admin=False, permissions=frozenset())
    fake.admins["-1"] = (replace(fake.admins["-1"][0], is_admin=False),)
    assert not (await fake.get_bot_membership("-1")).is_admin
    assert not (await fake.get_bot_membership("-1")).permissions
    assert not (await fake.get_chat_admins("-1"))[0].is_admin


@pytest.mark.parametrize("error", ["timeout", "429", "5xx", "max_chat_not_found"])
async def test_adapter_failures(error: str) -> None:
    fake = FakeMaxChatProvider(failures={"-1": error})
    with pytest.raises(MaxProviderError) as failure:
        await fake.get_chat_info("-1")
    assert failure.value.temporary is (error != "max_chat_not_found")
    with pytest.raises(MaxProviderError, match="max_chat_not_found"):
        await FakeMaxChatProvider().get_chat_info("-2")


async def test_production_never_selects_fake_and_off_cannot_call_max() -> None:
    settings = Settings(
        app_env="production",
        allow_test_session=False,
        demo_seed=False,
        session_secret="synthetic-long-secret",
        database_url="postgresql+asyncpg://x:x@localhost/x",
        public_base_url="https://example.invalid",
        max_bot_token="synthetic",
        _env_file=None,
    )
    container = build_container(settings)
    assert isinstance(container.chat_connections.provider, HttpMaxChatProvider)
    with pytest.raises(MaxProviderError, match="max_not_configured"):
        await container.chat_connections.provider.get_chat_info("-1")
    await container.engine.dispose()
    with pytest.raises(ValidationError):
        Settings(max_required_permissions=[], _env_file=None)
