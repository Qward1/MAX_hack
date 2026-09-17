# ДомСигнал — implementation context

## Назначение

Рабочий путь продукта: чат или личное сообщение → инцидент → проверяемый маршрут → редактируемый черновик → официальный канал руками пользователя → отметка жителя и наблюдение результата. Продукт не утверждает, что сам зарегистрировал обращение во внешней системе.

## Проверенное состояние

Состояние сверено 2026-09-17 после одного fetch.

- **MERGED:** `origin/main@a70df01` содержит только bootstrap совместной работы и repository-sanity. Runtime, БД, API, bot и mini app в проверенном `main` не реализованы.
- **IMPLEMENTED IN BRANCH:** foundation находится в доступном `dev/a-core@c939ccf`; `origin/dev/b-experience@c4492dd` содержит включённый foundation и частичный B-02. Это не готовность `main`; детали и проверки хранятся в status владельцев.
- **LIVE VERIFIED:** реальный MAX, публичный deploy и внешние providers не проверены.
- Интегратор по умолчанию — **DEV-B**. Он обновляет этот файл после значимого принятого merge/этапа по проверенному main/ref. Наличие кода в dev-ветке само по себе не меняет состояние выше.

## Возможности в проверенном main

| Возможность / flag | Состояние | Фактический статус |
|---|---|---|
| Runtime feature flags | PLANNED | Активных runtime-флагов в `origin/main@a70df01` нет |
| MAX transport | PLANNED | Локальный режим должен быть `off`; live transport не подтверждён |
| LLM/NLP, media, group mode, reminders | PLANNED | Не реализованы и не проверены в main |
| Demo/test data | PLANNED | В main данные и seed отсутствуют |
| Live MAX validation | PLANNED | Не выполнялась |

## Согласованные границы

- Один backend-пакет и один runtime image; `api` включает HTTP/webhook, отдельный durable `worker` работает без Redis на старте.
- Зависимости: API/bot/worker → services → core; бизнес-правила не дублируются во frontend или bot handlers.
- DEV-A владеет AI/NLP/ML: подготовкой текста для моделей, извлечением и классификацией, providers/prompts, structured output, semantic ranking, AI-specific resilience, datasets/evaluation и выделенным backend-кодом этих модулей.
- DEV-B владеет продуктовым контуром: mini app/MAX/bot, public API/contracts, core/services, incidents/appeals, DB/migrations, auth, rules/regions, общей jobs/outbox инфраструктурой, admin/analytics, deploy/CI/release и end-to-end интеграцией.
- DEV-B передаёт AI только разрешённый scope; DEV-A возвращает типизированный аналитический результат; DEV-B валидирует его, применяет бизнес-правила и выполняет транзакцию. Manual/deterministic путь остаётся рабочим без LLM.
- Каноническая матрица путей, shared writers и Owner задач находится в `ROADMAP.md`.

## Ближайший интеграционный риск

B-02 остаётся PARTIAL: C0 producer расходится с B-00 target по structured `allowed_actions`, provenance/freshness, capabilities, count semantics, read-model полям и errors. Следующий backend-срез **DEV-B** — существующая A-01, минимальная C0/B-00 convergence с producer+consumer+generated types+tests. Это не требует публиковать неподдержанные действия. DEV-A review обязателен; отсутствие convergence не переносит общий backend обратно DEV-A.

## Ссылки

- [DEV-A handoff](docs/status/dev-a.md) · [DEV-B handoff](docs/status/dev-b.md)
- [Roadmap](ROADMAP.md) · [Architecture](docs/ARCHITECTURE.md) · [Contracts](docs/CONTRACTS.md)
