# ДомСигнал — фактическая архитектура FND-01

## Статус

Проверенный baseline: `origin/main` и `dev/b-experience` на `3d4a095`
(17.09.2026, после fetch; интеграционный merge `e3ab6b7`). FND-01 (`c939ccf`,
автор DEV-A), B-00 и B-02 (`c4492dd`, DEV-B) включены в main. B-02 — PARTIAL:
C0/B-00 convergence не завершена. Реальный slice: test session → membership →
manual report → PostgreSQL Report/Incident → REST → board/detail → reload.
Live MAX NOT VERIFIED; routes/appeals и новая платформа не реализованы.

## A-07 — IMPLEMENTED IN BRANCH, 18.09.2026

`dev/b-experience` extends A-15 with existing MAX chat connections; not MERGED TO
MAIN and not LIVE VERIFIED. Evidence: [DEV-B](status/dev-b.md),
[CB acceptance](../scenarios/acceptance.md), [live runbook](MAX_LIVE_SMOKE.md).

- MAXChat is a local snapshot identified only by unique external `max_chat_id`.
  Title/owner metadata never selects house, tenant or permissions. Groups already
  exist; no API creates them. Channels/dialogs cannot bind in this MVP.
- ConnectionRequest stores SHA-256 of a random 256-bit opaque token, TTL (default
  15 minutes), initiating employee, claimed MAX identity, candidate chat and scope.
  Raw token appears only in the first response, never inbox/job/outbox/receipts.
  Central lifecycle: created → connector_claimed → chat_detected → max_verified
  → awaiting_approval → completed; same-company authorized connector can skip
  awaiting_approval, but explicit approval is always required. Expired/cancelled/
  rejected are terminal. Duplicate initiation returns the existing request without
  reissuing its token; cancellation + new initiation recovers a lost token.
- ChatBinding has pending/active/suspended/revoked and house/entrance scope.
  Composite FK `(management_id, house_id)` follows Incident consistency. Partial
  unique index allows only one active binding per external chat. Different chats
  may bind the same house. Immutable binding scope/version requires a new flow for
  reactivation/reassignment. MAXChat increments a version across all its bindings.
- Lock order is physical house (shared), chat advisory lock, connection row. The
  per-chat lock also serializes absence checks and activation; the DB unique index
  is independent protection. Approval atomically verifies current employee access,
  management/company, MAX rights, TTL and conflict, creates binding and lifecycle
  outbox event, and completes the request. No separate auth/context/audit framework.
- `chat.connect` is an AccessPolicy permission for company_admin or active company
  operator with responsible assignment. MAX identity/admin role is separate.
  Connector claim is correlation only. One open request per connector prevents
  ambiguous bot_added association; unrelated events retain only an unbound snapshot.
- `bot/chat_provider.py` is the typed read-only HTTPX provider. Configured HTTPS
  origin defaults to platform-api2.max.ru, timeout 5 seconds, header authorization,
  strict typed mapping, sanitized 401/403/404/429/5xx/errors. No automatic polling,
  subscription changes or production fake. Test double lives only in tests/fakes.
  Off/recording mode cannot call MAX, even if a token is configured.
- `/max/webhook` validates the configured secret before parsing/persistence. Typed
  Update mapping accepts bot_started/bot_added/bot_removed/message_created; unknown
  types are acknowledged without product effect. Inbox identity is deterministic
  (chat+mid for messages, lifecycle type/time/chat/actor otherwise). Receipt + state
  changes/jobs commit before 200; concurrent delivery is serialized. Lifecycle
  timestamps prevent older add/remove events from undoing newer installation state.
- Group intake is explicitly `/report <category> <description>`, using existing
  manual categories and existing ReportService core transaction. A-07 does not
  enable B-06 auto-group/NLP. Unbound chats and ordinary conversation are ignored;
  no message text is persisted for those paths. Group authors still need their
  existing ResidentMembership/employee access; no automatic membership import.
- Eligible active-chat jobs capture binding ID/version and event time on receipt.
  Worker health checks then re-resolves the immutable OperationContext inside the
  write transaction, using binding → management → tenant/house and existing policy.
  Stale binding/version, pre-activation event and revoked user rights fail closed.
  Entrance is verified context, preserved in outbox; text never changes scope.
  New outbound group sending is not implemented. Future senders must use the same
  active/version guard immediately before their side effect.
- bot_removed suspends idempotently with BOT_REMOVED. Worker-callable health service
  suspends on missing bot admin/permission, inaccessible chat or unknown API state.
  There is no periodic scheduler. Each group report performs health verification.
  Management status/end trigger suspends with MANAGEMENT_ENDED; natural expiry is
  checked by health/access resolution. No binding transfers to the successor UK.
- Signed Mini App chat/start_param remain ignored as authority; A-15 resolver and
  policy still control personal reads/writes. New chat-selector UX is not added.
- Migration 0003 is additive, creates no active/demo bindings and preserves A-15
  rows. Empty A-07 downgrade works; any connection/chat/job history requires a
  pre-A07 backup rather than destructive rollback. No new broker/service/DB port.

## A-15 — IMPLEMENTED IN BRANCH, 18.09.2026

Текущая `dev/b-experience` содержит A-01 и A-15 поверх main baseline выше.
Это не MERGED TO MAIN и не LIVE VERIFIED; evidence — [DEV-B](status/dev-b.md).

- `db/models/access.py`: ManagementCompany = tenant; House не имеет tenant_id.
  HouseManagement хранит tenant, house, `[valid_from, valid_to)`, status, basis,
  created_by, timestamps и demo provenance. OrganizationMembership — active/revoked
  company_admin/operator; HouseAssignment — active/revoked responsible/operator
  на management. ResidentMembership (бывшая house_memberships) — на House,
  источник/verification/expiry/status, без claims о собственности/проживании.
- `core/access.py` — компактная AccessPolicy; `services/membership.py` расширяет
  существующий resolver. `/me` и отдельные запросы читают текущие основания,
  без role cache в session. Staff требует active company и organization membership;
  operator дополнительно требует assignment. Superadmin не получает private read.
- `Incident` имеет non-null management_id и house_id, composite FK на
  `HouseManagement UNIQUE(id, house_id)`. Триггеры запрещают перепривязать
  incident scope и management tenant/house, сохраняя историческую принадлежность.
- `services/management.py` — внутренние create/switch в транзакции вызывающего;
  public admin endpoints/UI отсутствуют. Валидация периода + overlap query;
  `btree_gist` exclusion по house и `tstzrange(..., '[)') WHERE status='active'`
  закрывает в том числе конечные/будущие периоды и concurrent inserts. Null верхняя
  граница — бесконечность; соседние периоды разрешены. DB CHECK запрещает пустой
  или обратный период. Это один PostgreSQL constraint, без temporal framework.
- House row lock: management mutation — FOR UPDATE; report creation — FOR SHARE
  до commit, затем resolver использует текущее время после получения lock.
  Все будущие management mutations должны соблюдать этот протокол.
- Incident repository принимает context и фильтрует house + management; content
  чужого объекта не строит DTO. До resolver допустим только house routing ID.
  Чужой/отсутствующий scope → одинаковый 404; отсутствующий action permission в
  известном scope → 403. Query/body tenant/role не источник прав.
- Смена управления сохраняет старые incidents и assignments; новые операции
  относятся к новому management. Доска/detail ограничены текущим management,
  включая жителей. Resident basis переживает switch; архив/own-history endpoint
  не создан. Новая УК автоматически не получает старую историю.
- Индексы: management house/tenant и partial active house+valid_from;
  unique user+tenant, user+management, user+house для оснований;
  incident house+status, management+status. Partitioning/sharding отсутствуют.
- `20260918_0002` сохраняет C0.1 ID/тексты/reports/receipt; demo company + management
  явны. Legacy non-demo получает отдельный suspended/unverified management,
  без недоказанных production claims. Старый resident role/evidence сохранён,
  но не предоставляет organization rights. Downgrade C0 backfill проверен;
  при новых assignments/org memberships/revokes/switch/platform roles rollback
  запрещён, нужен backup. Это предотвращает потерю новых прав и возврат отозванных.

PostgreSQL + asyncpg — **единственный runtime**, включая local/backend/worker/tests.
Settings и engine factory отвергают SQLite и другие dialects. Runtime SQLite
fallback/dependency не было; unrelated ignore patterns сохранены. Deployment,
private Docker network, pg_dump/restore — [database runbook](../deploy/database.md).
MAX bindings, Ticket, onboarding и admin UI этим срезом не начаты.

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

### Personal MAX delivery — IMPLEMENTED IN BRANCH, 18.09.2026

A-05/B-03 consume the existing A-16 `ticket.notification_intent.v1` outbox.
One short transaction claims an intent with SKIP LOCKED, validates its stored
TicketEvent, materializes unique per-author NotificationDelivery rows and marks
existing work cards for reconciliation. Only then is the intent processed.
There is no second business outbox, scheduler or broker. The same WorkerRunner
advances delivery and existing jobs; off mode consumes intents but makes no MAX calls.

NotificationDelivery stores recipient, Ticket/WorkAttempt, random unique launch ref,
personal destination, provider mid, desired/applied Ticket versions, attempts,
lease, retry time and sanitized error. Pending/processing/accepted/retry_wait/
unknown/failed/superseded/skipped are delivery states, never Ticket states.
Before send/edit/answer, fresh MembershipService/AccessPolicy, own Report,
current management and verified MAX identity are required. Old unsent attempts
are superseded; accepted work cards render current ResidentWorkStatus and edit.
Network runs outside every Ticket/house lock and DB transaction. A revocation
committed after the final check cannot retract an already in-flight HTTP request;
subsequent actions and retries recheck access. No atomic DB+MAX guarantee is claimed.

MAX identity confirmation is additive `User.max_identity_verified_at`, written
by the existing validated initData session path. Legacy IDs are not backfilled.
There is no global User revocation model in A-15; active resident access and current
management remain the authoritative revocation boundary. No subscription model
exists: candidates are distinct Report authors only. No house/group broadcast.

All three messaging methods share A-07 MaxHttpClient/settings and a PostgreSQL
per-destination gate (minimum 500 ms between operations; independent dialogs).
90-second leases exceed the bounded total HTTP timeout. Send lease expiry or
ambiguous response becomes unknown with no automatic resend. Rejected 429/connect
failures retry up to five attempts with exponential backoff; edit/answer retries
are durable. A-16 callback observation and the existing answer Job commit together;
failure of MAX cannot roll back an observation. Mini App mutations use the same
A-16 path and trigger edits through outbox reconciliation.

Migration `2aea407269aa` is additive, creates no accepted deliveries or verified
identities, and guards downgrade when delivery/identity history exists. Deterministic
recording/HTTP fixture providers live only in tests and require explicit injection;
production composition always selects HttpMaxMessagingProvider, including safe off.
Evidence and limits: [DEV-B](status/dev-b.md), [ND matrix](../scenarios/acceptance.md#nd--personal-max-delivery).

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

**A-16 — IMPLEMENTED IN BRANCH `dev/b-experience`:** Ticket + история решений/работ + типизированное
доменное событие/намерение уведомить фиксируются согласованно в одной транзакции
через существующий PostgreSQL transactional outbox. WorkAttempt хранит отчёт,
ResultObservation — наблюдение конкретной попытки. A-05/B-03 выполняют сеть
после commit и ведут отдельный delivery state: сбой MAX не откатывает Ticket,
неизвестный send не превращается в exactly-once. Нового broker нет.
Перед отправкой повторно проверяются адресаты и актуальный management/binding/access.
Типы и факты сроков приходят через контракт A-02/A-11/Product, нормы не
зашиваются в Ticket state machine. [Семантика A-16 и API DoD](CONTRACTS.md),
[процесс и №416](PRODUCT_ARCHITECTURE.md#сквозной-max-путь--planned).

`core/tickets.py` — центральные transitions, `services/tickets.py` — проверка
OperationContext/AccessPolicy, idempotency, проекции и атомарные команды;
`db/models/tickets.py` / migration 0004 — Ticket, WorkAttempt, ResultObservation,
TicketEvent, TicketDeadline. Tenant не копируется в Ticket. `ReportService`
вызывает ensure в своей транзакции после принятия Report; один общий путь для
API и A-07. HouseManagement flag default false, диагностический replay исключён.

Write lock order: House SHARE (A-15) → Incident FOR UPDATE → Ticket/Attempt.
Incident — единая граница создания/возобновления/попыток/наблюдений, включая
проверку отсутствия Ticket. Partial unique active Incident — независимая защита
БД. Staff expected_version проверяется под блокировкой, observations получают
серверную revision и не теряются при изменении версии другим жителем.
Повторный report intake сериализует существующий idempotency key через
PostgreSQL advisory transaction lock в ReliabilityRepository; process-local
locks и второй механизм receipts не добавлены. Приватные данные не хранятся
в receipt Ticket — только IDs/версия эффекта; replay строит свежую проекцию.

Outbox использует существующую таблицу с nullable unique dedupe_key; новый
consumer описан выше. Жизненный цикл и permissions не
меняют Incident.status, capabilities/действия существующей Mini App и AI.

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
