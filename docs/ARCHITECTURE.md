# ДомСигнал — фактическая архитектура FND-01

## Статус

Walking skeleton реализован в доступном `dev/a-core@c939ccf`; до merge это не
описание состояния `origin/main@a70df01`. Тот же foundation включён в
`origin/dev/b-experience@c4492dd`, где B-02 остаётся частичным. Реальный slice:
test session → membership → manual report → PostgreSQL `Report`/`Incident` →
REST read → mini app board/detail → повторное чтение после reload. Live MAX,
routes и appeals не реализованы.

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

## Граница AI ↔ product backend

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
