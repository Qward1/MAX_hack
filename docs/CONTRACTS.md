# ДомСигнал — UX/API contract v0.1

## Статус

B-00 ниже сохраняет TARGET будущих workflows. **A-01 / C0.1 IMPLEMENTED IN
BRANCH `dev/b-experience`, 18.09.2026**: producer, consumer, OpenAPI и TS сведены
одним срезом. B-02 board/detail binding повторно проверен и DONE в ветке.
Baseline до среза: `804f198`; MERGED TO MAIN для A-01 не заявляется.
Live MAX Web/iOS/Android — NOT VERIFIED.

Опубликованы прежние C0 auth/me/capabilities/reports/incident endpoints и
диагностический replay. Analyze, appeals, join, feedback, admin, routes и
filing endpoints остаются TARGET. Перечень ошибок/полей C0.1 ниже отделён от
исторического C0 и полного B-00 target. Новых таблиц/миграций в A-01 нет.

Backend является source of truth для incident status, matching, route,
provenance, capabilities и `allowed_actions`. DEV-B отвечает за public DTO,
OpenAPI, generated TypeScript, их применение в core/services и транзакции.
Frontend не вычисляет права и не hardcode региональные правила. Deep link
передаёт navigation context, но не access grant.

Согласованная foundation boundary сохраняется: Pydantic/FastAPI → OpenAPI →
generated TypeScript types; внешние MAX identifiers на JSON-границе — строки,
время — timezone-aware UTC; API и bot вызывают общие services и не отдают ORM;
контракт меняется совместимо либо одним набором producer + consumer + generated
types + tests. AI-specific внутренний контракт пишет DEV-A, а его совместимую
границу с продуктом DEV-A и DEV-B проверяют вместе.

## A-07 connection contract — IMPLEMENTED IN BRANCH

18.09.2026, on A-15. No main merge or live MAX claim. Public external IDs remain
strings; timestamps are UTC. Pydantic → OpenAPI → generated TS remain canonical.

| Endpoint | Authority / result |
|---|---|
| `POST /api/v1/houses/{house_id}/chat-connections` | Existing session + `chat.connect`; body `scope_type=house`/null or `entrance`/nonempty `scope_value`; derives current management/tenant; 201 ConnectionView |
| `GET /api/v1/chat-connections/{id}` | Current authorized employee of the same management; ConnectionView, no token replay |
| `POST /api/v1/chat-connections/{id}/approve` | Body `confirm: true`; fresh AccessPolicy + MAX verification; 200 BindingView; duplicate returns same active binding |
| `POST /api/v1/chat-connections/{id}/reject` | Authorized employee; terminal rejected ConnectionView |
| `POST /api/v1/chat-connections/{id}/cancel` | Authorized employee; terminal cancelled ConnectionView |
| `POST /max/webhook` | Explicit webhook mode + constant-time `X-Max-Bot-Api-Secret`; committed InboundAccepted, HTTP 200; off gives 503 |

ConnectionView includes id/house/status/expiry/candidate external chat/scope/error,
optional completed binding ID/version. `correlation_token` is present only on first
creation. Repeated initiation of the same open employee+management+scope returns
that request with token null; cancel/recreate if the one-time response was lost.
No public tenant, management, role or client chat override fields are accepted.
A deep link is not synthesized without a known real bot identity; caller receives
the opaque correlation payload. No management addresses/titles of foreign bindings
are returned in conflict errors.

Request states: created → connector_claimed → chat_detected → max_verified →
awaiting_approval → completed. A connector with the same persisted MAX identity
and current company authority may confirm directly from max_verified. External
connector waits for the target company; no mandatory Superadmin step. All paths
still require explicit approval. expired/cancelled/rejected are terminal.
Binding states: pending → active → suspended/revoked, suspended → revoked.
Reactivation always creates a new request/binding and increases chat-wide version.
Revoke is currently an internal authorized service, not a full administration API.

Problem Details uses existing lowercase machine codes: connection_expired,
connection_not_detected, connection_not_verified, connection_invalid_transition,
connection_changed_retry, connector_not_chat_admin, bot_permission_missing,
chat_already_bound, management_not_active, tenant_suspended, binding_not_active,
stale_binding_version; sanitized max_* codes identify provider failures.
Foreign scope is masked 404; visible scope without action is 403; conflict is 409;
provider unavailability during approval is 503/retryable. Verification failures
remain pending/error with no active binding. Failed verification/expiry persists.
No raw upstream responses or secrets appear in errors.

The internal provider returns ChatInfo/ChatMember, never raw MAX JSON to core.
The worker registers max.connection.verify, max.binding.health, max.group.report.
The report job contains chat ID, binding ID/version, user identity, event time and
explicit command text. Resolve/access/version validation precedes product core.
A-07 group command is `/report <elevator|water|lighting|waste|other> <description>`
(5–2000 characters); it reuses manual ReportCreate semantics. Ordinary conversation
is ignored; auto-group NLP is a separate task. `group_mode` capability is not
promoted to a live-ready automatic feature. Personal/manual APIs stay unchanged.

Mini App signed chat/start_param do not grant access or create ResidentMembership;
this version keeps the existing explicit authorized house flow. No participant sync.
More implementation/limits: [architecture](ARCHITECTURE.md) and
[real MAX checklist](MAX_LIVE_SMOKE.md).

## Общие значения

### Capabilities

`UserContext.capabilities` обязательно содержит boolean-поля `group_mode`,
`miniapp`, `photo_analysis`, `voice`, `admin`. Отсутствующая/false capability
скрывает соответствующую функцию; capability не заменяет resource-level
permission.

### Incident status

Допустимы только `detected`, `open`, `reported`, `overdue`, `escalated`,
`resolved`, `dismissed`. `reported` означает: пользователь сообщил ДомСигналу,
что сам отправил обращение. Это не подтверждение регистрации внешней системой.

### ActionDescriptor

```json
{
  "code": "prepare_appeal",
  "enabled": true,
  "reason": null
}
```

Target codes: `prepare_appeal`, `edit_draft`, `join`, `copy_draft`,
`open_official_channel`, `mark_filed`, `mark_resolved`, `mark_unresolved`,
`escalate`, `report_not_problem`, `retry`. `reason` обязателен и может быть
`null`; при `enabled=false` содержит безопасное пользовательское объяснение.

### Provenance

Общий value object: `origin` (nullable, если неизвестно), `source_title?`, `source_url?`, `verified_at?`,
`recorded_at?`, `note?`. Backend соблюдает ограничения и UI-семантику:

| `origin` | Обязательные данные | Смысл |
|---|---|---|
| `official` | `source_title`, `verified_at`; URL при наличии | «Официальный источник · проверено <date>». |
| `product_derived` | `note` и provenance использованных правил | «Рассчитано ДомСигналом на основе указанных правил». |
| `user_reported` | `recorded_at` | «Указано пользователем · внешней системой не подтверждено». |
| `demo` | явный `origin=demo` | «Демонстрационные данные»; не может сериализоваться как official. |

Источник, дата проверки и demo-state передаются вместе с данными, когда влияют
на решение. Неизвестный срок остаётся `null`, а не вычисляется UI.

## Минимальные DTO

Формальная required/nullable-схема должна быть зафиксирована DEV-B в Pydantic →
OpenAPI; ниже — обязательная семантика, а не параллельная JSON Schema.

| DTO | Минимальные поля v0.1 |
|---|---|
| `UserContext` | `id`, `display_name`, `capabilities` с пятью обязательными flags. |
| `HouseSummary` | `id`, `name`, `address`, `region_code`, `timezone`, server-provided `access_role`, `provenance`. |
| `IncidentSummary` | `id`, `house_id`, `title`, `category_code`, `status`, `report_count`, `participant_count`, `updated_at`, nullable `due_at`, `provenance`, `allowed_actions`. |
| `IncidentDetail` | Все поля summary; `problem: ProblemDetails`; backend-resolved `route` (`recipient`, `guidance`, `rationale`, official channel, nullable deadline, provenance); nullable `draft_id`; filing summary с user-reported provenance; `version`; `allowed_actions`. |
| `ProblemAnalysis` | `analysis_id`, normalized `problem: ProblemDetails`, nullable `confidence`, `requires_confirmation`, `analysis_mode` (`rules`, `model` или `manual`), server questions/options, duplicate candidates, nullable emergency instructions/contacts с provenance. |
| `AppealDraft` | `id`, `incident_id`, editable `text`, `version`, `created_at`, `updated_at`, official channel descriptor, `provenance`, `allowed_actions`. |
| `ActivityEvent` | `id`, `incident_id`, `kind`, `title`, `detail`, `occurred_at`, `provenance`, `allowed_actions`. |
| `ActionDescriptor` | `code`, `enabled`, nullable `reason`. |
| `ProblemDetails` | `description`, nullable `category_code`, structured nullable location (`entrance`, `floor`, `label`), nullable `observed_since`, server-defined answers needed for routing. |

`ProblemAnalysis` may degrade from model to rules/manual without changing the
submit contract. Emergency data overrides the ordinary route in presentation.
Matching and create-vs-existing decisions remain server-side. UI показывает
неопределённость по `requires_confirmation`, а не вычисляет свой confidence
threshold.

### AI ↔ product analysis handoff (target)

Это логическая граница внутри текущего backend package, а не требование нового
сервиса и не заявление о существующем endpoint сверх OpenAPI.

1. DEV-B аутентифицирует запрос, проверяет house/resource access и формирует
   допустимый текст и набор кандидатов.
2. DEV-A возвращает типизированный аналитический результат через согласованную
   семантику `ProblemAnalysis`: категория, извлечённые поля, candidates,
   uncertainty/`requires_confirmation`, вопросы и состояние выполнения
   (`rules`, `model`, `manual` или явная ошибка/fallback).
3. DEV-B валидирует результат, применяет safety и остальные бизнес-правила,
   принимает create/join/merge решение, выполняет транзакцию и формирует
   public response.

Semantic score является предложением, а не разрешением merge. Признак риска не
заменяет проверенный безопасный текст и не задерживает deterministic off-ramp.
Предложенная моделью формулировка сохраняется только после продуктовой
валидации, прав доступа и подтверждения пользователя. Модель не задаёт
юридическую ответственность, нормативный срок, факт внешней регистрации или
устранения. При недоступном AI продукт использует честный rules/manual путь, а
не выдуманный production-ответ.

## Target endpoints

Все пути ниже — **не реализованное обещание, а target v0.1**. Protected routes
проверяют authenticated user и resource scope на каждом запросе.

| Method/path | Request → response |
|---|---|
| `GET /api/v1/me` | → `UserContext`. |
| `GET /api/v1/houses` | → `HouseSummary[]` только доступных домов. |
| `GET /api/v1/houses/{house_id}/incidents` | Фильтры/пагинация → `IncidentSummary[]` + page metadata. |
| `POST /api/v1/houses/{house_id}/reports/analyze` | Начальное описание/ответы → `ProblemAnalysis`; не создаёт incident. |
| `POST /api/v1/houses/{house_id}/reports` | Подтверждённые `ProblemDetails` + nullable `analysis_id` → `IncidentDetail` нового или существующего incident. |
| `GET /api/v1/incidents/{incident_id}` | → `IncidentDetail`. |
| `POST /api/v1/incidents/{incident_id}/join` | → актуальный `IncidentDetail`; только при разрешённом `join`. |
| `POST /api/v1/incidents/{incident_id}/appeal-draft` | → новый или существующий `AppealDraft`. |
| `GET /api/v1/appeal-drafts/{draft_id}` | → последняя сохранённая `AppealDraft`. |
| `PATCH /api/v1/appeal-drafts/{draft_id}` | `text`, `version` → сохранённая `AppealDraft`; stale version → `409`. |
| `POST /api/v1/incidents/{incident_id}/appeals/mark-filed` | `draft_id` → актуальный `IncidentDetail`/event; сохраняется только user assertion и server timestamp. |
| `POST /api/v1/incidents/{incident_id}/feedback` | outcome `resolved`, `unresolved` или `not_problem` → актуальный `IncidentDetail`/event. |
| `GET /api/v1/me/activity` | Фильтры/пагинация → `ActivityEvent[]` + page metadata. |
| `GET /api/v1/admin/houses/{house_id}/summary` | Admin-scoped aggregate summary. |
| `GET /api/v1/admin/houses/{house_id}/settings` | Admin-scoped versioned settings. |
| `PATCH /api/v1/admin/houses/{house_id}/settings` | Versioned settings patch → saved settings; stale → `409`. |
| `POST /api/v1/admin/incidents/{incident_id}/dismiss` | Reason → incident `dismissed`; admin scope required. |

State-changing POST requests accept `Idempotency-Key`: same key+payload returns
the original effect, while the same key with another payload returns `409`.
Opening/copying a draft never calls `mark-filed` implicitly.

### `mark_filed`

The endpoint records only the authenticated user's assertion and emits
`user_reported` provenance. It may set incident status to `reported` under
backend transition rules, but must not set external confirmation, invent an
external ID, or claim acceptance by an official system. Retrying with the same
idempotency key has one domain effect.

## Error contract

Errors use `Content-Type: application/problem+json` and contain:

```json
{
  "type": "https://domsignal.example/problems/stale_version",
  "code": "stale_version",
  "title": "Данные изменились",
  "status": 409,
  "detail": "Обновите данные и повторите действие",
  "retryable": true,
  "trace_id": "opaque-id",
  "field_errors": null
}
```

`code`, `title`, `status`, `detail`, `retryable`, `trace_id` обязательны.
Validation errors дополнительно содержат `field_errors` как список
`{field, code, message}`. Минимальная семантика: `401` invalid/expired auth,
`403` authenticated but forbidden, `404` missing resource, `409` stale или
idempotency conflict, `422` validation. Sensitive auth details не попадают в
`detail`, URL или логи.

## A-01 / C0.1 — implemented producer contract

| DTO / field | Реальный результат |
|---|---|
| `ActionDescriptor` | `{code, enabled, reason}`; vocabulary выше, `reason` required nullable. Incident producer всегда возвращает `[]`: domain endpoints ещё нет. Read/navigation не action. Unknown codes consumer игнорирует. |
| `CapabilityFlags` | `group_mode=false`, `miniapp=true`, `photo_analysis=false`, `voice=false`, `admin=false`. C0 flags сохранены: report_create/incident_board/incident_detail true; max_live/routes/appeals/reminders/media false; test_auth только по settings local/test. |
| `MeResponse.capabilities` | Та же модель/значения, что `/capabilities.features`, версия `c0.1`. Role `admin` старого house membership не включает несуществующий admin product. Capabilities не предоставляют resource access. |
| `IncidentSummary` | Сохранены id/house_id/category/title/description/status/created_at; добавлены nullable `updated_at`, `due_at`, structured `location` (entrance/floor/label), `participant_count`, `is_demo`, `provenance`; исправлен фактический report_count. |
| `IncidentDetail` | Summary + реальные reports (id/description/created_at) + существующий DemoRule с отдельным origin/verified_at. Route/responsible/explanation/appeal/history не опубликованы: движок маршрута и lifecycle events отсутствуют. Reports — сообщения, не история смены статусов. |
| Missing data | location/updated_at/due_at = null: нет соответствующего persistence. Не извлекаем место из description и не выдаём created_at за updated_at. |
| Counts | Board: batched `COUNT(*)`, `COUNT(DISTINCT Report.author_id)` по incident; detail: длина reports и множество author_id. Report.author_id — non-null FK. Это уникальные авторы сообщений, не подтверждённые жители; несколько reports одного actor не увеличивают participant_count. Nullable participant_count сохранён для будущего источника без identity. |
| Provenance | `origin` отдельно от `verification_status` и `verified_at`. C0 создаёт incident только по manual report authenticated actor: user_reported; дом is_demo даёт demo. DemoRule всегда origin=demo независимо от verification_status. verified_at=null, проверка не выдумана. Unknown origin допускает null; official не выводится из verified. |
| Status | Только существующие open/resolved/dismissed. Будущий reported остаётся исключительно отметкой пользователя о самостоятельной отправке; filing endpoint не добавлен. |

`POST /api/v1/reports` с body.house_id сохранён; новый house-scoped alias и
analyze не нужны для convergence. Idempotency receipts старого C0 читаются по
сохранённым report/incident IDs, доступ проверяется снова, ответ сериализуется
текущим read model (с актуальными counts). Domain effect/IDs сохраняются;
legacy actions из сохранённого JSON не выходят наружу. Изменённый payload с
прежним ключом по-прежнему даёт 409 без повторного эффекта.

### A-15 — server-resolved OperationContext (IMPLEMENTED IN BRANCH)

18.09.2026, `dev/b-experience`, поверх A-01/C0.1. Не MERGED TO MAIN и не
LIVE VERIFIED. Формы report/incident/board сохранены. `/me.houses[].role`
совместимо расширен `operator`/`responsible`; `admin` остаётся public descriptor
для company_admin, `resident` — для resident access. Полная RBAC модель и
внутренние tenant/management IDs клиенту не требуются. OpenAPI/TS обновлены.

Единственный resolver — `MembershipService.require_house`:
authenticated actor → существующий House → текущая active HouseManagement
(`valid_from <= now < valid_to`, null upper bound) и active ManagementCompany →
active OrganizationMembership + HouseAssignment + неистёкшая active
ResidentMembership → `AccessPolicy` → immutable OperationContext.

- `actor_user_id`, `house_id` известны; `tenant_id` и `management_id` имеют
  `ScopeValue(KNOWN, UUID)`. При недоступном/отсутствующем текущем scope — 404,
  контекст с выдуманным или UNKNOWN tenant не создаётся.
- `organization_role`, `house_assignment_role`, `resident_membership_id` и
  `resident_access` выводятся из БД; `roles`/`permissions` и `source=api|max_replay`
  задаёт сервер. Source resident basis не означает право собственности.
- company_admin видит все текущие management своей УК; operator — только с
  активным assignment operator/responsible на **этот management**. Assignment
  без active organization membership не предоставляет сотруднику доступ.
- Resident basis относится к физическому дому. Active и expires_at проверяются
  на каждом запросе, независимо от login. Истечение и revoke не требуют
  перевыпуска bearer session. Независимое действующее resident basis сохраняет
  доступ при отзыве employee assignment.
- Platform `superadmin` хранится отдельно и не выдаёт read-all/impersonation.
- Текущие permissions: `incident.read`, `report.create`. Возможность действия
  требует и permission, и реализованный endpoint/business capability.
  `allowed_actions=[]`; будущие Ticket/admin/appeal actions не опубликованы.
- chat_binding_id/source_chat_id/binding_version остаются
  `ScopeValue(NOT_APPLICABLE, null)`. MAX ChatBinding — отдельная A-07.

Ни query/header tenant/management/chat/start_param/role/permissions, ни deep link
не authority. Неизвестные query metadata игнорируются, extra body fields
отклоняются (`extra=forbid`, 422). Optional detail.house_id — только selector,
он обязан совпасть с разрешённым объектом; multiple houses требуют явного выбора.

Чужой или отсутствующий house/incident → одинаковые 404 `resource_not_found`,
без раскрытия private content; известный scope без permission конкретного
действия → 403 `house_access_denied`. Отсутствующий обязательный house context
во внутреннем вызове — fail closed. `/max/replay` также проверяет совпадение
external_user_id с bearer actor (подмена actor → 403) и scope до inbox;
worker повторно разрешает scope перед созданием Report.

Incident queries требуют OperationContext и фильтруют **house + management**
до чтения content/построения DTO. При detail без selector допускается сначала
прочитать только incident.house_id как routing metadata, не ORM content.
Counts/reports читаются лишь для уже разрешённых incidents.

При смене УК старые Incident/Assignment сохраняют исходный management; ничего
не копируется. Board/detail этого среза показывают только **текущий management**
(в том числе жителям). Старая история остаётся в БД, отдельный архивный endpoint
и own-history-after-revoke ещё не реализованы. ResidentMembership сохраняется
на House; новые reports получают новый management. Повтор старого idempotency
receipt после switch снова проверяет scope и возвращает 404, не раскрывая старый
ответ и не создавая второй эффект. A-15 не реализует приватные Ticket/internal
employee данные; существующие C0.1 reports остаются частью разрешённой доски.

Migration `20260918_0002`: demo houses → явные demo company/management;
Incident.management_id backfill без смены ID/текстов. Resident basis = demo/manual,
verification_level=unverified, verified_at=null; legacy role/evidence сохранены
для lossless C0 rollback, но не участвуют в policy. Non-demo legacy management
изолирован и suspended/legacy_unverified до проверки; фиктивных активных УК нет.

### Ошибки C0.1 и migration

Единый `application/problem+json`: type/title/status/code/detail/retryable/
trace_id, nullable field_errors; для 422 список `{field, code, message}`.
Сохраняются lower_snake_case codes: authentication_required,
house_access_denied, resource_not_found, idempotency_conflict,
validation_error, feature_unavailable, invalid_init_data, internal_error.
Framework 404/405 нормализуются в http_404/http_405; 500 — безопасный generic.
Все реально выдаваемые error responses описаны problem+json в OpenAPI.

Миграция producer+consumer атомарная: request_id/errors удалены из body;
X-Request-ID header сохранён и равен trace_id, генерируется сервером. Клиентский
X-Request-ID не отражается. Validation не отдаёт input/body/ctx/stack/SQL,
не отражает даже имя неизвестного extra field. C0 service errors retryable=false
(включая не реализованную функцию и конфликт idempotency); internal_error=true.
Consumer читает retryable/trace_id и сохраняет ввод. Только неполный proxy/non-JSON
ответ получает локальный transport fallback; это не business permission.

Producer и miniapp выпускаются вместе; поддержка старого JS bundle не обещается.
Generated source: `docs/openapi.json` и `miniapp/src/shared/api/schema.ts`,
только штатными export/api:generate + `scripts/check.py --scope contracts`.

## ARCH-PLATFORM-v1 — компактный target delta

Основание: [продуктовая архитектура](PRODUCT_ARCHITECTURE.md), §§ 4–12.
Connection/Ticket/onboarding ниже — TARGET. Tenant/access foundation уже
реализован в A-15 выше; остальные возможности не опубликованы.
Существующие C0 и C1/B-00 сохраняются; точная форма, nullable-поля, версии и
совместимость принимаются в A-01, затем соответствующем предметном срезе.

| Область | Требуемая семантика / граница |
|---|---|
| Tenant/house context | Tenant определяется сервером через действующую HouseManagement с периодом; house ID не даёт доступ. Старые объекты сохраняют исходную организацию при смене УК. A-15 реализует этот foundation; lifecycle подключений остаётся TARGET. |
| Assignments / access basis | Несколько назначений пользователя; отдельные organization role, house assignment и resident basis с источником, актуальностью и отзывом. Админ чата не становится админом УК; указанный адрес не открывает чужую доску. |
| Connection lifecycle | Разрешение УК → действие администратора чата → проверка MAX → подтверждение дома → атомарная активация. Состояние, причина, время проверки, лимит/резерв и допустимое следующее действие; сбой проверки оставляет pending. Строковые коды и TTL ещё не приняты. |
| Report / Incident / Ticket / ExternalAppeal | Сообщение, общая проблема, рабочая заявка и внешнее обращение — разные объекты и scope. Ticket несёт очередь/владельца/рабочие переходы; отчёт о выполнении связан с попыткой, наблюдения жителя отдельны. Нельзя заменить Incident.status lifecycle заявки. |
| Provenance | Происхождение отдельно от актуальности/проверки и demo-маркера. Ручной номер/filing не становится external verified registration; WorkReport не становится resident confirmation. |
| allowed_actions / capabilities | Backend вычисляет действия по актуальному scope; endpoint проверяет права повторно. Backend capability означает реализованную функцию, Bridge capability — клиентский метод. Ни одна не заменяет object permission; неподдержанные действия не публикуются активными. |
| Ошибки | Различать отказ доступа, истёкшее/отозванное назначение, конфликт привязки/лимита/версии, истёкший/replayed контекст и временную недоступность проверки MAX. Не раскрывать чужой tenant/объект; коды и HTTP mapping принимаются с negative tests, не объявляются поддержанными здесь. |

A-01 фиксирует минимальный совместимый контекст read-model и стратегию old/new
producer: какие данные уже подтверждены C0, какие отсутствуют и не выдают доступ.
Он не создаёт tenant из query, не заполняет фиктивные tenant ID и не выдаёт
непроверенную роль как действующую. Persistence/authorization двух УК — A-15;
подключения — A-07, кабинет — A-10/B-09, Ticket — A-16/B-14. Новые переходы
публикуются только вместе с реализацией и generated contract tests.

## Foundation C0 — implemented reference, merged to main at 3d4a095

The following section is a HISTORICAL C0 reference at main `3d4a095`, not the current branch contract. A-01/C0.1 above supersedes its actions, counts, capabilities and error format. Other target workflows remain unimplemented; LIVE MAX remains NOT VERIFIED.

# ДомСигнал — контракты C0

## Источник и генерация

Pydantic/FastAPI — источник формата. Зафиксированный OpenAPI 3.1 находится в
`docs/openapi.json`, generated TypeScript — в
`miniapp/src/shared/api/schema.ts`. Проверка воспроизводимости:

```bash
uv run python scripts/check.py --scope contracts
```

Файлы обновляются только вместе: `uv run python scripts/export_openapi.py`,
затем `npm --prefix miniapp run api:generate`.

## Аутентификация и доступ

- `POST /api/v1/auth/test-session` — только local/test и только seeded actor
  `demo` или `outsider`; production configuration не может разрешить endpoint.
- `POST /api/v1/auth/max` — проверяет raw initData один раз и выдаёт короткую
  bearer session. Без bot token возвращает `503`, а не фиктивный успех.
- `GET /api/v1/me` — пользователь и закрытый список memberships.
- Любой house/incident read и report create повторно проверяет membership.
  Deep link, path/query `house_id` и скрытая UI-кнопка права не выдают.

Bearer token хранится mini app только в памяти. Внешние MAX IDs на JSON-границе
считаются строками.

## Реализованные endpoints

| Method/path | Семантика |
|---|---|
| `GET /api/v1/capabilities` | C0 version, environment и только реально доступные flags |
| `POST /api/v1/auth/test-session` | Явная local/test session |
| `POST /api/v1/auth/max` | MAX initData → session после server validation |
| `GET /api/v1/me` | Профиль и доступные дома |
| `POST /api/v1/reports` | Manual category + description → Report и новый Incident |
| `GET /api/v1/houses/{id}/incidents` | House-scoped board, `limit/offset/total` |
| `GET /api/v1/incidents/{id}` | Карточка, reports и demo rule provenance |
| `POST /max/replay` | Local/test normalized diagnostic event → durable inbox/job |
| `POST /max/webhook` | A-07 branch: secret-validated Update → committed receipt/state/job; off = 503; live NOT VERIFIED |

Routes, appeals, participants, feedback, admin, reminders и media отсутствуют в
OpenAPI. Capability flags для них `false`; успешных placeholder responses нет.

## Создание report

`POST /api/v1/reports` требует `Idempotency-Key` длиной 8–200 символов.
Область ключа: authenticated actor + action `report.create`. Одинаковое тело и
ключ возвращают исходный `201`-результат без второго Report; тот же ключ с
другим телом возвращает `409 idempotency_conflict`.

`classification_mode` сейчас принимает только `manual`. Ответ содержит
`report_id` и `IncidentDetail`. Встроенный rule имеет status `demo`,
`due_at=null` и явное примечание, что ответственный/срок не проверены.

## Ошибки

Ошибки API имеют content type `application/problem+json`:

```json
{
  "type": "https://domsignal.local/problems/house_access_denied",
  "title": "Access denied",
  "status": 403,
  "detail": "The authenticated user is not a member of this house",
  "code": "house_access_denied",
  "request_id": "uuid"
}
```

Политика C0: `401` — отсутствующая/истёкшая session, `403` — известный ресурс
чужого дома, `404` — ресурс не существует, `409` — конфликт idempotency key,
`422` — форма запроса не прошла Pydantic validation. `X-Request-ID` возвращается
в response header и body ошибки.

Клиент обязан безопасно показывать неизвестный enum/ошибку как недоступное
состояние; release bundle не включает автоматическую подмену backend.

## MAX и worker boundary

`NormalizedInboundEvent` — наш тестовый контракт, а не утверждение о live MAX
payload: `event_id`, единственный `event_type=diagnostic.report`, string
`external_user_id`, UUID дома, manual category, description, timezone-aware
`occurred_at`. Replay требует bearer session и запрещён в production.

`MaxTransport.send(OutboundNotification)` имеет реализации `off` и
`recording`. `off` не выполняет сеть и не меняет subscriptions; `recording`
разрешён только вне production. Реальный HTTP transport и webhook adapter —
контрактная задача DEV-B после credentials/fixtures.
