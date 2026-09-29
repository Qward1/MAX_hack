# Тестирование ДомСигнала

Какие наборы проверок есть и как их запустить. Каталог кейсов —
[`docs/qa/TEST_CASES.md`](qa/TEST_CASES.md) и
[`docs/qa/TEST_CASES_PROD_MAX.md`](qa/TEST_CASES_PROD_MAX.md), матрица «кейс →
тест» — [`docs/qa/ACCEPTANCE_MATRIX.md`](qa/ACCEPTANCE_MATRIX.md).

## Наборы и запуск

| Набор | Что внутри | Как запустить |
|---|---|---|
| Backend: unit и контракты | ruff, mypy, проверка текстов интерфейса (`scripts/text_lint.py`); правила домена, разбор (`tests/ai`), настройки production, compose | `uv run python scripts/check.py --scope backend` |
| Контракты API | OpenAPI из кода = `docs/openapi.json`, генерируемые типы TS совпадают с закоммиченными, пакеты регионов | `uv run python scripts/check.py --scope contracts` |
| Интеграция | миграции и `tests/integration`: API + воркеры на настоящем PostgreSQL — доступ, заявки, сигналы, опасность, доставка, идемпотентность | `DATABASE_URL=… uv run python scripts/check.py --scope integration` (отдельная БД, её очищают — [`deploy/database.md`](../deploy/database.md)) |
| Фронтенд | типы, компоненты, презентация статусов, клиент API; сборка | `uv run python scripts/check.py --scope frontend` (= `npm --prefix=miniapp run typecheck`, `npm --prefix=miniapp test -- --run`, `npm --prefix=miniapp run build`) |
| Всё перечисленное | четыре набора выше подряд | `DATABASE_URL=… uv run python scripts/check.py --scope all` |
| Браузер | Playwright: кабинеты, мини-приложение на 390 и 1280 px, доступ, вход с TOTP, переключатель темы, обновление без перезагрузки; `ui-lint` — вёрстка всех экранов на 5 ширинах в светлой и тёмной теме | `npm --prefix=miniapp run test:browser` на стенде — переменные и порядок в [`miniapp/README.md`](../miniapp/README.md), «Браузерный стенд» |
| Docker-смоук | сборка и запуск стека `docker compose` в отдельном проекте (порт 18080), вход сотрудника с TOTP, проблема из `POST /api/v1/reports` на месте после перезапуска `api`; в конце стек удаляется | `uv run python scripts/docker_smoke.py` |
| Сквозной с эмулятором MAX | «своя УК с нуля» → подключение группы → `/report` → работа → «Исправлено» → личка → опасность → сигнал | стенд `MAX_TRANSPORT=record PASSIVE_CAPTURE_ENABLED=true docker compose up --build -d`, затем `ACCEPTANCE_BASE_URL=http://127.0.0.1:8000 uv run pytest tests/acceptance` |
| Сценарии | сквозные сценарии продукта через HTTP API и воркер, таблица PASS/FAIL по шагам | `DATABASE_URL=… uv run python scripts/scenario_run.py` |
| Приёмка по матрице | все кейсы TC/ПР из матрицы: автоматически локально, на production только чтение, отметка «нужен человек в MAX» | `uv run python scripts/acceptance_run.py --target local` / `--target prod-readonly` (базы и стенды для `local` — в описании в начале скрипта); отчёт — `output/acceptance/` |
| Проверки API | `DATA-API.yaml`: 24 проверки на production, 12 из них с входом по TOTP, три роли | `uv run python scripts/data_api_check.py` (без входа) или `--accounts <файл>` (формат — [`docs/api/accounts.example.json`](api/accounts.example.json)) |
| ML-модуль | юнит-тесты объединения и слотов; смоук `train → single → chat → eval` на синтетическом смоук-наборе из шаблонов | [`ml/README.md`](../ml/README.md#запуск-в-чистом-клоне-без-закрытых-данных) |
| Вручную в MAX | то, что не повторить эмулятором: клиент MAX на телефоне и в вебе, кнопки под постами, запуск мини-приложения из поста | [`docs/qa/TEST_CASES_PROD_MAX.md`](qa/TEST_CASES_PROD_MAX.md) |

Сборка с чистого клона, перезапуск сервисов и сохранность данных — замеры в
[`DEPLOYMENT.md`](DEPLOYMENT.md) и [`OPERATIONS.md`](OPERATIONS.md). Проверка
выпуска на production — [`RELEASE.md`](RELEASE.md).

## Нестандартные ситуации и безопасность

Поведение при пустом, длинном и бессмысленном тексте, повторах, двойном клике,
отказе модели, остановленном воркере, чужих объектах и несуществующих адресах —
таблица в [`docs/SCENARIOS.md`](SCENARIOS.md#нестандартные-ситуации) с тестом или
проверкой для каждой строки. Проверки безопасности: изоляция УК и ролей
(`test_tenant_access.py`, защита витрины — `test_f1_showcase_guard.py`, роли в
`DATA-API.yaml`), вход (`test_employee_auth.py`: пароль, TOTP, повтор кода,
блокировка, коды восстановления), вебхук без секрета — 401, повтор `POST /reports`
с тем же `Idempotency-Key` — тот же инцидент, тот же ключ с другим телом — 409
`idempotency_conflict`, production отвергает тестовый вход и локальные ключи
(`tests/contract/test_production_*.py`), маскирование перед моделью (`tests/ai`).

## Что проверяют только люди

Клиент MAX на телефоне и в вебе, запуск мини-приложения кнопкой под постом, правка
поста в клиенте, голосование в посте — кейсы с пометкой `human-MAX` в матрице
приёмки. Путь проверяющего в клиенте MAX — [`JURY_GUIDE.md`](../JURY_GUIDE.md).
