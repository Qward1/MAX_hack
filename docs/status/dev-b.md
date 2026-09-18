# DEV-B — current handoff
Updated: 2026-09-18 (Q&A documentation alignment)
Branch: dev/b-experience
Current task: QA-ALIGNMENT-2026-09-18 — документы и план
State: DOCS UPDATED; runtime readiness unchanged; A-16 TARGET / TODO / NOT STARTED

## Результат документационной правки

[Источник](../decisions.md#qa-alignment-2026-09-18) — заметки владельца после
Q&A организаторов, не самостоятельно просмотренная запись. Снят только блокер
общей допустимости LLM; provider/data/license gate сохранён. Собственный API
готовим для проверок в A-13: HTTPS, OpenAPI, роли/данные, обязательные проверки,
DATA-API по ещё не полученному официальному шаблону. Веса ТЗ не менялись.

A-16 уточнена: стабильный внутренний номер, исходные Report/заявители/история,
ответственный/резерв и следующий шаг, WorkAttempt/ResultObservation, позднее
возражение, четыре смысла срока и атомарные typed events/outbox intents.
Правило закрытия/reopening ждёт следующего согласования. Delivery остаётся
A-05/B-03/B-06/B-07/A-09/B-08, UI — B-14, live — B-01/B-11. Все эти Owners —
DEV-B; AI остаётся DEV-A. QA-01…QA-13 добавлены как PLANNED / NOT RUN.

№416: [таблица пунктов/применимости](../PRODUCT_ARCHITECTURE.md#пп-рф-416--документальная-сверка-18092026)
по тексту редакции 20.06.2026 из LegalActs/СудАкт; официальная публикация найдена,
но текст первоисточника получить не удалось. Ограниченная документальная сверка,
не полный compliance. Нужны официальная повторная сверка/порядок Минстроя,
роль продукта у партнёра, основания/anchors и раздельная retention policy.
Контроль жителем не акт приёмки; фото остаётся A-14/Product/B-13.

## Проверки и refs этой правки

- Стартовый HEAD и origin/dev/b-experience: `4628d11` (A-07);
  origin/main: `3d4a095`; origin/dev/a-core: `a70df01`, handoff прочитан из ref.
  Fetch успешен; синхронизация собственной ветки/main — already up to date.
- Repository-sanity по действующему CI: обязательные файлы, agent discovery,
  отсутствие conflict markers — PASS. Локальные Markdown пути/anchors — PASS.
  Прежние 100 строк C/MT/CB/A-15 acceptance и веса критериев сохранены.
- `git diff --check` — PASS; docs-only scope проверен. Архив плана, DEV-A status,
  runtime OpenAPI/generated TS, код/миграции/dependencies не изменены.
- Официальные страницы MAX send/edit/subscriptions/Mini App/Bridge и callback
  прочитаны, это DOC CHECK. Heavy product tests/Docker/live не запускались.

A-07 остаётся IMPLEMENTED IN BRANCH, не MERGED; текущий групповой путь только
явная `/report`. Live MAX **NOT VERIFIED / PENDING TOKEN**. Нужны разрешённый
токен, изолированные чаты, HTTPS-стенд и реальные клиенты. Новые evidence A/B
не подменяют C. Webhook/данные/боевой MAX не тронуты; Git cleanup не выполнялся.
Финальный SHA и результат push собственной ветки — в итоговом сообщении;
review/актуальный CI до main остаются обязательными. Остановиться после этой
правки: реализацию Ticket/UI/уведомлений/LLM и A-16 не начинать.

## Предыдущий handoff A-07 — сохранённое evidence

Updated: 2026-09-18 (A-07)
Branch: dev/b-experience
Current task: A-07 — existing MAX chat connection and safe ChatBinding
State: PASS / IMPLEMENTED IN BRANCH; MAX NOT LIVE VERIFIED / PENDING TOKEN

## Delivery boundary

| Slice | State | Evidence |
|---|---|---|
| A-01 / C0.1 | PASS / IMPLEMENTED IN BRANCH | Parent e66c351; producer/consumer regressions and OpenAPI/TS drift rerun |
| A-15 | PASS / IMPLEMENTED IN BRANCH | Parent ffd9b84; all 16 existing isolation/access tests rerun |
| A-07 | PASS / IMPLEMENTED IN BRANCH | Migration 0003, provider/state/approval/context/worker; CB-01…CB-22 PASS, 38 PG cases |
| B-02 | PASS / IMPLEMENTED IN BRANCH | 8 browser tests, real API/PG create/board/detail/reload plus existing 73 frontend tests |
| Real MAX | IMPLEMENTED / NOT LIVE VERIFIED | Read-only production provider + webhook; no real token/chat calls; PENDING TOKEN |
| Ticket / full admin UI / AI | NOT STARTED | Explicitly excluded from this task |

Start and END refs after fetch: own branch/remote ffd9b84, origin/main 3d4a095.
Own fast-forward/main synchronization was already up to date. Colleague handoff
read from origin/dev/a-core; no writes/push to that branch. Main is unchanged:
second-developer review/current CI/merge remain pending. IMPLEMENTATION_CONTEXT
retains the verified main table and a separate branch pointer. Final commit SHA
is provided in the final response, not a follow-up hash-only commit.

## Implemented flow and invariants

MAXChat is a technical snapshot of an already existing chat: UUID, unique string
max_chat_id, type/title/channel/owner, bot_present, last_seen/lifecycle timestamps
and a monotonic binding counter. Title/text/LLM/client parameters never select a
house or tenant. No API creates groups or imports participant lists.

ConnectionRequest stores management+house, initiator, connector MAX identity,
SHA-256 digest of a random 256-bit opaque token, expiry, scope, candidate chat,
verification/completion/cancellation/rejection times and sanitized error code.
TTL defaults to 900 seconds. The raw token is returned once; it is absent from
DB receipts/jobs/outbox. Repeated open initiation returns the same request with
null token; cancel/recreate recovers a lost first response.

State transitions are centralized in core/chat_connections.py and applied by the
application service: created → connector_claimed → chat_detected → max_verified
→ awaiting_approval → completed; expired/cancelled/rejected terminal. Same-company
connector with the same persisted MAX identity and current chat.connect permission
can confirm from max_verified. External connector waits for target-company approval.
Neither path needs mandatory Superadmin approval, and both require explicit confirm.

ChatBinding pins management+house and house/entrance scope; states pending → active
→ suspended/revoked, suspended → revoked. Reactivation/reassignment always uses a
new request/binding. The chat counter increments across bindings (1 → 2), old
binding scope/version is immutable, and histories are retained. Revoke is an
internal authorized service; no full administration endpoints/UI were introduced.

DB constraints: unique MAXChat external ID/token digest/request binding; composite
FK (management_id,house_id) for request and binding using the A-15 pattern; typed
scope/status/version CHECKs; unique (chat,version) and partial unique active chat;
immutable binding scope/version trigger. No house uniqueness prevents multiple
chats per house. An A-15 management status/end trigger suspends old active bindings
with MANAGEMENT_ENDED; natural period expiry is checked by health/access resolution.
No binding or old Incident history transfers automatically to a successor company.

`chat.connect` extends existing AccessPolicy: active company_admin, or active
organization operator with responsible assignment. Resident/operator alone cannot
connect. Backend derives current management/tenant. Existing OperationContext and
MembershipService remain the only access/context mechanism.

bot_started claims a valid unexpired token to the webhook's sender MAX identity;
same actor replay is idempotent, another actor cannot steal the request. A connector
may have only one open request; ambiguous bot_added is not guessed. bot_added
matches that connector's prior claim and records candidate chat, then enqueues
verification. Unrelated/duplicate add never activates a binding. Lifecycle event
timestamps stop an older add/remove from reversing newer installation state.

Verification reads current ChatInfo, bot membership/admin+mandatory permissions
(default read_all_messages), and current connector admin/owner from the provider.
No bot_added.user or token is permanent authority. Timeout/429/5xx keeps a new
connection chat_detected with verified_at null and uses durable job retry. Approval
rechecks MAX even after earlier success. Invalid/missing/unsupported responses fail
closed. Approval confirms current employee/management/company again after network
calls, rejects foreign active-chat conflict generically, creates binding/outbox and
completes request atomically. Lock order: house shared → chat advisory → request row;
DB uniqueness independently rejects concurrent activation. Request detection racing
its routing read fails closed for retry instead of reversing lock order.

Webhook authenticates configured secret before payload parsing (bounded 64 KiB).
Only explicit webhook mode accepts live payloads. Mapping lives in bot/max_updates;
application receives typed events. Concurrent duplicate delivery serializes on a
stable inbox identity. Receipt/state/jobs commit before HTTP 200. Inbox holds no
raw token or ordinary/unbound message text. Unknown events are acknowledged without
product effects; malformed identity gets sanitized Problem Details.

Group product intake is deliberately explicit `/report <category> <description>`
through existing manual ReportService core; no AI/NLP or B-06 auto-group introduced.
The author must already have authorized resident/employee access. Unbound chats,
ordinary conversation, channels and unauthorized actors create no Report/Incident
and invoke no NLP. There is no fallback demo/first house or membership grant.

For eligible messages, receipt captures chat_binding_id, binding_version and event
time. Worker checks binding health, then resolves chat → ACTIVE binding → pinned
current management → tenant/house → existing AccessPolicy → OperationContext in the
write transaction. Wrong/old ID/version, pre-activation events, management changes
and revoked access are ignored as terminal stale context. Outbox carries binding
ID/version and verified entrance hint; text cannot reassign it. No outbound group
sender/broadcast is added. Future senders must use the same guard before effects.

bot_removed sets bot_present false and suspends once with BOT_REMOVED. Health service
is worker-callable as max.binding.health and runs before each group report; missing
admin/permissions, inaccessible chat or unknown MAX state suspend. No periodic cron
was added. Recovery requires new confirmation/version, not automatic resumption.
Signed Mini App chat/start_param remain selectors only in the target architecture;
this version ignores them as access authority and keeps the existing explicit
house flow. No automatic ResidentMembership or live Mini App claim.

## API, provider and migration

Added API (existing session/Problem Details style):
- POST /api/v1/houses/{house_id}/chat-connections
- GET /api/v1/chat-connections/{request_id}
- POST /api/v1/chat-connections/{request_id}/approve with confirm:true
- POST /api/v1/chat-connections/{request_id}/reject
- POST /api/v1/chat-connections/{request_id}/cancel
- POST /max/webhook now implements authenticated mapping when explicitly enabled;
  off still gives 503. Existing test replay/manual endpoints remain independent.

OpenAPI and generated TS updated together. Foreign scopes are masked 404; visible
scope without permission 403; conflicts 409; provider failure 503/retryable.
Error codes include connection_expired, connector_not_chat_admin,
bot_permission_missing, chat_already_bound, management_not_active, tenant_suspended,
binding_not_active, stale_binding_version and sanitized max_* errors. No foreign
owner/title, raw upstream JSON or secrets appear in responses.

Production HttpMaxChatProvider is the sole read HTTP boundary, using configured
HTTPS origin (current official default platform-api2.max.ru), token from Settings
in Authorization, timeout, no redirects and strict response mapping. 401/403/404/
429/5xx/network/malformed responses have safe typed errors. It uses only documented
GET chat, members/me and members/admins. Unexpected admin pagination is explicitly
unsupported, not guessed. TLS is not disabled. HTTPX moved from dev to runtime.
Off/recording composition withholds token from the provider, preventing live calls.
The deterministic adapter exists only in tests/fakes and must be explicitly injected.
It covers metadata/admin/non-admin/permissions/timeout/429/5xx/missing chat.
Production selection and response mapping are independently tested.

Migration 20260918_0003 is additive, produces no active/demo bindings and preserves
existing A-15 grants/history. Clean upgrade and upgrade from populated C0.1/A-15
are tested. Empty A-07 downgrade works through base and back to head. Nonempty
chat/request/job history blocks destructive downgrade and requires a pre-A07 backup.
Alembic check reports no drift. Existing private PostgreSQL + worker/outbox are reused.

## Actual commands and evidence

Dedicated local PostgreSQL container domsignal-a07-db, loopback 55475; existing
shared DBs untouched. Python 3.12.14; Node 24.21.0 in child process PATH, existing
npm launcher; browser Chrome against own API 8020 with MAX_TRANSPORT=off. Docker
smoke uses its own project/volume/API 18086 and removes that smoke volume afterward.
No real MAX token, shared webhook mutation, polling or VPS deployment was performed.

| Command actually executed | Result |
|---|---|
| uv run ruff check src tests scripts migrations --fix; final without --fix | PASS; initial import/line-length issues fixed |
| uv run ruff format <explicit changed Python paths> | Formatting confined to this task |
| uv run mypy src/domsignal | PASS, 62 files; initial redundant cast corrected |
| uv run pytest tests/unit tests/contract -q / same via check.py backend | Final PASS, 51; initial tests package import collection issue fixed |
| uv run alembic upgrade head | PASS, clean 0001 → 0002 → 0003; initial multi-statement asyncpg DDL corrected before success |
| uv run alembic revision --autogenerate -m 'verified MAX chat connections' --rev-id 20260918_0003 | Generated additive draft, then reviewed and hardened |
| uv run pytest tests/integration/test_chat_bindings.py -x -q | PASS first 28 cases; final expanded suite 38 |
| uv run python scripts/check.py --scope backend | Final PASS: ruff, mypy, 51 unit/contract |
| uv run python scripts/check.py --scope integration | PASS: upgrade head + 65 integration tests (A-07 38, A-15 16, other regressions/migrations 11) |
| Migration harness subprocesses: python -m alembic upgrade 20260917_0001 / 20260918_0002; upgrade head; check; downgrade 20260917_0001/base; upgrade head | PASS in two uniquely named temporary PostgreSQL DBs; grants/data preserved; history-bearing A-07 downgrade correctly refused |
| uv run pytest tests/integration/test_chat_bindings.py::test_cb18_max_temporary_failure_is_pending_with_durable_retry tests/integration/test_jobs.py -q | PASS, 6 after final provider/terminal-job hardening |
| uv run python scripts/export_openapi.py | PASS, regenerated |
| npm --prefix miniapp run api:generate | PASS, regenerated |
| uv run python scripts/check.py --scope frontend | PASS: npm run typecheck; npm run test -- --run (73); npm run build |
| uv run python scripts/check.py --scope contracts | PASS: export_openapi --check; validate_region_pack.py; npm exec openapi-typescript to temporary file; TS comparison |
| uv run uvicorn domsignal.main:create_app --factory --host 127.0.0.1 --port 8020 | Own API for B-02 browser checks, test/off mode |
| npm --prefix miniapp run test:browser (explicit Node 24 npm CLI, PLAYWRIGHT_BASE_URL=8020, PLAYWRIGHT_CHANNEL=chrome) | PASS, 8; real-detail screenshot inspected |
| uv run python scripts/docker_smoke.py --project domsignal-smoke-a07 --api-port 18086 | PASS, clean image/PG/migration/seed/API+worker/restart persistence |
| docker compose -f compose.yaml -f compose.prod.yaml config --format json (synthetic config-only env) | PASS; PostgreSQL no published ports; required services share network |
| git diff --check | PASS |

Existing Starlette/httpx/anyio deprecation and browser color notices remain; no
checks were suppressed. B-02 board/detail/manual/reload and /me/houses/capabilities
regressions pass with group transport off. CB-01…CB-22 outcomes and test names:
[acceptance matrix](../../scenarios/acceptance.md). Source/doc mapping and 18 pending
live smoke steps: [MAX_LIVE_SMOKE](../MAX_LIVE_SMOKE.md).

## Remaining boundary / next

A-07 PASS refers to this authorized backend/connection slice and deterministic
regressions. IMPLEMENTED IN BRANCH is not MERGED TO MAIN. MAX integration code is
IMPLEMENTED / NOT LIVE VERIFIED; live verification is PENDING TOKEN and two real
existing test chats, HTTPS webhook, genuine permissions/identities and clients.
No real token was requested from secret stores or invented as production credentials.
Test adapters/synthetic events are explicitly not live integration evidence.

One recommended next DEV-B task: B-01 — live MAX feasibility using the checklist
once an approved token and isolated bot/chats are available. Do not start Ticket,
full admin UI or AI from this handoff. Review/CI of this branch precedes main merge.
