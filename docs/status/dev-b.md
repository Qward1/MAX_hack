# DEV-B — current handoff

Updated: 2026-09-19 (live Mini App identity continuation)
Branch: dev/b-experience
Current task: B-01 live Mini App authentication/context, then A-07 house/group smoke
State: MINI APP AUTHENTICATION/CONTEXT LIVE VERIFIED (MAX WEB) / NOT MERGED TO MAIN
Real MAX: binding + validated initData + canonical User + test house board/reload VERIFIED

## Current Mini App checkpoint

START/own origin `53ee8b5`; fetched main is already an ancestor. DEV-A remote
handoff read without writes. MAX Web operator launch produced auth/max 200 and
me 200 at 17:28:29 UTC, with canonical user and verified timestamp committed.
The real MAX identity matches the previously accepted bot_started destination.
Production contained zero houses/memberships: empty board was correct access.
Full sanitized evidence and exact IDs: [MAX live smoke](../MAX_LIVE_SMOKE.md).

Existing HMAC/age validation matches current official MAX documentation and needs
no bypass. Added `tools.live_fixture` singleton CLI with validated identity
precondition, ManagementService, explicit ResidentMembership, no employee/platform
role, operator audit and safe revoke/delete-empty. Deterministic PG tests exercise
scope isolation, idempotency, invalid identity/other owner rejection, revocation
and refusal to delete dependent rows. Added wrong-token/future-date/signed selector
auth tests. OpenAPI/TS unchanged. This is not a main merge.

Deployed code `d4b6776` via verified Git bundle (VPS has no GitHub credential),
production Docker rebuild and healthy API/DB. The CLI created exactly one test
scope at 17:43:43 UTC; operator audit retains IDs/reason. Production service reads
return only that house with resident permissions, empty board succeeds, unknown
house is masked 404. No organization membership, Report, Ticket or ChatBinding.
Public ready 200, anonymous me 401 and disabled test-session 503; no new session
issued by operator checks. Original real MAX session expired before provisioning.

Checks PASS: 68 targeted PG/auth/production tests; backend 100 unit/contract,
ruff/mypy 78 files, OpenAPI/TS drift, region validation, frontend production build,
local + production Docker builds, Gitleaks staged scan and diff check. Existing
Starlette/httpx/anyio deprecation notices only; no checks suppressed.

Operator completed reopening at 17:44:49 UTC and separate MAX-menu reload at
17:47:34 UTC. Each produced real auth/max, me and exact test-house board GET 200;
same canonical User and resident scope. Operator confirmed the board remained
visible. Mini App authentication/context is now LIVE VERIFIED for MAX Web.
Tool browser inventory did not expose the user's MAX tab; visual confirmation
is human evidence, not an automated browser fixture. Native mobile is untested.

Provider me exposes no group-add switch. Current official docs deprecate GET/chats
since June 2026, so its empty response proves neither absence of groups nor group
disablement. Setting is organizer-owned and currently UNKNOWN. Requested actual
addition/admin assignment in an existing test group. All later group/product loop
steps remain pending; no synthetic production webhook/identity or binding used.

## Current production checkpoint

Resumed START ref and own origin ref:
`b986aeda249316d75ad2a2c9620a803033e96a69`; origin/main already an ancestor.
No main merge and no writes to DEV-A. Existing project SSH key passes BatchMode
and strict host verification; the previous SSH access blocker is resolved.

VPS `domsignal-prod`, Ubuntu 24.04.4, 4 vCPU/7.8 GiB RAM/55 GiB disk, now runs
Docker 29.8.1 + Compose 5.5.1 at `/opt/domsignal`. Missing host DNS resolvers and
broken Ubuntu mirror fixed; NTP synchronized. UFW allows TCP 22/80/443;
PostgreSQL has no published port and API is loopback-only. Fresh secrets stay in
mode-600 `deploy/.env.production`; `.dockerignore` now excludes nested env files.

**DEPLOYED:** Caddy/API/worker/PostgreSQL; migrations completed, demo seed disabled,
API and DB healthy; worker process and DB reachable, no restart loops.
Application source remains the previously deployed code; this checkpoint adds a
Caddy Docker network alias and docs. Exact deployed checkpoint SHA is stored as
BUILD_COMMIT in the VPS environment file. No test data copied or generated.

**DETERMINISTIC VERIFIED:** Compose quiet validation/fail-closed assertions;
17 targeted production/subscription/MAX provider tests pass. Public `/ready` and
resident `/` return 200; external webhook without secret 401 and with production
secret plus `{}` 422. Test auth and demo seed remain disabled.
Controlled replay of the exact real event identity returns duplicate=true,
job_id=null; inbox count stays one and no jobs are added. This is operator replay,
not a second MAX-originated delivery.

**LIVE VERIFIED:** trusted public TLS (Let's Encrypt YE1, matching SAN and verified
chain); real production MAX GET `/me` identity
402577719 / t480_hakaton_max_bot / is_bot=true. Safe utility inspected empty
subscriptions, registered the expected `/max/webhook` URL, and confirmed exactly
one subscription with all six documented event types.

The operator's real Start produced authenticated, typed, persisted bot_started at
2026-09-18 21:39:42.616290 UTC. MAX's active dialog data identified the actual
recipient and reconstructed the exact event hash for duplicate verification.
Production HttpMaxMessagingProvider sent the requested plain-text confirmation;
MAX accepted `mid.00000000066d71cf01a0b678f3ea6fad`, and GET read-back verified
ID/text/recipient. No reading/push-display claim.

Acceptance is persisted in the real inbox receipt's `payload.bootstrap_smoke`;
a pre-send claim prevents accidental resend. This operational record does not
create or verify a Ticket NotificationDelivery or app User. Users, tickets, work
attempts, deliveries and jobs remain empty. API/worker restart retained event,
accepted message ID and subscription; readiness, TLS preflight and worker process/DB pass.

**FIXES:** cloud ingress was opened by the operator. VPS public-IP loopback remains
unavailable, so Caddy gets PUBLIC_DOMAIN as a Docker network alias. Container
HTTPS preflight uses the real Caddy certificate; separate external probes confirm
actual public reachability. No TLS bypass, token rotation or unrelated services.

**PENDING ORGANIZER ACTION:** Mini App binding; group permission if disabled
(capability currently unverified; GET chats empty, not presumed disabled/enabled).
Resident entry for organizers is `https://domsignal.176-108-244-168.sslip.io/`;
HTTPS/HTML are verified. Mini App binding/initData/client behavior are not.
Callbacks require a genuine product Ticket/WorkAttempt; no artificial smoke Ticket.
No further action is requested from the operator now. Product scenarios remain pending.

Full evidence and continuation boundary: [MAX live smoke](../MAX_LIVE_SMOKE.md).

## Delivery result and roadmap mapping

START HEAD/origin/dev/b-experience `95a6c24`, origin/main `3d4a095`; clean tree.
START fetch, own fast-forward and main sync completed, already up to date. DEV-A
status read from origin/dev/a-core; no writes/push there. Final commit/push evidence
belongs in the session report, without a follow-up hash-only commit. Main requires
the existing second-developer review and current CI; this task does not merge it.
END fetch confirms unchanged main and own remote refs. Required documentation,
local links, conflict markers and final diff whitespace checks pass.

| Existing task | Implemented part; remaining boundary |
|---|---|
| A-05 | A-16 intent consumer, durable per-recipient delivery, leases/recovery/retry/unknown and dialog throttling |
| B-03 | Production send/edit/answer provider and authenticated callback ingress; live acceptance pending |
| B-06 | Personal work-card reconciliation and safe callbacks; group cards/quiet hours remain outside slice |
| B-07 | Opaque personal open_app/start_param and existing Mini App routing; QR/sharing/group transition remain outside slice |
| B-08 | Existing work result/observation connected to personal messages; remaining history/reminder/escalation scope unchanged |
| A-09 | Reused delivery access/staleness safeguards only; reminder scheduler and escalation remain PLANNED |

No new epic, broker, business outbox, lifecycle, admin screen, A-10 or AI work.

## Durable delivery and authorization

WorkerRunner consumes existing `ticket.notification_intent.v1`: SKIP LOCKED claim,
typed payload + stored TicketEvent validation, unique fan-out, reconcile marks and
outbox processed commit together. Candidates are distinct authors of own Reports
for the Incident, then MembershipService/AccessPolicy resident access, current
management, same Ticket and confirmed numeric MAX identity are checked. No house
broadcast/subscriber model is invented. Legacy max_user_id alone does not qualify:
additive max_identity_verified_at is set only by existing validated initData auth.

NotificationDelivery uniquely identifies (outbox, recipient, channel); it stores
Ticket/attempt, random ref, destination, provider mid, desired/applied version,
attempt/retry counters, timestamps, sanitized error and fenced lease. States:
pending, processing, accepted, retry_wait, unknown, failed, superseded, skipped.
`accepted` means validated MAX API response with a persisted mid, never read/push.

Fresh authorization/render runs again after the durable claim immediately before
send/edit/answer, with no domain lock or DB transaction held during HTTP. Changed
management/identity or revoked access suppresses delivery. An old unsent work
attempt becomes superseded. No global User revocation field exists in A-15;
resident access/current management are the available revocation boundary. A change
after the final check cannot atomically retract an in-flight external request.

Only accepted and work_reported produce new personal messages. Other A-16 intents
reconcile already accepted work cards against current ResidentWorkStatus. Renderer
uses controlled category, explicitly public work description and own observation;
never private Report/location, internal cancellation reason or other users' data.
Work verification includes «Открыть и проверить», «Исправлено», «Проблема осталась».
After observation/rework/new attempt, callbacks disappear from rendered cards.

Opaque random `w_…` ref has no embedded IDs or authority. GET
`/api/v1/notification-launch/{ref}` requires an authenticated intended recipient,
current access/management/identity and own Report. Other actors receive masked 404.
Bridge reads start_param, resolver selects the existing Incident Detail/current
WorkAttempt, stale launch shows current work with a notice and focus. Test URL
override requires non-production + server test_auth. No new UI lifecycle.

Webhook secret verification and bounded parser precede durable callback inbox/job.
Callback actor, original provider mid and accepted delivery must match; then the
same A-16 observe service and lock order create ResultObservation. Same event is
deduplicated; another callback ID after one's answer cannot overwrite it. First
historical answer may be recorded with applied_to_current=false, preserving A-16;
it cannot change the newer attempt. Unresolved reopens the same Ticket. Corrections
remain possible through existing Mini App actions. Observation + durable answer
job commit together; provider edit/answer failure cannot roll back business state.
Existing A-16 intents reconcile messages after callback AND Mini App observations.

Production HttpMaxMessagingProvider reuses A-07 MaxHttpClient and existing
base URL/token/timeout/TLS boundary. MAX_BOT_USERNAME is additive configuration,
passed through production Compose; missing value is a terminal configuration
failure, not a fake successful send. POST /messages validates recipient and mid;
PUT /messages and POST /answers require strict boolean success=true. Recording
providers live in tests and require explicit injection; no production fake mode.

Transient rejected sends (429/connect failure) and edit/answer errors use durable
backoff 2/4/8/16 seconds, max five calls per operation/version; Retry-After is
respected up to one hour. Permanent errors stop. Ambiguous POST timeout/5xx/invalid
response or expired send lease becomes unknown and is never blindly resent.
Known mids are retained on edit failure. PostgreSQL destination gate covers all
three operations, with 500ms minimum gap and 90s leases; dialogs are independent.
No exactly-once external send guarantee is asserted.

## Delivery verification actually executed

Dedicated own PostgreSQL 16 container `domsignal-nd-db`, loopback 55478, databases
`domsignal` (integration) and `nd_smoke` (HTTP/browser); existing test containers and
production data untouched. Test-only HTTP provider uses a loopback port and a
synthetic credential; no real MAX token/webhook was used. No dependency changes.

| Command actually executed | Result |
|---|---|
| `uv run ruff format` on explicit changed files; `uv run ruff check src tests scripts migrations`; `uv run mypy src/domsignal` | PASS, 76 source files; final targeted rerun after defensive renderer/ref checks |
| `uv run python scripts/export_openapi.py`; `npm --prefix miniapp run api:generate` | PASS, additive resolver producer/OpenAPI/TS synchronized |
| `uv run python scripts/check.py --scope all` with isolated DATABASE_URL | PASS: 75 unit/contract, 89 frontend unit/component, 119 real PG integration (228.62s), ruff/mypy, TS/typecheck/build and generated drift checks, migration upgrade |
| `uv run pytest tests/contract/test_max_messaging.py -q` | PASS, 22 provider tests: exact wire, strict success, errors/unknown, real composition |
| `uv run pytest tests/integration/test_notifications.py -q` | PASS, 20 integration tests, also included in full gate; rerun after final defensive backend changes |
| `uv run python scripts/notification_smoke.py --browser` with APP_ENV=test, ND_FIXTURES=1, separate migrated nd_smoke DB | PASS HTTP + PG + separate worker/provider processes + actual restart; all 28 browser tests (8 B-02, 19 B-14, 1 ND), 1.2m |
| `uv run python scripts/notification_smoke.py` after readiness/answer assertions | PASS, callback answer observed; same Ticket, two attempts, two observations, two unique mids persist after API/worker restart |
| `uv run python scripts/docker_smoke.py --project domsignal-smoke-nd --api-port 18090` | PASS, clean build/migration/API+worker, Incident persisted after API restart; own smoke project and volume removed |
| `git diff --check` | PASS, no whitespace errors |

ND-01…ND-30 are PASS assertions, not thirty separate test functions: full mapping
is in [acceptance](../../scenarios/acceptance.md#nd--personal-max-delivery).
Kill-test proves unsent #1 superseded, #2 actionable and fabricated old callback
inert; an accepted historical callback is separately checked against newer work.
Two concurrent consumers/delivery workers preserve unique logical fan-out. Access
revocation is also injected between claim and final preflight; no send follows.
Provider failure tests acquire Incident NOWAIT from another connection during HTTP
to verify no domain lock is retained, and exercise the five-call retry bound.

Migration `2aea407269aa` upgrades populated A-16 `20260918_0004` and preserves
Incident/Ticket/attempt/observation/event/outbox history; legacy identity stays
unconfirmed and no fake delivery is backfilled. Empty-slice downgrade/upgrade
passes; populated delivery/verified identity downgrade is explicitly guarded:
restore a pre-delivery backup rather than discard durable external state.

Latest HTTP restart evidence: Ticket `00eefcd0-90be-40f1-a7ba-d64d849e1c34`,
Incident `3e3f438f-8b5f-42f2-8bad-4dd2a4c8879b`, two attempts/two observations,
two mids prefixed `mid.fixture-c7b861625bd447c29a1c0ec91f3232ef-`, with accepted
intent superseded before send. Browser screenshot reviewed at
`miniapp/test-results/nd-resident.png` (ignored local artifact): existing detail,
public work result, own unresolved feedback and current state; no overflow.

Early test runs exposed fixture settings shared across tests and an older migration
snapshot treating the new null identity field as old data; isolated settings and
explicit additive-column exclusion corrected those issues. Smoke retries exposed
reused fake mids and Windows subprocess redirection; per-run mids and direct base
interpreter handles made restart deterministic. Final runs above pass; no tests
disabled to obtain a green result. Existing dependency warnings remain unchanged.

## Official MAX boundary and handoff

Official API checked on 18.09.2026: [send](https://dev.max.ru/docs-api/methods/POST/messages),
[edit](https://dev.max.ru/docs-api/methods/PUT/messages),
[answer](https://dev.max.ru/docs-api/methods/POST/answers),
[Mini Apps](https://dev.max.ru/docs/webapps/introduction),
[Bridge](https://dev.max.ru/docs/webapps/bridge). Current open_app uses web_app +
payload; attached app/client behavior still needs live validation. Current answers
schema exposes message, not a notification field. success=false at HTTP 200 is
failure. Personal dialog guidance is at most two operations/second. Keyboard DM
edits have no documented age limit; other messages have seven days. No documented
POST idempotency guarantee, so uncertain send is unknown. Actual push/read and
mobile/web behavior cannot be inferred from provider acceptance.

Production code is IMPLEMENTED, deterministic integration VERIFIED; real MAX is
NOT LIVE VERIFIED / PENDING TOKEN. Updated unchecked live list is
[MAX_LIVE_SMOKE](../MAX_LIVE_SMOKE.md).
Main/review/CI policy unchanged; no A-10 or next-task work started.

Exactly one recommended next DEV-B task: **B-01 — execute the updated live MAX
delivery checklist with an explicitly allowed token and attached Mini App.**

## Historical B-14 handoff

Updated: 2026-09-18 (B-14)
Branch: dev/b-experience
Current task: B-14 — employee Ticket UI + resident verification
State: PASS / IMPLEMENTED IN BRANCH; NOT MERGED TO MAIN; NOT LIVE VERIFIED

## B-14 result

Explicit owner request supersedes the earlier “B-14 not started” handoffs.
START HEAD/origin/dev/b-experience: `194d91a`; origin/main: `3d4a095`.
Tree was clean. START/END fetch succeeded, refs unchanged; START own ff/main
sync already up to date. DEV-A status read from origin/dev/a-core, no writes there.
Final SHA/push result is in the session report, not a follow-up hash-only commit.
No automatic main merge: second-developer review/current remote CI remain required.

One existing Vite/npm project, two HTML entries: resident `/` and employee
`/admin/`. Employee entry loads no MAX UI/Bridge/CDN; one sidebar item “Заявки”.
Queue uses backend-scoped house pages (20 each), server order/status/assignee
filters, real totals and pagination; detail/URL/back/reload use authoritative reads.
Address comes from /me, title/category/location/counts from authorized Incident API.
No fabricated SLA or priority. All permitted houses appear without loading foreign
scope and filtering it away in React. No Superadmin/onboarding/settings/chat UI.

Detail renders number, state, action panel, assignee, incident, separate attempts,
current-observation summary, paginated history and published typed deadlines.
Only allowed_actions expose implemented commands; unknown values fail safely,
disabled descriptors remain disabled and show reason. Canonical accept performs
claim; no invented claim endpoint. assign gets only scoped paginated candidates,
requires a reason and cannot submit an arbitrary employee. Operator has no assign.
Report form explicitly publishes its text and waits for resident verification.
Existing clarify/wait-external/resume/cancel adapters use required reasons; deadline
editing/calculation is outside this slice. Native dialog adds explicit focus trap,
Escape/return focus, labels and safe field errors.

Existing Incident Detail adds public work-status/latest attempt and attempt-scoped
observations. Confirmation is a resident observation, not an official acceptance.
Late objection reopens the same Ticket; employee “В работе” includes it. Conflicting
observations require another check, not majority voting. A-16 actually records stale
attempt responses as historical with applied_to_current=false; UI honors that source
of truth and refreshes the current attempt. It does not claim a backend HTTP reject.

No new workflow, migrations or HTTP endpoints. Minimal additive internal read DTO:
assignee_name; AttemptView.performer_name/resolved_count/unresolved_count. Counts
use existing backend current-observation revisions, not a frontend decision rule.
Separate ResidentWorkStatus/AttemptPublic remain unchanged, internal fields are
physically absent. Producer/OpenAPI/TS regenerated together; privacy assertions
cover the additions. Published summaries agree in detail and attempt history.

Mutations retain the original body/key for an uncertain retry, prevent double
submit, then await GET. Failed GET after acknowledged POST retries only GET.
No optimistic lifecycle. 403/409 losing claim refetches the winner; 401/403/404
remove cached private content. 422 attaches safe validation to fields; 429/5xx/
network use retryable. History refreshes on version change. No raw error/stack/IDs.
Shared useResource preserves cancellation/out-of-order guards and exposes awaited
read-after-write. No tokens or private responses persist in browser storage.

## B-14 actual commands and evidence

Dedicated PostgreSQL 16.10 container `domsignal-b14-db`, loopback 55477;
`b14_tests` for pytest, `b14_browser` for browser (never concurrently shared).
API 8030 in APP_ENV=test/MAX_TRANSPORT=off. Python 3.12.14, Node 24.19.0,
existing ignored npm launcher; no dependency/lock updates. Browser fixtures require
APP_ENV=test + B14_BROWSER_FIXTURES=1, are CLI-only, and never truncate shared data.
Instructions: [miniapp README](../../miniapp/README.md#b-14--employee-entry-и-browser-fixtures).

| Command actually executed | Final result |
|---|---|
| `uv run ruff format` on explicit changed Python files; `uv run ruff check src tests scripts migrations` | PASS; fixture unused import/formatting corrected |
| `uv run mypy src/domsignal` | PASS, 69 source files |
| `uv run python scripts/export_openapi.py`; `npm --prefix miniapp run api:generate` | PASS, generated OpenAPI/TS |
| `uv run python scripts/check.py --scope frontend`; final targeted typecheck, 15 B-14 component tests and build after dialog feedback cleanup | PASS, 88 frontend tests (73 existing + 15 B-14), final targeted 15/15, production build for both entries |
| `uv run python scripts/check.py --scope all` | PASS: ruff/mypy, 53 unit/contract, 88 frontend, build, OpenAPI/region/TS drift, alembic upgrade, 98 real PG integration (230.95s); A-01/A-15/A-07/A-16 regressions included |
| `uv run alembic upgrade head`; `uv run python -m domsignal.tools.seed_demo`; `uv run python -m domsignal.tools.seed_tickets` | PASS in separate browser DB; no migration added |
| `npm --prefix miniapp run test:browser` with base URL 8030, Chrome and fixture gates | Final PASS 27 (19 B-14 + all 8 B-02), 1.8m; real HTTP/PG vertical path, access/revoke/switch, concurrent claim, late/stale/conflict, idempotent retry, reload, field 422, axe and responsive/themes |
| `uv run python scripts/docker_smoke.py --project domsignal-smoke-b14 --api-port 18089` | PASS clean image/build/PG/migrations/API+worker, persisted Incident after API restart; own smoke project/volume cleaned by script |
| `git diff --check`; repository required files/conflict markers/local documentation links | PASS before commit |

The full backend/PG gate and Docker smoke preceded the final dialog feedback
polish. The final frontend build, targeted component checks and all 27 browser
tests ran after that polish; backend and packaging files were unchanged.

Full vertical scenario: actual Report creates Incident+one Ticket → employee
queue/detail accepts/starts/reports attempt 1 → resident unresolved → same Ticket
returns to work → new attempt 2 → resident resolved → closed → both UI reload.
Direct PostgreSQL snapshot matches HTTP ID/version/status, exactly 2 attempts and
2 observations. Commit-with-lost-response test returns one WorkAttempt after retry.
New backend regression verifies current revision counts, names and history/detail
agreement. Full [UI-TK-01…28 matrix](../../scenarios/acceptance.md#b-14--ui-tk-evidence).

An additional browser regression verifies an in-dialog 409 notice, retained text,
disabled outdated submit and no duplicate WorkAttempt. Final visual review also
waits for loaded queue rows before checking responsive overflow.

First browser run exposed Tab escaping the dialog to browser chrome; explicit
focus trap fixed it. Repeated full run exposed duplicate synthetic address in the
switch fixture; unique isolated fixture addresses fixed repeatability. Final full
27/27 rerun passed, no skipped/disabled checks. Screenshots of employee/resident,
390/768/1024/1366 admin and 320 light/dark resident generated; visual QA performed.
Existing Starlette/httpx deprecation and browser color environment notices remain.

## B-14 limitations and next step

PASS applies to the authorized UI/workflow slice, not production identity or live MAX.
Production admin accepts an existing bearer session in memory and requires sign-in
again after reload; only explicitly enabled non-production test auth offers named
fixtures. A complete employee login provider/MFA is still A-10/B-09, not invented MAX
OAuth. Browser reload lifecycle evidence uses real gated test-session identities.
No live MAX token/chat/callback/notification, real mobile MAX client, public TLS or
external official acceptance was verified. Outbox delivery unchanged. Existing
manual report/group-off/B-02 regressions pass; semantic matching remains outside scope.
Queue composes per-house pages because no cross-house queue endpoint exists; no
claim of large-tenant performance or server-side global sorting. Deadline editor,
photos, employee/resident messaging, Superadmin and onboarding are excluded.

One recommended next DEV-B task after review/merge: A-10 employee web authentication
for this cabinet. Do not start it in this session. Current integration step is DEV-A
review and green merge-result CI; main stays unchanged.

## Previous A-16 handoff — historical evidence

Updated: 2026-09-18 (A-16 backend)
Branch: dev/b-experience
Current task: A-16 — Ticket backend
State: PASS / IMPLEMENTED IN BRANCH; NOT MERGED; NOT LIVE VERIFIED

## A-16 result and boundaries

Owner authorization: A16_TICKET_BACKEND_CODEX.md, iterations 1–2 agreed;
the earlier docs-only prohibition below is historical and superseded for A-16.
Start HEAD/origin/dev/b-experience `0bbe6a4`; origin/main `3d4a095`.
Fresh refs fetched at START and END; own ff/main sync at START already up to date;
END refs unchanged. DEV-A handoff read from origin/dev/a-core; no AI/DEV-A writes.
Initial working tree clean; no unrelated WIP to move/stash. IMPLEMENTATION_CONTEXT
is intentionally unchanged: its verified-main table must not describe branch-only work.
Final commit/push SHA is reported in the final response, without a hash-only follow-up commit.

Implemented models: Ticket, WorkAttempt, ResultObservation, TicketEvent,
TicketDeadline; additive migration `20260918_0004`. No duplicated tenant source:
Ticket → original Incident house/management via composite FK → HouseManagement.
Partial unique active Ticket per Incident includes all six nonterminal statuses.
Composite FK checks latest attempt belongs to Ticket; attempt numbers unique per
Ticket; global DB identity number rendered `T-N`, stable with permitted gaps.
Scope, creation authorship and number immutable; attempt identity/report immutable,
rework only false→true; observations/events/deadlines append-only. Downgrade fails
with new history/config instead of deleting it. No historical backfill/intents.

Common ReportService.create_in_context calls ensure inside its transaction after
authorized Report persistence, including A-07 manual group intake. Flag
HouseManagement.ticket_intake_enabled defaults false; explicit test/demo enabling
does not verify a real organization. Existing/manual disabled path unchanged.
One active responsible → assignee while new; several/none → house queue, null
assignee; unknown category other → needs_clarification. Company admin sees reserve
and revoked-assignee tasks. Reassignment clears acceptance; work must be accepted
personally, preserving attempt snapshots of the previous employee.

Central core transitions and service authorization implement new→accepted→
in_progress→verification_pending→closed, clarification/external waiting/resume,
reasoned cancellation. Work report is an event and new attempt. No employee close,
silent/timeout close or external registration. Resident needs current basis and own
Report; canonical User identity cannot verify its own performed/reported attempt.
Resolved closes only without current objections and without rework. Late unresolved
reopens the same latest Ticket; rework is permanent on that attempt. Correction
appends a server revision; old positive answers cannot close without a new attempt.
Old/cancelled/superseded attempts remain historical, and response flags say whether
the observation affected current work. Conflicting opinions remain visible.

House SHARE → Incident FOR UPDATE is the common write lock order, including
absence/ensure/reopen. Expected version guards staff commands; resident observations
are serialized without rejecting a valid late answer for a changed Ticket.version.
Existing idempotency_records and ReliabilityRepository are reused; report intake
adds an advisory transaction lock for same-key concurrency. Ticket receipts contain
effect IDs/version, not private snapshots. Replay rechecks access/ownership and
returns current state plus original effect_version/replayed. Same key/different body
is a defined 409; revoke cannot replay old success. Internal DB uniqueness supplements
the serialized decisions rather than serving as the normal conflict handler.

HTTP/DTO handoff: [A-16.1 contract](../CONTRACTS.md#a-161-http-и-handoff-b-14).
Staff list/detail/assignee lookup, assign/accept/start/clarify/wait-external/resume/
cancel/work-attempts/deadlines, paginated events/attempts/observations/deadlines;
resident work-status, authorized observation POST and own observation history.
Existing Bearer/AccessPolicy/OperationContext; 404 foreign scope, 403 action,
409 transition/version/key, mandatory Idempotency-Key; bounded pagination/totals.
Separate ResidentWorkStatus allowlist excludes employees, service notes, other
comments/reports and agreement references. TicketAction does not change B-00 actions.
C0.1 plus additive A-16.1; app/OpenAPI version remains 0.1.0; generated TS updated
only by npm run api:generate. Test-session enum adds only named a16-* demo aliases;
the existing production prohibition remains enforced.

Deadline facts separate response/completion/next_update and internal/agreed/normative;
anchor references a same-Ticket event/time, due may be null; changes preserve revision,
author and reason. Agreement requires recorded source/time (staff attestation, not
independent external verification). Existing region rule is demo with due_at=null:
normative HTTP creation is unavailable until verified A-02 applicability exists.
No clock pause for waiting_external, universal repair deadline or SLA calculator.

Each accepted change persists state + event + existing OutboxMessage in one
transaction; unique dedupe_key ties intent to event. Typed safe references, context,
version and audience only; no comment/auth/token copies. Kind
ticket.notification_intent.v1 stays pending, with no registered delivery handler.
Work_reported/to_status records both report and pending verification. Future sender
must recheck recipient/scope/management/binding and latest state, never broadcast to
all house chats or send a stale fixed result after reopen. No SENT/READ/exactly-once claim.

## A-16 actual verification evidence

Dedicated PostgreSQL 16.10 container `domsignal-a16-db`, host port 55476; final suite
DB `a16_final`, separate network/browser DB `a16_smoke`. Existing databases untouched.
Local Python 3.12.14, Node 24.19.0 (within declared 24.x range); ignored local npm
launcher selects bundled Node, dependency/lock changes not required. Docker uses
the existing pinned Node 24.21.0/Python 3.12.11 images. MAX off outside explicit
A-07 fake-provider tests; no live token/webhook/provider or AI calls.

| Actual command / check | Result |
|---|---|
| `git fetch origin`; `git merge --ff-only origin/dev/b-experience`; `git merge --no-edit origin/main` | PASS; START sync already up to date; END fetch same refs |
| `uv run alembic revision --autogenerate -m 'A16 ticket work and resident verification' --rev-id 20260918_0004` | Draft generated, reviewed; dependency order/FK cycle/downgrade guard/history triggers hardened |
| `uv run alembic upgrade head`; `uv run alembic check` | PASS clean PostgreSQL; no model drift; also exercised in migration tests |
| `uv run pytest tests/integration/test_tickets.py -x -q` and subsequent targeted added scenarios | Initial 23 PASS; final expanded file 31 PASS in full suite. A new test initially missed an import; fixed before final run |
| `uv run pytest tests/integration/test_ticket_migration.py -x -q` | PASS populated A-07 preservation, repeated upgrade, drift, guarded downgrade |
| `uv run python scripts/export_openapi.py`; `npm --prefix miniapp run api:generate` | PASS; generated files not manually edited |
| `uv run python scripts/check.py --scope all` | Final PASS: ruff, mypy (69 files), 53 unit/contract, 73 frontend, frontend typecheck/build, OpenAPI/region/TS drift, clean migration and 97 PG integration; integration 190.27s |
| `npm --prefix miniapp run test:browser` with PLAYWRIGHT_BASE_URL=http://127.0.0.1:8026, PLAYWRIGHT_CHANNEL=chrome | PASS 8 / 18.8s, including actual API→PG→board/detail/reload; 320/430/1280 light/dark, keyboard/accessibility/unknown values |
| `uv run python scripts/docker_smoke.py --project domsignal-smoke-a16 --api-port 18087` | PASS clean build/PG/migrations/seed/API+worker and persisted Incident after API restart; own project cleaned by existing script |
| `uv run python -m domsignal.tools.seed_tickets`; `uv run python scripts/ticket_smoke.py --base-url http://127.0.0.1:8026` | PASS actual network HTTP Report→Ticket→accept→start→attempt→resolved→late unresolved→read, version 6 |
| Separate Compose `domsignal-smoke-a16-ticket`, port 18088: seed_tickets; ticket_smoke; `docker compose ... restart api worker`; ticket_smoke `--read-incident d9544cd6-c107-43fd-b5d0-a45dd610f69f` | PASS after actual API AND worker process restart: same Ticket c816f50a-ee3a-45e5-b65b-3dc882352a7c, version 6, in_progress/rework; SQL confirmed all 6 intents pending |
| `git diff --check`; repository-sanity + relevant local Markdown links | PASS (final pre-commit check) |

Full final suite includes all previous 65 PG integration cases plus 32 A-16 cases
(31 HTTP/PG + populated migration), with no regression suppression. Two existing
AccessPolicy permission assertions were extended to the implemented Ticket/resident
permissions; old scope assertions remain. [TK-01…26 mapping](../../scenarios/acceptance.md#a-16--backend-evidence-18092026)
preserves C/MT/CB/QA IDs and separates future UI/delivery/live evidence.
Concurrency uses independent DB sessions, simultaneous HTTP requests, and an
explicit held PG aggregate lock; it is not sequential simulation. SQL rollback
fault injection checks no partial Report/Incident/Ticket/Event/Intent. Existing
Starlette/anyio deprecation warnings and browser color notice remain non-failing.

The host-process restart command was rejected by automatic execution policy;
the restart requirement was instead completed through the scoped Compose project.
The loopback browser-test API at 8026 and dedicated PG container at 55476 remain
available locally; no new scheduled/background automation was created. The separate
Compose Ticket smoke was stopped with down; its test volume is retained.

## Reproduce A-16 network smoke

Use a fresh isolated Compose project and an unused loopback port, not a shared DB.
PowerShell example (MAX_TRANSPORT remains off in the checked-in Compose):

```powershell
$env:API_PORT='18088'
docker compose -p domsignal-smoke-a16-ticket up --build -d
docker compose -p domsignal-smoke-a16-ticket exec -T api python -m domsignal.tools.seed_tickets
uv run python scripts/ticket_smoke.py --base-url http://127.0.0.1:18088
docker compose -p domsignal-smoke-a16-ticket restart api worker
# Wait for /ready, then substitute the incident_id printed by the previous command:
uv run python scripts/ticket_smoke.py --base-url http://127.0.0.1:18088 --read-incident <incident_id>
docker compose -p domsignal-smoke-a16-ticket down
```

The idempotent seed adds synthetic roles/two organizations/three houses, without
resetting data or granting real access. Repeated smoke creates an explicit new
test report; no generic Ticket create, public seed/reset, or automatic old-data work.

## A-16 status, limitations and next step

- A-16 backend: PASS / IMPLEMENTED IN BRANCH. A-01/A-15/A-07/B-02 regression PASS.
- MERGED: no; origin/main remains 3d4a095. Remote CI/review are separate from local PASS.
- LIVE VERIFIED: no. MAX delivery/UI/callbacks/live clients, real organization
  connection and normative applicability NOT RUN. B-14 and other roadmap work not started.
- Existing core still creates a new Incident per ordinary Report; linked-report
  fixtures do not claim semantic matching. Existing assignment roles cover routing;
  no category rules or responsibility verification were invented.
- No normative calculator/verified deadline source, join flow, photo/voice,
  full admin/web-auth/MFA, official registration, archival tenant transfer or retention
  platform. Current safety UI/path unchanged; no AI/emergency classification added.
- Next single step: DEV-A review of the A-16 branch and current remote CI before a
  normal PR merge. Do not automatically start B-14, MAX delivery or the next roadmap task.

## Previous Q&A documentation handoff — historical evidence

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

The next DEV-B step is to finish B-01 live feasibility after a public HTTPS VPS/DNS
endpoint is available, using the issued token and isolated bot/chats. Do not start
A-10/Mini App binding or unrelated product work from this handoff. Review/CI of
this branch precedes main merge.

## A-12/B-01 production webhook bootstrap — 18.09.2026

Production Compose is now a fail-closed live overlay: `APP_ENV=production`, test
session and demo seed disabled, fixed webhook transport/bot username/API origin,
required token/webhook/session/DB secrets, HTTPS public origin/CORS, DB-backed API
readiness, restart policies and private PostgreSQL. Caddy remains the single HTTPS
edge and keeps persistent certificate state. The runtime trust store includes the
Russian Trusted Root CA used by the current `platform-api2.max.ru` chain; TLS
verification is not disabled.

Settings reject short/template session and DB secrets, missing/template MAX
credentials, non-webhook production transport, another bot username/API origin,
HTTP/path/non-default-port public URLs and invalid CORS. Production composition
still selects only `HttpMaxChatProvider`/`HttpMaxMessagingProvider`; deterministic
fakes remain tests-only. Contract coverage proves production test auth is disabled,
and webhook authentication returns 401 before parsing while valid secret + `{}`
reaches the expected 422 payload rejection.

Added `deploy/.env.example`, a copy-paste VPS/Caddy/Compose runbook and guarded
`python -m domsignal.tools.max_subscription`. The operator tool verifies `GET /me`,
lists subscriptions, refuses every foreign/multiple-URL conflict, checks public
`/ready` and webhook 401/422, then registers the exact official six update types.
Update/secret rotation uses documented POST for the same URL; DELETE targets only
that exact URL and verifies removal. HTTP 200 with `success=false` always fails.
Application startup never creates, replaces or deletes a subscription.

Read-only live evidence from the built runtime image: TLS validation succeeded;
`GET /me` matched `t480_hakaton_max_bot`; `GET /subscriptions` returned `[]`.
No POST/DELETE, polling, public deployment or synthetic live event was performed.
There is no public HTTPS hostname/VPS in this environment, so external `/ready`,
subscription registration and real `bot_started`/message/callback delivery remain
PENDING PUBLIC HTTPS / NOT LIVE VERIFIED. Mini App binding and A-10 were untouched.

Relevant evidence:

| Command/check | Result |
|---|---|
| `uv run ruff check ...`; `uv run mypy src/domsignal` | PASS; mypy 77 source files |
| `uv run python scripts/check.py --scope backend` | PASS: ruff, mypy 77 source files, 96 unit/contract tests |
| isolated PostgreSQL: Alembic head + `test_chat_bindings.py test_notifications.py` | PASS, 58 tests |
| `uv run python scripts/docker_smoke.py --project domsignal-smoke-max-live-final --api-port 18092` | PASS; final image migration/seed/API/worker/restart persistence, isolated volume removed |
| production Compose config with safe synthetic env | PASS; DB has no published ports, API is loopback-only, Caddy 80/443 |
| production Compose with missing env; runtime with template values | FAIL CLOSED as expected |
| `caddy validate`; root certificate subject/validity/SHA-256 | PASS |
| built-container guarded `list` with issued token | PASS; correct bot and zero subscriptions, no mutation |

Canonical commands and manual VPS/DNS/secrets boundary are in
[`deploy/README.md`](../../deploy/README.md); the live evidence boundary remains in
[`MAX_LIVE_SMOKE.md`](../MAX_LIVE_SMOKE.md). Final exact test counts, diff check and
commit SHA belong to the session report after the final checkpoint.
