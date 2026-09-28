"""Build a small SYNTHETIC smoke dataset in the v3.0 folder format.

Purpose: let anyone run `train -> single -> chat -> eval` of the standalone
module on a clean clone, without the private v3.0 dataset of real chats.
Every message is generated from templates below; nothing comes from real
chats. Metrics computed on it only prove that the pipeline runs end to end —
they are NOT a quality measurement and must not be quoted as one.

Output (git-ignored): ml/artifacts/smoke-data/
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ML_ROOT / "artifacts" / "smoke-data"
SEED = 42

# class -> templates; {e} entrance, {f} floor
PROBLEMS: dict[str, list[str]] = {
    "elevator_out": [
        "Во {e} подъезде не работает лифт",
        "лифт в {e} подъезде опять стоит",
        "Лифт не приходит на {f} этаж, {e} подъезд",
        "Сломался лифт в подъезде {e}, не вызывается",
        "грузовой лифт в {e} подъезде не работает с утра",
    ],
    "no_hot_water": [
        "Во {e} подъезде нет горячей воды",
        "С утра нет горячей воды, {e} подъезд",
        "горячую воду отключили без объявления, {f} этаж",
        "Нет горячей воды уже второй день",
        "из горячего крана идёт только холодная вода",
    ],
    "no_cold_water": [
        "Нет холодной воды во всём доме",
        "в {e} подъезде пропала холодная вода",
        "Холодной воды нет с ночи, {f} этаж",
        "отключили холодную воду, когда дадут?",
    ],
    "water_leak": [
        "В подвале {e} подъезда течёт труба",
        "С потолка на {f} этаже капает вода",
        "Протечка в подъезде {e}, лужа на площадке",
        "течёт стояк на {f} этаже",
    ],
    "lighting_entrance": [
        "В {e} подъезде не горит свет на лестнице",
        "На {f} этаже перегорела лампочка",
        "темно в подъезде {e}, свет не включается",
        "не работает освещение на лестничной клетке {f} этажа",
    ],
    "intercom": [
        "Не работает домофон в {e} подъезде",
        "домофон не открывает дверь, подъезд {e}",
        "Сломался домофон, ключ не срабатывает",
        "домофон звонит, но дверь не открывается",
    ],
    "door_defect": [
        "Входная дверь {e} подъезда не закрывается",
        "сломан доводчик на двери в {e} подъезде",
        "Дверь в подъезд {e} не захлопывается",
        "замок на входной двери сломан",
    ],
    "gas_smell": [
        "В подъезде {e} пахнет газом",
        "Запах газа на {f} этаже, срочно",
        "сильно пахнет газом у лифта",
        "чувствуется запах газа в {e} подъезде",
    ],
    "heating_none": [
        "Батареи холодные, отопления нет",
        "в квартире на {f} этаже не греют батареи",
        "Когда включат отопление? дома холодно",
        "отопление не работает в {e} подъезде",
    ],
    "cleaning_entrance": [
        "В {e} подъезде давно не мыли полы",
        "грязно на лестнице, уборки не было неделю",
        "На {f} этаже мусор, никто не убирает",
        "в подъезде {e} не убирают",
    ],
}
RESOLVED = [
    "лифт в {e} подъезде заработал, спасибо",
    "Воду дали, всё нормально",
    "домофон починили",
    "свет в подъезде {e} включили",
]
# Conversation that is not a house problem. Train and val/test use different
# sentences, so the gate threshold is chosen on conversation the model has not seen.
OFFTOPIC_TRAIN = [
    "Соседи, во сколько сегодня собрание?",
    "Кто-нибудь видел рыжего кота у {e} подъезда?",
    "Спасибо всем за помощь с переездом",
    "Продаю детскую коляску, недорого",
    "Доброе утро, соседи!",
    "Кто знает хорошего мастера для ремонта в квартире?",
    "Поздравляем всех с праздником",
    "Во дворе нашли ключи, заберите у консьержа",
    "Когда будет собрание по поводу парковки?",
    "Отличная погода сегодня",
    "У кого есть лишний стул? Нужен на вечер",
    "Напоминаю про субботник в воскресенье",
    "Отдам книги детям бесплатно",
    "Кто едет в центр завтра утром? Подвезите",
    "Спасибо за поздравления!",
    "Приглашаем на праздник двора в субботу",
    "Ищу няню на пару часов вечером",
    "Кто потерял перчатки у {e} подъезда?",
]
OFFTOPIC_EVAL = [
    "Продаю велосипед, почти новый",
    "Всем хороших выходных",
    "Кто знает, во сколько открывается аптека?",
    "Соседи, давайте обсудим озеленение двора",
    "Спасибо, очень приятно",
    "Нашёлся кот, хозяева, откликнитесь",
    "Где лучше купить продукты рядом?",
    "Поздравляю с днём рождения!",
    "Кто пойдёт на концерт в пятницу?",
    "Отличная идея, я за",
    "Можно взять у кого-нибудь дрель на вечер?",
    "Добрый вечер всем",
]
EMERGENCY_CLASSES = {"gas_smell", "water_leak"}


def render(template: str, rng: random.Random) -> str:
    return template.format(e=rng.randint(1, 6), f=rng.randint(1, 16))


def build_rows(rng: random.Random, source: str, split: str, repeats: int) -> list[dict]:
    rows: list[dict] = []
    for name, templates in PROBLEMS.items():
        for _ in range(repeats):
            for template in templates:
                rows.append({"text": render(template, rng),
                             "label": {"class": name, "utterance": "report"}})
    for _ in range(repeats):
        for template in RESOLVED:
            rows.append({"text": render(template, rng),
                         "label": {"class": "elevator_out", "utterance": "resolved_notice"}})
        # Real chats are mostly conversation (problems ≈ 9–12 %); without enough
        # negatives the "precision ≥ 0.80" gate threshold on val degenerates to ~0.
        offtopic = OFFTOPIC_TRAIN if split == "train" else OFFTOPIC_EVAL
        for template in offtopic * 8:
            rows.append({"text": render(template, rng),
                         "label": {"class": "not_a_problem", "utterance": "offtopic"}})
    rng.shuffle(rows)
    for index, row in enumerate(rows):
        row["id"] = f"smoke-{source}-{split}-{index:04d}"
        row["origin"] = "synthetic_smoke"
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    rng = random.Random(SEED)
    out: Path = args.out
    # The loader checks the card for the format marker "v3.0"; the content is synthetic.
    (out / "README.md").parent.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text(
        "# Smoke dataset — folder format v3.0, SYNTHETIC content\n\n"
        "Generated by ml/scripts/make_smoke_data.py from templates. Not the private\n"
        "v3.0 dataset of real chats. Metrics on it prove only that the pipeline runs.\n",
        encoding="utf-8", newline="\n")
    (out / "labels_taxonomy.yaml").write_text(
        "version: smoke\nclasses: [" + ", ".join([*PROBLEMS, "not_a_problem"]) + "]\n",
        encoding="utf-8", newline="\n")
    sizes = {"train": 3, "val": 2, "test": 1}
    for source in ("real_whatsapp", "real_telegram"):
        for split, repeats in sizes.items():
            write_jsonl(out / source / f"{split}.jsonl", build_rows(rng, source, split, repeats))
    synthetic = build_rows(rng, "synthetic", "train", 1)
    for row in synthetic:
        row["annotation"] = {"use": ["gate", "class"]}
    write_jsonl(out / "synthetic" / "train.jsonl", synthetic)
    safety: list[dict] = []
    for split, repeats in sizes.items():
        for row in build_rows(rng, "safety", split, repeats):
            safety.append({"id": row["id"], "text": row["text"], "split": split,
                           "emergency": row["label"]["class"] in EMERGENCY_CLASSES,
                           "origin": "synthetic"})
    write_jsonl(out / "safety" / "emergency_cases.jsonl", safety)
    counts = {split: sum(1 for row in safety if row["split"] == split) for split in sizes}
    print(json.dumps({"out": str(out), "synthetic": True, "safety_rows": counts},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
