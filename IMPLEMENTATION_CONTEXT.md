# ДомСигнал — implementation context

## Назначение

Рабочий путь продукта: чат или личное сообщение → инцидент → проверяемый маршрут → редактируемый черновик → официальный канал руками пользователя → отметка жителя и наблюдение результата. Продукт не утверждает, что сам зарегистрировал обращение во внешней системе.

## Проверенное состояние

Состояние сверено 2026-09-17 после интеграционного merge `e3ab6b7` и синхронизации
`main` с `dev/b-experience`.

- **IMPLEMENTED:** FND-01 даёт исполняемый backend/runtime, PostgreSQL-модель и
  миграцию, C0 API, test-session/demo seed, durable jobs/worker, режимы MAX
  transport `off`/`recording`, OpenAPI и сгенерированные TypeScript-типы.
- **MERGED TO MAIN:** FND-01, B-00 и реализация B-02 на фактическом C0 API входят
  в `main`; B-02 остаётся **PARTIAL**, пока producer/consumer не сведены с
  целевым B-00 contract.
- **LIVE VERIFIED:** нет. Локальные unit/contract/frontend/PostgreSQL/Docker
  проверки не являются подтверждением работы в реальном MAX или публичном
  production-окружении.
- **NOT LIVE VERIFIED:** реальные MAX web/iOS/Android-клиенты, live initData и
  webhook, MAX-controlled appearance, публичный TLS deploy и внешние providers.
- Интегратор по умолчанию — **DEV-B**. Он обновляет этот файл после значимого
  принятого merge/этапа по проверенному `main`.

## Возможности в проверенном main

| Возможность / flag | Состояние | Фактический статус |
|---|---|---|
| Backend/runtime foundation | IMPLEMENTED · MERGED TO MAIN | FastAPI, services/core, PostgreSQL, Alembic, worker/jobs, Docker и CI quality gate находятся в `main` |
| C0 API и контракты | IMPLEMENTED · MERGED TO MAIN | House-scoped auth, reports/incidents, capabilities, OpenAPI и TS schema работают; B-00 convergence ещё не завершена |
| B-02 mini app | PARTIAL · MERGED TO MAIN | Board/detail/report flow подключён к реальному C0 API; planned actions/read-model/error semantics ещё требуют A-01 convergence |
| MAX transport | IMPLEMENTED LOCALLY · NOT LIVE VERIFIED | Подпись initData и режимы `off`/`recording` реализованы; live webhook/client compatibility не подтверждены |
| Demo/test data | IMPLEMENTED · MERGED TO MAIN | Явные local/test session и demo seed присутствуют; это не реальные пользовательские данные |
| LLM/NLP/ML | NOT IMPLEMENTED | Детерминированный `rules` fallback сохраняет рабочий manual path; AI providers и модели не подключены |
| Media, group mode, reminders | NOT IMPLEMENTED | Не реализованы и не проверены |
| Public deploy / Live MAX validation | NOT LIVE VERIFIED | Реальный MAX и публичный TLS-стенд не проверялись |

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
