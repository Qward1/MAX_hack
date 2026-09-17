# ДомСигнал — implementation context

## Назначение

Рабочий путь продукта: чат или личное сообщение → инцидент → проверяемый маршрут → редактируемый черновик → официальный канал руками пользователя → отметка жителя и наблюдение результата.
Продукт не утверждает, что сам зарегистрировал обращение во внешней системе.

## Текущий этап

- Этап: `BOOT-01` — подготовка репозитория и совместной работы.
- Реально готово: процесс репозитория, документация bootstrap и конфигурация repository-sanity CI.
- Приложение, runtime, БД, API, бот, mini app и продуктовые тесты ещё не реализованы.
- Ключевой рабочий путь продукта пока только согласован, но не исполняется.
- Интегратор по умолчанию: DEV-A. Передача роли фиксируется явной строкой здесь и в решении.

## Возможности и состояния

| Возможность / flag | Состояние | Фактический статус |
|---|---|---|
| Runtime feature flags | PLANNED | Активных runtime-флагов пока нет |
| MAX transport | PLANNED | Локальный режим должен быть `off`; transport не реализован |
| LLM/NLP, media, group mode, reminders | PLANNED | Не реализованы и не проверены |
| Demo/test data | PLANNED | Данные и seed ещё не созданы |
| Live MAX validation | PLANNED | Не выполнялась |

## Согласованные границы

- Один backend-пакет и один runtime image; `api` включает HTTP/webhook, отдельный durable `worker` без Redis на старте.
- Зависимости: API/bot/worker → services → core; бизнес-правила не дублируются во frontend.
- DEV-A: core/services/contracts/db/api/nlp/worker/bootstrap, migrations, regions и основная эксплуатационная конфигурация.
- DEV-B: bot/transport UX, `miniapp`, browser checks, MAX fixtures и пользовательские тексты.
- Общие DTO, migrations, CI и конфигурация меняются согласованно.

## Проверки и совместимость

- Bootstrap: `git diff --check`, проверка обязательных файлов и ссылок выполняется job `repository-sanity`.
- Итоговый обязательный job: `quality-gate`; реальные backend/frontend/contracts/integration проверки подключаются в `FND-01`.
- Опубликованных DTO, миграций и endpoints пока нет.
- Ближайший интеграционный риск: `FND-01` одновременно задаёт DTO/OpenAPI/TS types и UI shell; нужен один writer каркаса и review DEV-B.

## Ссылки

- [DEV-A handoff](docs/status/dev-a.md) · [DEV-B handoff](docs/status/dev-b.md)
- [Roadmap](ROADMAP.md) · [Architecture](docs/ARCHITECTURE.md) · [Contracts](docs/CONTRACTS.md)
