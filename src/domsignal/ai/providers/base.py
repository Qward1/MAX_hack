"""Интерфейс провайдера анализа окна и построение внешнего запроса.

Во внешний запрос не попадают идентификаторы продукта: реплики
перенумерованы `m1..mN`, авторы заменены псевдонимами по первому появлению,
открытые элементы получают номера `open:1..K`, тексты замаскированы. Обратное
соответствие живёт только в памяти процесса.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from domsignal.ai.contracts import Channel, WindowInput
from domsignal.ai.masking import author_alias, mask_text
from domsignal.ai.model_output import SCHEMA_ID
from domsignal.ai.taxonomy import Taxonomy, load_taxonomy


class ProviderError(RuntimeError):
    """Базовая ошибка провайдера."""


class ProviderTimeout(ProviderError):
    """Провайдер не ответил за отведённое время."""


class ProviderUnavailable(ProviderError):
    """Провайдер недоступен: сеть, 5xx, 429 или истёкший ключ."""


class ProviderRateLimited(ProviderUnavailable):
    """Лимит запросов провайдера (HTTP 429) или свой ограничитель токенов в минуту.

    Это не отказ провайдера: предохранитель от него не размыкается (F1,
    LLM-RATE-2026-09-29). `retry_after` — через сколько секунд можно
    повторить, если провайдер это сообщил; `local` — отказал собственный
    ограничитель, вызова не было.
    """

    def __init__(
        self, message: str, *, retry_after: float | None = None, local: bool = False
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.local = local


class ProviderInvalidOutput(ProviderError):
    """Провайдер ответил тем, что не разбирается по схеме."""


class ProviderBudgetExceeded(ProviderError):
    """Дневной бюджет вызовов или доля чата исчерпаны: вызова не было."""


class ProviderCircuitOpen(ProviderError):
    """Предохранитель разомкнут после серии отказов: вызова не было."""


class ProviderOverloaded(ProviderError):
    """Свободных мест в ограничителе конкурентности не нашлось за отведённое ожидание."""


class Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProviderLine(Strict):
    id: str
    author: str
    text: str
    offset_seconds: int = 0
    reply_to: str | None = None
    is_context: bool = False


class ProviderOpenItem(Strict):
    ref: str
    category: str
    subtype: str | None = None
    entrance: str | None = None
    title: str
    danger_kinds: tuple[str, ...] = ()


class ProviderRequest(Strict):
    """Единица работы провайдера: одно окно, один вызов."""

    channel: Channel
    schema_id: str = SCHEMA_ID
    lines: tuple[ProviderLine, ...] = Field(min_length=1)
    open_items: tuple[ProviderOpenItem, ...] = ()
    entrance_hint: str | None = None
    subtype_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderResult:
    """Итог одного вызова модели: сырой ответ и учёт токенов и стоимости.

    `content` — текст ответа без разбора: разбирает и проверяет его ядро, а не
    провайдер. `tokens_in`, `tokens_out` и `cost_rub` заполняются, только если
    их сообщил сам провайдер; выдуманных оценок здесь нет.
    """

    content: str
    model: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_rub: float | None = None
    latency_ms: int = 0


@dataclass(frozen=True)
class WindowMapping:
    """Обратное соответствие внешних номеров внутренним идентификаторам."""

    line_by_msg: dict[str, str] = field(default_factory=dict)
    msg_by_line: dict[str, str] = field(default_factory=dict)
    item_by_ref: dict[str, str] = field(default_factory=dict)
    alias_by_author: dict[str, str] = field(default_factory=dict)

    def line_id(self, msg: str) -> str | None:
        return self.line_by_msg.get(msg)

    def item_ref(self, ref: str) -> str | None:
        return self.item_by_ref.get(ref)


def build_request(
    window: WindowInput, taxonomy: Taxonomy | None = None
) -> tuple[ProviderRequest, WindowMapping]:
    """Построить внешний запрос и запомнить обратное соответствие."""
    tax = taxonomy or load_taxonomy()
    mapping = WindowMapping()
    first_sent = window.lines[0].sent_at
    lines: list[ProviderLine] = []
    for index, line in enumerate(window.lines, start=1):
        msg = f"m{index}"
        mapping.line_by_msg[msg] = line.line_id
        mapping.msg_by_line[line.line_id] = msg
        if line.author_ref not in mapping.alias_by_author:
            mapping.alias_by_author[line.author_ref] = author_alias(
                len(mapping.alias_by_author)
            )
        lines.append(
            ProviderLine(
                id=msg,
                author=mapping.alias_by_author[line.author_ref],
                text=mask_text(line.text),
                offset_seconds=int((line.sent_at - first_sent).total_seconds()),
                reply_to=mapping.msg_by_line.get(line.reply_to or ""),
                is_context=line.is_context,
            )
        )
    items: list[ProviderOpenItem] = []
    for index, item in enumerate(window.open_items, start=1):
        ref = f"open:{index}"
        mapping.item_by_ref[ref] = item.ref
        items.append(
            ProviderOpenItem(
                ref=ref,
                category=item.category.value,
                subtype=item.subtype,
                entrance=item.entrance,
                title=mask_text(item.title),
                danger_kinds=tuple(item.danger_kinds),
            )
        )
    request = ProviderRequest(
        channel=window.channel,
        lines=tuple(lines),
        open_items=tuple(items),
        entrance_hint=window.entrance_hint,
        subtype_codes=tax.codes,
    )
    return request, mapping


@runtime_checkable
class AnalysisProvider(Protocol):
    """Провайдер делает ровно один вызов на окно и возвращает сырой ответ.

    Повторов внутри провайдера нет: отказ — это результат, и ядро отвечает
    результатом правил. Версию промпта провайдер объявляет необязательным
    атрибутом `prompt_version`; провайдер без промпта его не имеет.
    """

    async def analyze_window(self, request: ProviderRequest) -> ProviderResult: ...


def prompt_version_of(provider: object) -> str | None:
    """Версия промпта провайдера, если он её объявляет."""
    version = getattr(provider, "prompt_version", None)
    return version if isinstance(version, str) and version else None
