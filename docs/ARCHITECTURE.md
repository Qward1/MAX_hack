# ДомСигнал — фактическая архитектура FND-01

## Статус

Проверенный baseline: `origin/main` и `dev/b-experience` на `3d4a095`
(17.09.2026, после fetch; интеграционный merge `e3ab6b7`). FND-01 (`c939ccf`,
автор DEV-A), B-00 и B-02 (`c4492dd`, DEV-B) включены в main. B-02 — PARTIAL:
C0/B-00 convergence не завершена. Реальный slice: test session → membership →
manual report → PostgreSQL Report/Incident → REST → board/detail → reload.
Live MAX NOT VERIFIED; routes/appeals и новая платформа не реализованы.

## Согласованное направление — TARGET

Единственный продуктовый baseline — [ARCH-PLATFORM-v1](PRODUCT_ARCHITECTURE.md).
Эта техническая карта описывает существующие пути, а не повторяет спецификацию.

| Область | Implemented в проверенном ref | Agreed target / ещё отсутствует |
|---|---|---|
| Доступ | User, House, HouseMembership, house-scoped API | Tenant, HouseManagement с периодом, назначения и основания resident-access; tenant/object isolation |
| Поверхности | Одна React/MAX UI mini app, board/detail/manual report | Общий бот и одна Mini App на все дома; отдельный обычный веб-кабинет сотрудников без Bridge |
| Подключения | Test replay, MAX transport off/recording; live webhook возвращает 503 | Двухсторонний ConnectionRequest, независимая проверка УК/человека/MAX, несколько чатов дома, отзыв и аудит |
| Работа с проблемой | Report и Incident, C0 open/resolved/dismissed | Ticket с очередью/назначением отдельно от Incident и ExternalAppeal; WorkReport отдельно от наблюдения жителя |
| Выполнение | PostgreSQL jobs/lease/retry и worker | Tenant scope и повторная проверка прав перед побочным действием; история без передачи старых данных новой УК |

Расширение остаётся внутри модульного монолита API/webhook + worker + PostgreSQL.
Новые таблицы, auth, frontend entry points и endpoints определяются отдельными
задачами roadmap; пустые модули и второй scaffold сейчас не создаются.

## Runtime

Один Python-пакет `domsignal` и один backend image запускаются в трёх ролях:

- `api`: FastAPI, C0 REST, auth и модуль `/max`;
- `worker`: отдельный цикл PostgreSQL jobs с claim/lease/retry;
- `migrate`/`seed`: одноразовые команды того же image.

PostgreSQL 16 — единственное обязательное хранилище. Redis, RabbitMQ, Kafka,
pgvector, Kubernetes и внутренние HTTP-микросервисы отсутствуют. Caddy входит
только в production overlay и не регистрирует/не меняет MAX webhook.

```text
miniapp React/TS ── typed C0 HTTP ──> api routers
                                          │
normalized test replay ──> inbox + job ───┤
                                          v
                              application services
                              │ membership/session
                              │ report/incident
                              v
                         SQLAlchemy repositories
                              │
                         PostgreSQL 16
                              ▲
worker ── claim/lease ────────┘ ──> MaxTransport(off|recording)
```

## Код и зависимости

```text
src/domsignal/
  core/          enums и чистые названия категорий
  contracts/     Pydantic DTO C0
  services/      membership, sessions, report/incident use cases
  db/            SQLAlchemy models, repositories, session factory
  api/           dependencies, errors, initData, routers
  bot/           normalized ingress и MaxTransport port/adapters
  worker/        handler mapping, claim/lease runner, process entrypoint
  tools/         идемпотентный demo seed
  bootstrap.py   composition root
  main.py        create_app, lifespan и router mounts
miniapp/         React/Vite shell, board, detail, typed client, states
migrations/      одна миграция только используемых таблиц
regions/         JSON Schema и безопасный demo pack
deploy/          Caddyfile без webhook side effects
scripts/         checks, OpenAPI export, region validation, Docker smoke
```

Направление вызовов: `api/bot/worker → services → core`. SQLAlchemy-запросы
находятся только в `db/repositories`; React и ingress не содержат правил
ответственности. `bootstrap.py` явно собирает engine, services, transport и
worker handlers без DI-framework.

## Граница AI ↔ product backend — TARGET

Это логическая граница внутри текущего backend package, а не новый
микросервис. Подробный ownership путей и задач задаёт `ROADMAP.md`.

1. DEV-B принимает запрос, проверяет identity, доступ и допустимый scope текста
   и кандидатов.
2. DEV-A анализирует только разрешённые данные и возвращает типизированный
   результат: категорию, извлечённые поля, ранжированных кандидатов,
   неопределённость, нужные уточнения и состояние выполнения анализа.
3. DEV-B валидирует результат, применяет safety и доменные правила, принимает
   решение, выполняет транзакцию и формирует public API/UI ответ.

AI может предложить похожие инциденты, признаки риска или формулировку, но core
решает, допустимо ли объединение, кому доступны данные, что сохранить и как
вести версии/историю. Safety-путь имеет проверенный deterministic приоритет и
не ждёт модель. LLM не определяет юридическую ответственность, нормативный
срок, внешнюю регистрацию или факт устранения.

AI-specific provider, prompt, evaluation и изолированный job handler принадлежат
DEV-A. Общая очередь, leases, retries, outbox, delivery, registration/wiring и
settings принадлежат DEV-B. Аналогично, dataset модели — зона A, а справочники
домов, нормативные правила и region packs — B; ASR/vision provider — A, а
upload/storage/access/UX вложений — B. Целевые каталоги AI/NLP появятся только
с соответствующей roadmap-задачей; в проверенных refs отдельного AI-модуля пока
нет.

## Транзакционные границы

- `POST /reports` проверяет membership, создаёт Report/Incident, outbox и
  idempotency record в одной транзакции.
- Inbox receipt и job создаются в одной короткой транзакции. Ответ `accepted`
  формируется только после выхода из неё; исключение откатывает обе записи.
- Worker claim использует `FOR UPDATE SKIP LOCKED`, фиксирует lease и завершает
  транзакцию до handler/transport. Завершить job можно только текущим
  `lease_token`; истёкшая аренда доступна recovery-worker.
- Повтор inbound job безопасен благодаря domain idempotency key
  `inbound:<event_id>`. Exactly-once внешней доставки не обещается.

## Auth и окружения

Настройки имеют режимы `local`, `test`, `production`. Test session выдаётся
только отдельным endpoint в local/test; пользовательский header/query не может
включить bypass. Production validation запрещает demo seed/credentials,
test-session, recording transport, HTTP public URL, wildcard CORS и стандартный
session secret.

MAX initData проверяется сервером: уникальные и известные поля, HMAC-SHA256 по
официальному `WebAppData` алгоритму, constant-time compare, возраст и строгий
user payload. После проверки выдаётся короткая opaque session; хранится только
HMAC-хеш токена. LIVE-вектор MAX пока не проверен.

## Надёжность и расширение

Первая миграция содержит только `users`, `houses`, `house_memberships`,
`app_sessions`, `reports`, `incidents`, `idempotency_records`,
`inbox_receipts`, `jobs`, `outbox_messages`. Следующие задачи добавляют модели
отдельными миграциями; опубликованная revision не переписывается.

Точки подключения:

- A-01: DEV-B согласует C0/B-00 и расширяет public `contracts`/generated types
  совместимым producer+consumer-срезом, не заменяя C0 фиктивным API;
- A-02/A-04: DEV-B расширяет rules, services, API и persistence;
- A-03: DEV-A реализует NLP/извлечение/детектор риска, DEV-B — intake
  orchestration и применение safety-политики;
- A-05: DEV-B развивает общие job kinds, outbox sender и delivery в worker;
- A-06: DEV-A возвращает semantic scores/candidates, DEV-B принимает доменное
  решение и отвечает за counts, persistence и concurrency;
- B-02/B-03: реальный MAX transport и payload adapter за `MaxTransport` и
  normalized ingress, Owner DEV-B;
- B-02/B-05: mini app использует generated schema и capability flags;
- A-02/A-11: DEV-B ведёт проверенные region packs по `regions/schema.json`;
- A-14: DEV-B ведёт attachment/storage/API, DEV-A подключает ASR/vision только
  при согласованном scope и реальном provider.

Неиспользуемые будущие директории и фиктивные endpoints не созданы.
