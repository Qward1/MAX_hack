# DEV-A — current handoff
Updated: 2026-09-20T15:30:00+03:00
Branch: `agent/a/a03-ai-core` (worktree от `origin/dev/b-experience`)
Current task: A-03/AI + A-17/AI — AI-ядро на правилах (P1)
State: IMPLEMENTED IN BRANCH / NOT MERGED

## Active/recent tasks

| ID | State | Result / blocker | PR or tested reference |
|---|---|---|---|
| BOOT-01 | BASELINE | Repository workflow was present on main before this task | `a70df01` |
| FND-01 | READY_FOR_REVIEW | C0 UI→API→PostgreSQL slice, auth boundary, jobs, generated contracts, Compose/Caddy and real checks implemented; live MAX remains not verified | local `dev/a-core`; PR pending owner action |
| A-03/AI + A-17/AI | IMPLEMENTED IN BRANCH | Детерминированное ядро разбора окна: таксономия v2, правила, fallback, fusion, сила сигнала, guard, интерфейс провайдера, датасеты и оценка | `agent/a/a03-ai-core`; `scripts/check.py --scope backend` PASS |
| A-08 / P2 | NEXT | Реальный провайдер polza.ai за готовым интерфейсом; нужен ключ, бюджет и промпт окна | Зависит от решения владельца по ключу и лимитам |

## Result

Одно ядро разбирает окно реплик; одиночное сообщение — окно из одной реплики,
поэтому явный путь (форма, `/report`) и пассивное чтение чата используют один
и тот же «пол» понимания.

- `src/domsignal/ai/` — контракт окна, таксономия подтипов v2 (31 код),
  нормализация с картой позиций, маскирование, правила опасности, места,
  времени, территории и ролей, вариант C для режима без модели, строгая схема
  ответа модели с экспортом JSON Schema, семантический валидатор, Emergency
  Fusion с журналом аудита, сила сигнала и разделение Inbox/Audit Pool, guard
  `no_new_facts`, Protocol провайдера с детерминированным Fake и фасад
  `WindowAnalyzer`, который не бросает исключений.
- `screen_message_for_danger(text)` — чистая функция без I/O и исключений для
  вызова в транзакции приёма webhook: p95 < 5 мс, отрицание и «не у нас / не
  сейчас» фиксируются отдельными флагами.
- Ответственность ядро не определяет. Организаций, каналов, телефонов, сроков,
  статусов, уверенности и текстов для жителя в пакете нет.
- `datasets/synthetic/` — 98 одиночных сообщений, 10 инцидентов с 22 запросами
  и поток из 63 реплик, перенесённые из эксперимента E0/E0b/E0c без правки
  текстов, плюс новый набор территории и контекстной опасности.
- `evaluation/run_eval.py` — воспроизводимый отчёт с интервалами Уилсона.

## Checks

- `uv run python scripts/check.py --scope backend` — **PASS**: ruff, mypy
  strict, 264 теста (unit + contract + ai), ~10 с.
- `uv run python evaluation/run_eval.py --provider rules --out evaluation/reports/`
  — воспроизводим: два прогона дают одинаковый JSON, кроме `generated_at`.
  Все регрессионные полы PASS.
- `uv build --wheel` во временный каталог вне репозитория — в wheel есть
  `domsignal/ai/resources/taxonomy.v2.yaml`, `lexicon.r1.yaml` и
  `schemas/window_output.v1.json`.
- Изменений БД, API, worker, bot, miniapp, settings, bootstrap и зависимостей
  нет. Единственная правка общего файла — две строки в `scripts/check.py`.

## Not verified / blockers

- Реальный провайдер LLM не подключён: это P2. Промпт окна и модель в
  `versions` — `None`.
- Все числа оценки — **внутривыборочная синтетика**: авторы данных и правил
  пересекаются. Настоящий контроль — наборы P6 (смоделированный чат в MAX,
  набор опасности от другого автора, локальные замеры на реальных выгрузках).
- Реальные выгрузки чатов из `data/` не открывались и не использовались.
- Семантическая опасность проверена только через Fake-провайдера с заданными
  ответами; поведение реальной модели на контекстных окнах неизвестно.

## Next

P2 — провайдер polza.ai за готовым `AnalysisProvider`: адаптер
`openai_compatible`, промпт окна v1 поверх уже экспортированной JSON Schema,
таймаут, circuit breaker и семафор, отбор моделей на синтетических окнах.
Нужны от владельца: ключ, дневной бюджет и подтверждение, что на хакатон
уходят только тестовые и синтетические данные.

## For teammate (DEV-B)

Для Responsibility Router (P3a) готовы стабильные коды подтипов и значения
предварительной территории.

**`location_scope`:** `apartment`, `house_common`, `house_territory`,
`municipal_territory`, `external_network`, `other_building`, `unknown`.
Значение приходит только с цитатой; без цитаты — всегда `unknown`.

**Подтипы таксономии v2** (`code | product_category | dedupe_scope`):

| Код | product_category | dedupe_scope |
|---|---|---|
| `gas.smell` | other | house |
| `gas.supply_outage` | other | house |
| `elevator.button` | elevator | object |
| `elevator.doors` | elevator | object |
| `elevator.stopped` | elevator | object |
| `roof.leak` | water | object |
| `water.leak` | water | object |
| `water.hot_outage` | water | house |
| `water.supply_outage` | water | house |
| `water.quality` | water | house |
| `water.pressure` | water | house |
| `heating.cold_radiators` | other | house |
| `electrical.panel` | lighting | object |
| `power.grid_outage` | lighting | house |
| `street_lighting.failure` | lighting | object |
| `lighting.yard` | lighting | object |
| `lighting.stairwell` | lighting | object |
| `waste.chute` | waste | object |
| `waste.container_site` | waste | house |
| `waste.removal_regional` | waste | house |
| `intercom.broken` | other | object |
| `entrance_door.broken` | other | object |
| `cleaning.stairwell` | other | house |
| `snow.street` | other | object |
| `snow.yard` | other | house |
| `playground.damaged` | other | object |
| `landscaping.public` | other | object |
| `road.damage` | other | object |
| `structure.damage` | other | object |
| `external_network.outage` | other | house |
| `other.unspecified` | other | house |

Точки входа: `WindowAnalyzer.analyze(window) -> WindowAnalysis`,
`decide_explicit_report(analysis)` для формы и `/report`,
`screen_message_for_danger(text)` для транзакции приёма,
`domsignal.ai.windowing.build_windows` для сборщика окон.
`product_category` — это код заявки, если её всё-таки создаёт УК; это **не**
утверждение о том, что проблема входит в зону ответственности УК.
