"""D3: контракты навигатора и сообщества — только проекции и честные подписи."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from domsignal.contracts.community import (
    AnnouncementItem,
    BroadcastCreate,
    CompanyProfileUpdate,
    CompletedWork,
    PollDraft,
    PollView,
)
from domsignal.contracts.notifications import NotificationLaunch
from domsignal.services import community_texts


def test_resident_projections_have_no_private_fields() -> None:
    for model in (CompletedWork, PollView, AnnouncementItem):
        fields = set(model.model_fields)
        assert not fields & {
            "author_id",
            "reported_by",
            "performed_by",
            "performer_name",
            "comment",
            "actor_id",
            "user_id",
            "display_name",
        }, model.__name__


def test_a_poll_disclaimer_says_it_is_not_a_general_meeting() -> None:
    text = community_texts.POLL_DISCLAIMER.lower()
    assert "не является решением общего собрания собственников" in text


def test_the_service_only_rule_forbids_advertising() -> None:
    assert "реклама запрещена" in community_texts.SERVICE_ONLY_RULE.lower()


def test_polls_need_two_to_ten_distinct_options() -> None:
    base = {"question": "Когда удобно собрание?", "closes_at": "2026-10-01T10:00:00+03:00"}
    with pytest.raises(ValidationError):
        PollDraft(**base, options=["Вечер"])
    with pytest.raises(ValidationError):
        PollDraft(**base, options=["Вечер", "вечер"])
    with pytest.raises(ValidationError):
        PollDraft(**base, options=[str(index) for index in range(11)])
    assert len(PollDraft(**base, options=["Утро", "Вечер"]).options) == 2


def test_an_announcement_needs_a_topic_and_a_poll_needs_a_poll() -> None:
    with pytest.raises(ValidationError):
        BroadcastCreate(kind="announcement", title="Отключение", body="Текст", channels=["chat"])
    with pytest.raises(ValidationError):
        BroadcastCreate(kind="poll", title="Опрос", channels=["chat"])
    with pytest.raises(ValidationError):
        BroadcastCreate(
            kind="mailing", title="Рассылка", body="Текст", channels=["chat", "chat"]
        )


def test_company_profile_rejects_unsafe_links_and_bad_phones() -> None:
    with pytest.raises(ValidationError):
        CompanyProfileUpdate(website="javascript:alert(1)")
    with pytest.raises(ValidationError):
        CompanyProfileUpdate(phone="звоните")
    profile = CompanyProfileUpdate(website=" https://uk.example ", phone="+7 843 000-00-00")
    assert profile.website == "https://uk.example"


def test_the_launch_contract_is_additive() -> None:
    assert NotificationLaunch.model_fields["poll_id"].is_required() is False
    assert NotificationLaunch.model_fields["kind"].default == "ticket"
