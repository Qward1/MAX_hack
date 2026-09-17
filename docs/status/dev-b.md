# DEV-B — current handoff
Updated: 2026-09-18 (A-01 / C0.1)
Branch: dev/b-experience
Current task: A-01 — C0/B-00 convergence + request context foundation
State: A-01 PASS; B-02 DONE for current C0.1 binding; IMPLEMENTED IN BRANCH

## Result and delivery boundary

| ID | State | Evidence |
|---|---|---|
| B-00 | DONE | Original target UX/acceptance; future workflows remain TARGET |
| A-01 | PASS / IMPLEMENTED IN BRANCH | Producer + OpenAPI + regenerated TS + consumer + regression tests in this commit |
| B-02 | DONE / IMPLEMENTED IN BRANCH | Producer blocker removed; real API/PostgreSQL/create/board/detail/reload, components and browser checks rerun |
| A-15 / A-07 / A-16 | NOT STARTED | Tenant persistence/isolation, chat onboarding and Ticket remain separate tasks |

Start refs after fetch: `origin/main=3d4a095`, own branch/remote `804f198`.
START fast-forward/merge origin/main were already up to date. Colleague status
read from origin/dev/a-core; that branch/status were not modified. A-01 is not
MERGED TO MAIN and not LIVE VERIFIED. No main merge, force push or history rewrite.
Commit SHA is provided in the final handoff, without a hash-only follow-up commit.

`IMPLEMENTATION_CONTEXT.md` remains the verified main baseline: ownership rules
16 / WORKFLOW WRITERS require its refresh after an accepted main merge. Current
branch progress is here; PRODUCT_ARCHITECTURE TARGET is unchanged.

## C0 → C0.1 contract decisions

- Legacy string `view` removed. ActionDescriptor is `{code, enabled, reason}`
  with canonical B-00 vocabulary and nullable required reason. Actual actions
  are `[]`: no unsupported appeal/join/filing/feedback actions or fake endpoints.
  Navigation remains available for returned resources; API checks access again.
- Five B-00 capabilities included in both `/capabilities.features` and
  `/me.capabilities`: miniapp=true; group_mode/photo_analysis/voice/admin=false.
  Existing useful C0 flags retained, unsupported flags false. Version c0.1.
- Provenance.origin independent of rule.verification_status/verified_at.
  Manual actor reports → user_reported; demo house → demo. Existing DemoRule
  explicitly stays demo, verified_at=null. No verified→official conversion.
- report_count counts rows; participant_count counts distinct Report.author_id.
  Board uses one batched aggregate, detail uses stored reports. No claim of
  verified residency; schema permits null for future sources without identity.
- Summary/detail expose location (entrance/floor/label), updated_at and due_at
  as null because storage lacks them, plus counts/is_demo/provenance/actions.
  Reports remain real messages; route/responsible/explanation/appeal/history
  absent because C0 has no rule engine result or lifecycle event storage.
- Stable application/problem+json: type/title/status/code/detail/retryable/
  trace_id/field_errors. request_id/errors removed in atomic producer/consumer
  migration; X-Request-ID kept and server generated. Validation input/ctx/raw
  auth/unknown extra-field names and internal exceptions are not disclosed.
  OpenAPI describes runtime media type, including framework 404/405 and 500.
- Existing endpoints and report body retained. Old idempotency receipts preserve
  effect/IDs, recheck access and publish the current read representation, never
  replay legacy DTO JSON. C0 reported filing semantics were not expanded.

## OperationContext and isolation

Existing MembershipService.require_house now returns internal immutable context
from authenticated identity and stored membership; services use its actor/house.
Known actor/house are required. Tenant/management ScopeValue=UNKNOWN;
chat binding/source chat/binding version=NOT_APPLICABLE for current direct API
and diagnostic replay. KNOWN requires a value; other states prohibit one.
Source/roles/permissions are resolved internally, never from public metadata.

Incident optional house_id selector must match the resource and authorized
membership. Direct ID rechecks access; absent house in create/resolver fails
closed. Miniapp requires selection for multiple houses; invalid/empty selector
never falls back. Client tenant/chat/start_param/role metadata cannot grant
access; extra body fields rejected. Diagnostic replay previously ignored bearer
actor: it now checks external identity and house before inbox, and worker keeps
its execution-time membership check.

**NOT IMPLEMENTABLE UNTIL A-15:** real two-tenant isolation, HouseManagement
periods, organization/resident assignments, tenant scope revocation/change.
ChatBinding lifecycle/version and real MAX chat access additionally require A-07.
No fake tenants, bindings, RBAC platform, Ticket, lifecycle actions or AI/NLP
changes. Target resolution chain is documented in CONTRACTS; UNKNOWN is not a
future tenant authorization grant.

## Checks actually executed in this session

Environment: Windows, Python 3.12.14, Node 24.21.0 (explicit PATH), PostgreSQL 16
in newly created isolated `domsignal-a01-db`, loopback 55473. Browser API on 8018,
MAX_TRANSPORT=off; no shared DB/session reset or MAX network/subscription action.

| Command | Actual result |
|---|---|
| `uv run python scripts/export_openapi.py` | PASS; OpenAPI regenerated |
| `npm --prefix miniapp run api:generate` | PASS; TS regenerated, no manual generated edits |
| `uv run python scripts/check.py --scope backend` | PASS; also repeated within all |
| `uv run ruff check src tests scripts migrations` | PASS |
| `uv run mypy src/domsignal` | PASS, 50 source files |
| `uv run pytest tests/unit tests/contract` | PASS, 15 tests (includes context invariant and runtime problem/schema/security) |
| `uv run python scripts/check.py --scope integration` | PASS; also repeated within all |
| `uv run alembic upgrade head` | PASS on isolated PostgreSQL, no new migration |
| `uv run pytest tests/integration` | PASS, 9 tests; existing worker/lease/rollback retained, counts/access/receipt/replay regression added |
| `uv run python scripts/check.py --scope contracts` | PASS; also repeated within all |
| `uv run python scripts/export_openapi.py --check` | PASS, no drift |
| `uv run python scripts/validate_region_pack.py` | PASS |
| `npm exec openapi-typescript -- ../docs/openapi.json -o <temporary schema.ts>` (miniapp) | PASS, generated comparison performed by contracts check |
| `uv run python scripts/check.py --scope all` | PASS; 15 backend, 72 frontend, 9 integration at that point |
| `uv run python scripts/check.py --scope frontend` | PASS, rerun after final empty-selector regression |
| `npm run typecheck` (miniapp) | PASS |
| `npm run test -- --run` (miniapp) | PASS, final 73 tests |
| `npm run build` (miniapp) | PASS, production bundle |
| `npm --prefix miniapp run test:browser` | PASS, 8 tests against real API and fixture error/layout branches |
| `git diff --check` | PASS |

Browser evidence: actual HTTP → PostgreSQL → create/board/detail/reload;
real outsider 403 clears private detail; network retry; unknown status/action/
origin and nulls; 100 cards; 320/430/1280px light/dark; no horizontal overflow;
keyboard and axe including contrast. Screenshots inspected in ignored
`miniapp/test-results/` (real detail and narrow dark long-content page).
Initial ruff implementation checks found formatting/UP046 issues, fixed before
the final PASS. Existing Starlette/httpx/anyio deprecation notices remain;
no checks suppressed. No standalone frontend lint exists.

## NOT VERIFIED / next

Live MAX Web/iOS/Android, actual initData/webhook/appearance/reload host behavior,
public TLS deploy and external integrations: NOT VERIFIED. Browser emulation
is not MAX evidence. Full golden path, future MT-01…MT-20 and future B-00 actions
are not declared PASS. Main CI/second-developer approval and merge are pending.

One recommended next DEV-B task: **A-15 — minimal tenant/access foundation**,
as a separately authorized slice. It has not started. DEV-A should review this
producer/context boundary before a PR can be merged; no merge bypass.
