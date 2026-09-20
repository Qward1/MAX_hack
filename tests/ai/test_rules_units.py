"""Юнит-тесты нормализации, маскирования, опасности, места и ролей."""

from __future__ import annotations

import pytest

from domsignal.ai import screen_message_for_danger
from domsignal.ai.masking import author_alias, mask_text
from domsignal.ai.matching import tokenize
from domsignal.ai.normalize import contains_quote, normalize
from domsignal.ai.rules import location as location_rules
from domsignal.ai.rules.lexicon import classify_role, load_lexicon
from domsignal.ai.taxonomy import load_taxonomy


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Ё-моё,   ЛИФТ", "е-мое, лифт"),
        ("нееет свееета", "нет света"),
        ("lift ne rabotaet 2 podezd", "лифт не работает 2 подъезд"),
        ("net vody voobshe", "нет воды вообще"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize(raw).text == expected


def test_normalized_quote_is_substring_of_original() -> None:
    normalized = normalize("Ёлки, ЛИФТ   не работает")
    quote = normalized.quote(normalized.text.index("лифт"), normalized.text.index("лифт") + 4)
    assert quote == "ЛИФТ"
    assert quote in normalized.original


def test_contains_quote_uses_the_same_light_normalisation() -> None:
    assert contains_quote("Лифт во 2 подъезде  не работает", "лифт во 2 подъезде")
    assert not contains_quote("Лифт не работает", "во 2 подъезде")


@pytest.mark.parametrize(
    "raw,masked",
    [
        ("звоните 8 927 123 45 67", "звоните [телефон]"),
        ("пишите на a.b+1@mail.ru", "пишите на [почта]"),
        ("вот ссылка https://example.com/x?y=1", "вот ссылка [ссылка]"),
        ("карта 4276 3800 1234 5678", "карта [карта]"),
        ("я из кв. 45", "я из [квартира]"),
        ("машина а123вс777 мешает", "машина [госномер] мешает"),
        ("номер заявки 1234567", "номер заявки [номер]"),
    ],
)
def test_masking(raw: str, masked: str) -> None:
    assert mask_text(raw) == masked


@pytest.mark.parametrize(
    "raw",
    ["во 2 подъезде", "на 5 этаже", "подъезд №3", "между 3 и 4"],
)
def test_masking_keeps_entrance_and_floor(raw: str) -> None:
    assert mask_text(raw) == raw


def test_author_alias_order() -> None:
    assert [author_alias(index) for index in (0, 1, 25, 26)] == ["A", "B", "Z", "AA"]


@pytest.mark.parametrize(
    "text,kinds",
    [
        ("В подъезде сильно пахнет газом!", {"gas"}),
        ("из щитка на 3 этаже искрит и дым", {"electric", "smoke_fire"}),
        ("человек застрял в лифте, 2 подъезд", {"person_trapped"}),
        ("заливает кипятком сверху, прорвало трубу", {"flooding"}),
        ("тянет гарью из подвала", {"smoke_fire"}),
        ("стена обрушилась у крыльца", {"structural"}),
    ],
)
def test_danger_is_found(text: str, kinds: set[str]) -> None:
    hits = screen_message_for_danger(text)
    assert {hit.kind for hit in hits if not hit.negated} == kinds
    for hit in hits:
        assert hit.quote in text


@pytest.mark.parametrize(
    "text,kind",
    [
        ("газом не пахнет, всё нормально", "gas"),
        ("дыма нет, это сосед шашлык жарит", "smoke_fire"),
        ("никто не застрял, лифт просто не едет", "person_trapped"),
        ("свет не горит на лестнице", "smoke_fire"),
    ],
)
def test_danger_negation(text: str, kind: str) -> None:
    hits = screen_message_for_danger(text)
    assert kind in {hit.kind for hit in hits}, "срабатывание должно сохраняться в журнале"
    assert all(hit.negated for hit in hits if hit.kind == kind)
    assert not [hit for hit in hits if not hit.negated]


def test_negated_one_marker_does_not_hide_another() -> None:
    hits = screen_message_for_danger("Газом не пахнет, но из щитка искрит")
    active = [hit for hit in hits if not hit.negated]
    assert [hit.kind for hit in active] == ["electric"]
    assert any(hit.kind == "gas" and hit.negated for hit in hits)


def test_gas_shutdown_is_not_a_trigger() -> None:
    assert screen_message_for_danger("Отключили газ на день") == []


def test_displaced_markers() -> None:
    hits = screen_message_for_danger("в соседнем доме на Гагарина газом пахнет, ужас")
    assert hits and all(hit.displaced for hit in hits)


def test_danger_screening_never_raises() -> None:
    for text in ("", " ", "🎉🎉🎉", "a" * 4000, "\n\n"):
        assert isinstance(screen_message_for_danger(text), list)


@pytest.mark.parametrize(
    "text,entrance",
    [
        ("во втором подъезде темно", "2"),
        ("подъезд №3, нет света", "3"),
        ("домофн не работает п.2", "2"),
        ("в 1-м под. течёт с потолка", "1"),
        ("2 podezd lift ne rabotaet", "2"),
        ("2-й под. без света", "2"),
    ],
)
def test_entrance_with_quote(text: str, entrance: str) -> None:
    normalized = normalize(text)
    evidence = location_rules.find_entrance(normalized, "line-1")
    assert evidence is not None
    assert evidence.value == entrance
    assert contains_quote(text, evidence.quote)


@pytest.mark.parametrize(
    "text,floor",
    [("на 5 этаже перегорела лампочка", "5"), ("застряли между 3 и 4", "между 3 и 4")],
)
def test_floor_with_quote(text: str, floor: str) -> None:
    evidence = location_rules.find_floor(normalize(text), "line-1")
    assert evidence is not None and evidence.value == floor
    assert contains_quote(text, evidence.quote)


@pytest.mark.parametrize(
    "text",
    ["нет воды с утра", "стоит третий день", "кипятка нет вторые сутки", "темно с выходных"],
)
def test_since_is_extracted_with_quote(text: str) -> None:
    evidence = location_rules.find_since(normalize(text), "line-1")
    assert evidence is not None
    assert contains_quote(text, evidence.quote)


@pytest.mark.parametrize(
    "text,scope",
    [
        ("в подъезде нет света", "house_common"),
        ("в лифте не закрываются двери", "house_common"),
        ("во дворе не горит фонарь", "house_territory"),
        ("на детской площадке сломаны качели", "house_territory"),
        ("на улице у остановки не горят фонари", "municipal_territory"),
        ("на дороге яма", "municipal_territory"),
        ("нет воды во всём районе, авария на магистрали", "external_network"),
        ("в квартире течёт кран", "apartment"),
        ("у меня в ванной мокрое пятно", "apartment"),
        ("в соседнем доме лифт стоит", "other_building"),
        ("всё хорошо", "unknown"),
    ],
)
def test_location_scope(text: str, scope: str) -> None:
    normalized = normalize(text)
    evidence = location_rules.find_scope(normalized, tokenize(normalized.text), "line-1")
    assert evidence.value == scope
    if scope == "unknown":
        assert evidence.quote is None
    else:
        assert evidence.quote and contains_quote(text, evidence.quote)


@pytest.mark.parametrize(
    "text,role",
    [
        ("Когда починят лифт?", "status_question"),
        ("есть новости по воде?", "status_question"),
        ("Лифт починили, спасибо!", "resolved_claim"),
        ("воду дали, всё ок", "resolved_claim"),
        ("Уважаемые жильцы! Завтра плановые работы", "announcement"),
        ("у нас тоже", "me_too"),
        ("в первом", "more_info"),
        ("Соседи сверху шумят после 23", "out_of_scope"),
        ("как передать показания счетчиков?", "out_of_scope"),
        ("Продам детскую коляску", "chatter"),
        ("Лифт в 3 подъезде не работает", "new_problem"),
    ],
)
def test_roles(text: str, role: str) -> None:
    taxonomy = load_taxonomy()
    lexicon = load_lexicon()
    normalized = normalize(text)
    tokens = tokenize(normalized.text)
    subtypes = taxonomy.match(tokens, lexicon.negation_tokens)
    assert (
        classify_role(
            tokens,
            has_subtype=bool(subtypes),
            active_danger=False,
            displaced=False,
            has_place_or_time=False,
            ends_with_question=text.rstrip().endswith("?"),
            lexicon=lexicon,
        )
        == role
    )


@pytest.mark.parametrize("text", ["забит мусоропровод", "сломан доводчик двери", "оборван провод"])
def test_water_stem_does_not_fire_inside_other_words(text: str) -> None:
    """Урок E0: «вод» не должно находиться внутри «мусоропровод»."""
    taxonomy = load_taxonomy()
    matches = taxonomy.match(tokenize(normalize(text).text))
    assert "water" not in {match.subtype.product_category.value for match in matches}
