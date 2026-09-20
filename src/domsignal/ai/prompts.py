"""Промпт окна v1: детерминированный рендер, независимый от провайдера.

Системное сообщение собирается из шаблона `prompts/window.v1.md` и живых
значений контракта: коды таксономии, территории, признаки, роли, виды
опасности и причины опровержения. Расхождение между контрактом и промптом
невозможно — при рассинхронизации модуль не импортируется.

Пользовательское сообщение — сериализованный `ProviderRequest`: замаскированные
тексты, номера `m1..mN`, псевдонимы авторов, смещения во времени, `reply_to`,
контекстные реплики и открытые элементы `open:K`. Идентификаторов продукта в
нём нет.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, cast

from domsignal.ai.contracts import (
    DANGER_KINDS,
    LOCATION_SCOPES,
    REFUTATION_REASONS,
    ROLES,
    DangerKind,
    LineRole,
    LocationScope,
    RefutationReason,
)
from domsignal.ai.providers.base import ProviderRequest
from domsignal.ai.resources import read_resource
from domsignal.ai.schema_modes import SchemaMode, schema_in_prompt, strict_schema
from domsignal.ai.taxonomy import Taxonomy, load_taxonomy

#: Версия промпта, попадающая в `WindowAnalysis.versions.prompt`.
PROMPT_VERSION = "window.v1"

PROMPT_RESOURCE = "prompts/window.v1.md"
EXAMPLES_RESOURCE = "prompts/window.v1.examples.jsonl"

SCOPE_GUIDE: dict[LocationScope, str] = {
    "apartment": "внутри квартиры: «у меня в ванной», «в моей квартире», «у соседа сверху»",
    "house_common": (
        "общее имущество дома: подъезд, лестница, лифт, подвал, чердак, крыша, "
        "стояк, щиток, мусоропровод, входная дверь"
    ),
    "house_territory": (
        "двор и участок дома: детская площадка у дома, парковка жильцов, "
        "газон у подъезда, дорожка от подъезда"
    ),
    "municipal_territory": (
        "городская территория за двором: улица, проспект, тротуар, остановка, "
        "сквер, парк, дорога, городское освещение"
    ),
    "external_network": (
        "внешние сети и авария за домом: «отключили весь квартал», «порыв на "
        "магистрали», «авария в районе»"
    ),
    "other_building": "другой дом или здание: «в соседнем доме», «в доме напротив», «в школе»",
    "unknown": "место не названо или названо без дословной цитаты",
}

ROLE_GUIDE: dict[LineRole, str] = {
    "new_problem": "сообщение о проблеме, которой ещё не было в окне",
    "me_too": "подтверждение той же проблемы у себя: «у нас тоже», «и у меня»",
    "more_info": "уточнение уже названной проблемы: где именно, с какого времени, что видно",
    "objection": "возражение: проблемы нет, это не то, причина другая",
    "status_question": "вопрос о ходе работ или сроках: «когда почините», «есть новости»",
    "resolved_claim": "утверждение, что проблема устранена: «уже работает», «починили»",
    "announcement": "объявление или пересказ новости, а не собственное наблюдение",
    "discussion": "обсуждение по теме дома без собственного наблюдения о проблеме",
    "chatter": "болтовня, приветствия, благодарности, эмоции",
    "out_of_scope": (
        "не про общее имущество и не про территорию: личные дела, «посоветуйте "
        "мастера», «соседи шумят», продажа, реклама"
    ),
}

DANGER_GUIDE: dict[DangerKind, str] = {
    "gas": "запах газа, утечка, шипение газа",
    "smoke_fire": "дым, гарь, открытый огонь, задымление",
    "electric": "искрение, замыкание, треск и вспышки в проводке, удар током, оплавление",
    "person_trapped": "человек заперт или зажат: люди в кабине лифта, кто-то не может выйти",
    "flooding": "активное затопление: вода льётся, хлещет, прибывает",
    "structural": "обрушение или угроза обрушения: рухнуло, обвалилось, шатается, падает",
    "other_hazard": (
        "иная непосредственная угроза здоровью, которую не покрывают виды выше: "
        "«едкий запах, глаза режет», «ступени провалились под ногой»"
    ),
}

REFUTATION_GUIDE: dict[RefutationReason, str] = {
    "past": "это было раньше и уже прошло: «это было вчера», «в прошлом месяце»",
    "resolved": "уже устранено: «уже приехали», «починили», «вытащили»",
    "other_place": "это про другой дом, двор или район: «это в соседнем доме»",
    "explicit_negation": "прямое отрицание опасности: «нет, ничем не пахнет», «никто не застрял»",
    "not_literal": "сказано не буквально: шутка, сравнение, преувеличение",
}


def _check(guide: dict[Any, str], expected: tuple[str, ...], name: str) -> None:
    missing = [code for code in expected if code not in guide]
    extra = [code for code in guide if code not in expected]
    if missing or extra:
        raise RuntimeError(
            f"промпт окна разошёлся с контрактом {name}: нет {missing}, лишние {extra}"
        )


_check(cast(dict[Any, str], SCOPE_GUIDE), LOCATION_SCOPES, "location_scope")
_check(cast(dict[Any, str], ROLE_GUIDE), ROLES, "roles")
_check(cast(dict[Any, str], DANGER_GUIDE), DANGER_KINDS, "danger kinds")
_check(cast(dict[Any, str], REFUTATION_GUIDE), REFUTATION_REASONS, "refutation reasons")


@dataclass(frozen=True)
class FewShotExample:
    """Пример «запрос → ответ» на синтетическом окне, написанном для промпта."""

    id: str
    user: str
    assistant: str


def _bullets(guide: dict[Any, str], order: tuple[str, ...]) -> str:
    return "\n".join(f"- `{code}` — {guide[code]}" for code in order)


def _subtype_bullets(taxonomy: Taxonomy) -> str:
    return "\n".join(
        f"- `{subtype.code}` — {subtype.description}" for subtype in taxonomy.subtypes
    )


def render_system_prompt(
    taxonomy: Taxonomy | None = None, *, mode: SchemaMode = "json_schema_strict"
) -> str:
    """Системное сообщение промпта окна для выбранного режима схемы."""
    tax = taxonomy or load_taxonomy()
    if schema_in_prompt(mode):
        schema = json.dumps(strict_schema(tax), ensure_ascii=False, indent=2, sort_keys=True)
        schema_block = f"Схема ответа (JSON Schema):\n\n```json\n{schema}\n```"
    else:
        schema_block = "Схема ответа передана отдельным полем запроса — следуй ей точно."
    scopes = cast(dict[Any, str], SCOPE_GUIDE)
    roles = cast(dict[Any, str], ROLE_GUIDE)
    dangers = cast(dict[Any, str], DANGER_GUIDE)
    refutations = cast(dict[Any, str], REFUTATION_GUIDE)
    substitutions = {
        "{{SUBTYPES}}": _subtype_bullets(tax),
        "{{LOCATION_SCOPES}}": _bullets(scopes, LOCATION_SCOPES),
        "{{ROLES}}": _bullets(roles, ROLES),
        "{{DANGER_KINDS}}": _bullets(dangers, DANGER_KINDS),
        "{{REFUTATIONS}}": _bullets(refutations, REFUTATION_REASONS),
        "{{SCHEMA}}": schema_block,
    }
    rendered = read_resource(PROMPT_RESOURCE)
    for placeholder, block in substitutions.items():
        rendered = rendered.replace(placeholder, block)
    if "{{" in rendered:
        raise RuntimeError("в промпте окна остались незаполненные подстановки")
    return rendered.strip() + "\n"


def render_user_message(request: ProviderRequest) -> str:
    """Пользовательское сообщение: сам запрос окна в JSON.

    Список кодов подтипов не дублируется: он уже перечислен с описаниями в
    системном сообщении.
    """
    payload = request.model_dump(mode="json", exclude={"subtype_codes"})
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


@lru_cache(maxsize=1)
def load_examples() -> tuple[FewShotExample, ...]:
    """Few-shot примеры промпта: синтетические окна, написанные для промпта."""
    examples: list[FewShotExample] = []
    for raw in read_resource(EXAMPLES_RESOURCE).splitlines():
        if not raw.strip():
            continue
        row = cast(dict[str, Any], json.loads(raw))
        request = ProviderRequest.model_validate(row["request"])
        examples.append(
            FewShotExample(
                id=str(row["id"]),
                user=render_user_message(request),
                assistant=json.dumps(row["response"], ensure_ascii=False, sort_keys=True),
            )
        )
    if not examples:
        raise RuntimeError("few-shot примеры промпта окна не найдены")
    return tuple(examples)


def build_messages(
    request: ProviderRequest,
    taxonomy: Taxonomy | None = None,
    *,
    mode: SchemaMode = "json_schema_strict",
    few_shot: bool = True,
) -> list[dict[str, str]]:
    """Сообщения одного вызова: system, few-shot парами и разбираемое окно."""
    messages: list[dict[str, str]] = [
        {"role": "system", "content": render_system_prompt(taxonomy, mode=mode)}
    ]
    if few_shot:
        for example in load_examples():
            messages.append({"role": "user", "content": example.user})
            messages.append({"role": "assistant", "content": example.assistant})
    messages.append({"role": "user", "content": render_user_message(request)})
    return messages
