# ДомСигнал — UX/API contract v0.1

## Статус

Это **target contract**, подготовленный DEV-B для реализации DEV-A. Он не
объявляет перечисленные endpoints доступными. На текущей базе ветки
`dev/b-experience` опубликованного API нет; фактическая доступность после merge
определяется OpenAPI и contract tests, а не этим документом.

Read-only наблюдение параллельного FND-01 на локальном `dev/a-core@c939ccf`:
C0 реализует auth/test boundaries, `GET /api/v1/capabilities`, `GET /api/v1/me`,
`POST /api/v1/reports`, house incidents list, incident detail и test MAX replay;
live webhook честно отвечает `503`. Appeals, drafts, analyze, activity, join и
admin API там отсутствуют. Этот commit не замёржен в текущую ветку или `main`.

Backend является source of truth для incident status, matching, route,
provenance, capabilities и `allowed_actions`. Frontend не вычисляет права и не
hardcode региональные правила. Deep link передаёт navigation context, но не
access grant.

Согласованная foundation boundary сохраняется: Pydantic/FastAPI → OpenAPI →
generated TypeScript types; внешние MAX identifiers на JSON-границе — строки,
время — timezone-aware UTC; API и bot вызывают общие services и не отдают ORM;
контракт меняется совместимо либо одним набором producer + consumer + tests.

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

Общий value object: `type`, `source_title?`, `source_url?`, `verified_at?`,
`recorded_at?`, `note?`. Backend соблюдает ограничения и UI-семантику:

| `type` | Обязательные данные | Смысл |
|---|---|---|
| `official` | `source_title`, `verified_at`; URL при наличии | «Официальный источник · проверено <date>». |
| `product_derived` | `note` и provenance использованных правил | «Рассчитано ДомСигналом на основе указанных правил». |
| `user_reported` | `recorded_at` | «Указано пользователем · внешней системой не подтверждено». |
| `demo` | явный `type=demo` | «Демонстрационные данные»; не может сериализоваться как official. |

Источник, дата проверки и demo-state передаются вместе с данными, когда влияют
на решение. Неизвестный срок остаётся `null`, а не вычисляется UI.

## Минимальные DTO

Формальная required/nullable-схема должна быть зафиксирована DEV-A в Pydantic →
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

## Contract conflicts / decisions required

Read-only сверка локальной параллельной ветки `dev/a-core` на commit `c939ccf`
показывает незамёрженный C0, а не состояние `main`:

- C0 создаёт report через `POST /api/v1/reports` с `house_id` в body; target
  использует house-scoped analyze + create. DEV-A должен выбрать совместимую
  миграцию/alias и отразить её в OpenAPI.
- C0 возвращает capabilities отдельным endpoint и с другим набором flags;
  target требует пять UX capabilities в `UserContext`.
- C0 поддерживает только `open/resolved/dismissed`; target lifecycle требует
  ещё `detected/reported/overdue/escalated` с указанной семантикой `reported`.
- C0 `allowed_actions` — строки (`view`); target — объекты
  `{code, enabled, reason}` и перечисленные action codes.
- C0 `RuleProvenance.verification_status` использует
  `verified/needs_verification/demo`; target требует отдельный origin type
  `official/product_derived/user_reported/demo`. Нужно сохранить понятие
  verification freshness, не смешивая его с происхождением.
- C0 problem body использует `request_id` и `errors`; target требует
  `retryable`, `trace_id` и validation `field_errors`. Нужен согласованный
  backward-compatible переход или единое обновление producer/consumer/tests.
- Appeals, activity, analyze, join, houses list и admin target routes в C0
  отсутствуют. Это ожидаемые будущие endpoints; B-00 не добавляет заглушки.

## DEV-B → DEV-A requirements

- DTO: `UserContext`, `HouseSummary`, `IncidentSummary`, `IncidentDetail`, `ProblemAnalysis`, `AppealDraft`, `ActivityEvent`, `ActionDescriptor`, `ProblemDetails` с указанными минимальными полями и Pydantic → OpenAPI source of truth.
- Statuses: `detected`, `open`, `reported`, `overdue`, `escalated`, `resolved`, `dismissed`; `reported` — только self-report пользователя.
- `allowed_actions`: объекты `{code, enabled, reason}`; codes `prepare_appeal`, `edit_draft`, `join`, `copy_draft`, `open_official_channel`, `mark_filed`, `mark_resolved`, `mark_unresolved`, `escalate`, `report_not_problem`, `retry`.
- Capabilities в `UserContext`: `group_mode`, `miniapp`, `photo_analysis`, `voice`, `admin`.
- Target endpoints: `GET /api/v1/me`; `GET /api/v1/houses`; `GET /api/v1/houses/{house_id}/incidents`; `POST /api/v1/houses/{house_id}/reports/analyze`; `POST /api/v1/houses/{house_id}/reports`; `GET /api/v1/incidents/{incident_id}`; `POST /api/v1/incidents/{incident_id}/join`; `POST /api/v1/incidents/{incident_id}/appeal-draft`; `GET /api/v1/appeal-drafts/{draft_id}`; `PATCH /api/v1/appeal-drafts/{draft_id}`; `POST /api/v1/incidents/{incident_id}/appeals/mark-filed`; `POST /api/v1/incidents/{incident_id}/feedback`; `GET /api/v1/me/activity`; `GET /api/v1/admin/houses/{house_id}/summary`; `GET /api/v1/admin/houses/{house_id}/settings`; `PATCH /api/v1/admin/houses/{house_id}/settings`; `POST /api/v1/admin/incidents/{incident_id}/dismiss`.
- `mark_filed`: idempotent user assertion only; no external confirmation, invented registration or implicit call from copy/open.
- Provenance: `official`, `product_derived`, `user_reported`, `demo` with required source/date/demo semantics.
- Errors: `application/problem+json` with `code`, `title`, `status`, `detail`, `retryable`, `trace_id`; validation adds `field_errors`.
