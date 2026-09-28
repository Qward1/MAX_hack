# Тестирование ДомСигнала

Что проверяется, как запустить и что показал последний прогон финальной версии
(28.09.2026). Каталог кейсов — [`docs/qa/TEST_CASES.md`](qa/TEST_CASES.md) (99 TC) и
[`docs/qa/TEST_CASES_PROD_MAX.md`](qa/TEST_CASES_PROD_MAX.md) (61 ПР), матрица «кейс →
тест» — [`docs/qa/ACCEPTANCE_MATRIX.md`](qa/ACCEPTANCE_MATRIX.md).

## Уровни и запуск

| Уровень | Что внутри | Как запустить |
|---|---|---|
| Unit и контракты | правила домена, разбор (`tests/ai`), настройки production, compose, OpenAPI = код, генерируемые типы TS, пакеты регионов | `uv run python scripts/check.py --scope backend` и `--scope contracts` |
| Интеграция | API + воркеры на настоящем PostgreSQL: доступ, заявки, сигналы, опасность, доставка, миграции, идемпотентность | `DATABASE_URL=… uv run python scripts/check.py --scope integration` |
| Фронтенд | типы, компоненты, презентация статусов, клиент API | `npm --prefix miniapp run typecheck`, `npm --prefix miniapp test -- --run` |
| Браузер | Playwright: кабинеты, мини-приложение на 390 и 1280 px, доступ, вход с TOTP, обновление без перезагрузки; `ui-lint` — вёрстка 39 экранов × 5 ширин × 2 темы | стенд и переменные — [`miniapp/README.md`](../miniapp/README.md), «Браузерный стенд»; `npx playwright test` |
| Сквозной с эмулятором MAX | «своя УК с нуля» → подключение группы → `/report` → работа → «Исправлено» → личка → опасность → сигнал | `ACCEPTANCE_BASE_URL=… uv run pytest tests/acceptance` на стенде `MAX_TRANSPORT=record` |
| Сценарии | 38 шагов 10 сценариев через HTTP API и воркер | `DATABASE_URL=… uv run python scripts/scenario_run.py` |
| Приёмка по матрице | все кейсы TC/ПР: авто-локально, авто-production, «нужен человек в MAX» | `scripts/acceptance_run.py --target local` / `--target prod-readonly` |
| Проверки API | 24 проверки `DATA-API.yaml` на production, три роли | `uv run python scripts/data_api_check.py --accounts <файл>` |
| ML-модуль | 7 юнит-тестов объединения и слотов; смоук `train → single → chat → eval` на синтетике | [`ml/README.md`](../ml/README.md#запуск-в-чистом-клоне-без-закрытых-данных) |
| Вручную в MAX | то, что не повторить эмулятором: клиент MAX на телефоне и в вебе, кнопки под постами, запуск мини-приложения из поста | [`docs/MAX_LIVE_SMOKE.md`](MAX_LIVE_SMOKE.md), `docs/qa/TEST_CASES_PROD_MAX.md` |

## Последний прогон — финальная версия, 28.09.2026

| Проверка | Результат |
|---|---|
| Backend: ruff, mypy (193 файла), unit и контракты | **1 073 passed** |
| Контракты: OpenAPI из кода = `docs/openapi.json`, типы TS, пакеты регионов | пройдено |
| Интеграция на PostgreSQL 16 | **537 passed** (CI на `ff5573c`, с первого раза; `test_claim_uses_the_partial_pool_index` проверяет план запроса PostgreSQL и зависит от статистики таблицы — локально однажды прошёл только при повторе) |
| Фронтенд: типы, 31 файл тестов | **343 passed**, сборка без ошибок |
| Браузер (Playwright, Chrome) | **78 passed, 0 failed** на свежем стенде, в том числе `ui-lint` — 39 экранов × 5 ширин × 2 темы без нарушений; 10 спеков-снимков запускаются только с `UX_SNAPSHOTS=1`; спек `notifications.spec.ts` требует жителя с MAX-идентичностью в фикстурах — тот же путь покрыт `test_notifications.py` (20) и сквозным TC-035 с эмулятором |
| Сквозной с эмулятором MAX (`tests/acceptance`) | **15 из 15** |
| Сценарии (`scenario_run.py`) | **38 из 38** шагов |
| ML-модуль | 7 из 7 юнит-тестов; смоук-цепочка на синтетике — работает |
| `DATA-API.yaml` на production | 24 из 24 на финальном коммите: «без входа: 12 из 12», «с входом по TOTP: 12 из 12» ([`FINAL_JURY_READINESS_REPORT.md`](../FINAL_JURY_READINESS_REPORT.md)) |
| Чистый клон → `docker compose build --no-cache` → `up` | сборка 34 с, `/ready` через 20 с |
| Перезапуск `api`, `worker`, `ai-worker`, `db`, весь стек | готов за 0–4 с, данные на месте; при остановленном `worker` приём работает, задачи ждут |
| Повтор `POST /reports` с тем же `Idempotency-Key` | тот же инцидент; тот же ключ с другим телом — 409 `idempotency_conflict` |
| gitleaks | история с прошлого выпуска — 0 находок; рабочее дерево — только шаблоны `replace_with_…` |

Производственные проверки после выкладки — в
[`FINAL_JURY_READINESS_REPORT.md`](../FINAL_JURY_READINESS_REPORT.md).

## Нестандартные ситуации и безопасность

Поведение при пустом, длинном и бессмысленном тексте, повторах, двойном клике,
отказе модели, остановленном воркере, чужих объектах и несуществующих адресах —
таблица в [`docs/SCENARIOS.md`](SCENARIOS.md#нестандартные-ситуации) с тестом или
проверкой для каждой строки. Проверки безопасности: изоляция УК и ролей
(`test_tenant_access.py`, `test_f1_showcase_guard.py`, роли в `DATA-API.yaml`), вход
(`test_employee_auth.py`: пароль, TOTP, повтор кода, блокировка, коды восстановления),
вебхук без секрета — 401, production отвергает тестовый вход и локальные ключи
(`tests/contract/test_production_*.py`), маскирование перед моделью (`tests/ai`).

## Что проверяют только люди

Клиент MAX на телефоне и в вебе, запуск мини-приложения кнопкой под постом, правка
поста в клиенте, голосование в посте — кейсы с пометкой `human-MAX` в матрице
приёмки (14 кейсов). Последние живые проверки — `docs/MAX_LIVE_SMOKE.md` (19–27.09);
перед сдачей владелец проходит сценарий 1 из [`JURY_GUIDE.md`](../JURY_GUIDE.md) в
клиенте MAX.
