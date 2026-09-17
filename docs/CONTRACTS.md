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
| `POST /max/webhook` | Честный `503`: live payload adapter пока не реализован |

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
