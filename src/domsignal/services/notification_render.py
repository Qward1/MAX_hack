"""Deterministic resident allowlist. No Report text, internal reasons or other observations."""

from domsignal.bot.messaging import MessageButton, PersonalMessage
from domsignal.contracts.tickets import ResidentWorkStatus


def actionable(view: ResidentWorkStatus, attempt_id: object) -> bool:
    return bool(
        view.latest_attempt
        and view.latest_attempt.id == attempt_id
        and view.status == "verification_pending"
        and not view.latest_attempt.rework_required
        and view.my_latest_observation is None
        and "observe_result" in view.allowed_actions
    )


def render(
    *,
    purpose: str,
    title: str,
    view: ResidentWorkStatus,
    attempt_id: object,
    ref: str,
) -> PersonalMessage:
    active = purpose == "work_verification" and actionable(view, attempt_id)
    rows: list[tuple[MessageButton, ...]] = [
        (MessageButton("open_app", "Открыть и проверить" if active else "Открыть проблему", ref),)
    ]
    if purpose == "ticket_accepted":
        text = "Проблема принята в работу"
    elif not view.latest_attempt or view.latest_attempt.id != attempt_id:
        text = "По проблеме появился новый результат. Откройте актуальную работу."
    elif view.status == "cancelled":
        text = "Работа по этой заявке отменена. Актуальное состояние — в приложении."
    elif (
        view.status == "in_progress"
        and view.my_latest_observation
        and view.my_latest_observation.outcome == "unresolved"
    ):
        text = "Ваш ответ учтён. Проблема возвращена в работу."
    elif view.status == "closed":
        text = (
            "Вы подтвердили, что после последней работы проблема устранена."
            if view.my_latest_observation
            else "Результат проверен жителями."
        )
    elif active:
        text = (
            "Исполнитель сообщил о выполнении\n\n"
            + view.latest_attempt.public_description[:2500]
            + "\n\nПроверьте, устранена ли проблема."
        )
        rows.append(
            (
                MessageButton("callback", "Исправлено", f"{ref}:resolved"),
                MessageButton("callback", "Проблема осталась", f"{ref}:unresolved"),
            )
        )
    elif view.status == "in_progress":
        text = "Проблема возвращена в работу. Ожидается новый результат."
    else:
        text = "Состояние работы изменилось. Откройте проблему для актуальных сведений."
    return PersonalMessage(f"{title}\n\n{text}", tuple(rows))
