# DEV-B — current handoff
Updated: 2026-09-18 (A-15)
Branch: dev/b-experience
Current task: A-15 — tenant/access foundation
State: PASS / IMPLEMENTED IN BRANCH; B-02 current binding PASS

## Delivery boundary

| Slice | State | Evidence |
|---|---|---|
| A-01 / C0.1 | PASS / IMPLEMENTED IN BRANCH | Parent `e66c351`, producer/OpenAPI/TS; existing regressions rerun |
| A-15 | PASS / IMPLEMENTED IN BRANCH | Migration 0002, access policy/resolver/scoped reads; A-15 MT-01…MT-10 all PASS |
| B-02 | PASS / IMPLEMENTED IN BRANCH | Real API/PG board/detail/create/reload and masked 404 cache clearing |
| A-07 / A-16 / admin UI | NOT STARTED | No ChatBinding/MAX onboarding/Ticket/admin endpoints or UI |

Start after fetch: own branch/remote `e66c351`, main `3d4a095`. START own
fast-forward/main merge already up to date; colleague handoff read from
origin/dev/a-core without modifying that branch. Main approval/merge not performed.
IMPLEMENTATION_CONTEXT retains verified main baseline with a branch pointer,
not a false MERGED label. Final commit SHA is delivered in the final report.

## Implementation and important limits

ManagementCompany is tenant; House has no permanent tenant_id. HouseManagement
stores temporal `[from,to)` tenant/house association, basis, actor/timestamps and
is_demo. PostgreSQL btree_gist exclusion prevents intersecting active periods
(including finite/future/concurrent inserts), plus application overlap validation.
Adjacent periods work. Internal ManagementService uses caller-owned transactions;
no public maintenance/admin API. House row locks serialize switch/report creation.

OrganizationMembership company_admin/operator is active/revoked. Company admin
has all current houses of its active company; operator needs active
HouseAssignment operator/responsible on that management. Assignments are never
copied on switch. ResidentMembership is house-bound, active/revoked/expired with
source/verification/expiry; it proves product access only. Legacy role/evidence
are retained solely for rollback, never used as employee rights. Separate nullable
User.platform_role=superadmin deliberately has no private read-all grant.

Incident.management_id is non-null alongside house_id. Composite FK references
UNIQUE(management.id, house_id); triggers protect incident scope and management
tenant/house from rewriting. Indexes cover tenant/house/current management,
unique membership/assignment lookup, incident house/status and management/status.

Existing MembershipService resolves immutable OperationContext on every request:
identity → active management/company → organization/assignment/resident basis →
AccessPolicy. Tenant/management are KNOWN; chat fields NOT_APPLICABLE. Permissions
are incident.read/report.create only. Revocation/expiry applies without login;
worker also re-resolves before report creation. Client tenant/management/role/chat
metadata never grants rights. Body extras 422. Missing/foreign scope 404 with the
same problem content; visible scope without action permission 403.

Incident content queries require context and constrain house+management. Optional
house selector must match. Without selector only house routing ID is read before
scope resolution. No DTO is built from unauthorized content. Board/detail expose
current management only, including residents. Historical rows remain immutable,
but archive/own-history-after-revoke endpoints are NOT implemented. New Beta does
not see old Alpha incidents. Resident basis survives switch; new reports use new
management; old receipt retry is checked again and returns 404, no duplicate effect.

Migration preserves C0.1/demo IDs/text/reports; demo company/management retain
provenance. Resident source=demo/manual, verification=unverified, verified_at=null.
Non-demo legacy houses get isolated suspended/legacy_unverified management, no
invented active production ownership. Pristine C0 backfill downgrade is supported;
new assignments/org grants/revokes/switches/platform roles fail closed and require
pre-A15 backup for rollback. Existing ORM idempotency constraint name aligned with
published 0001 for alembic check; no change to its uniqueness or original revision.

API paths/report/incident DTO unchanged; /me.houses.role adds operator/responsible,
admin remains the public company_admin descriptor. Generated OpenAPI/TS regenerated.
Capabilities unchanged, allowed_actions=[]: no unimplemented role-derived actions.
PostgreSQL-only is enforced in Settings and engine factory; no SQLite fallback or
runtime dependency existed. Ignore patterns are unrelated tooling and retained.

## Actual commands and evidence

Windows / Python 3.12.14, Node 24.19.0 in runner PATH (npm launcher 10.9.7),
Docker build Node 24.21.0; PostgreSQL 16.10 in dedicated domsignal-a15-db,
loopback 55474. Browser API 8019, Chrome channel, MAX_TRANSPORT=off.
No shared DB/session reset, live MAX network/subscription operation or VPS deploy.

| Command actually executed | Result |
|---|---|
| `uv run ruff check src tests scripts migrations --fix` / final without `--fix` | PASS after initial import/line-length corrections |
| `uv run ruff format <explicit changed Python files>` | Applied only to this slice |
| `uv run mypy src/domsignal` | PASS, 53 source files; initial repository Any returns corrected |
| `uv run pytest tests/unit tests/contract` | PASS, 27 |
| `uv run alembic upgrade head` | PASS on clean PostgreSQL, 0001 → 0002 |
| `uv run pytest tests/integration -x -q` | PASS, existing 9 before adding A-15 tests |
| `uv run pytest tests/integration/test_tenant_access.py -x -q` | PASS, initial 15; final 16 incl. concurrent exclusion in full suite |
| `uv run pytest tests/integration/test_migrations.py -x -q` | PASS, one harness test; initial old ORM constraint-name mismatch corrected |
| Harness: `python -m alembic upgrade 20260917_0001`, `upgrade head` twice, `check`, `downgrade 20260917_0001`, `upgrade head`, `downgrade base`, `upgrade head`, `check` | PASS in uniquely named temporary PostgreSQL DB, preserved legacy/demo/non-demo records |
| `uv run python scripts/export_openapi.py` | PASS, generated |
| `npm --prefix miniapp run api:generate` | PASS, generated |
| `uv run python scripts/check.py --scope all` | PASS: backend + frontend + contracts + PostgreSQL integration |
| Expanded: `npm run typecheck`, `npm run test -- --run`, `npm run build` in miniapp | PASS, 73 frontend tests and production build |
| Expanded: `uv run python scripts/export_openapi.py --check`, `uv run python scripts/validate_region_pack.py`, `npm exec openapi-typescript -- ../docs/openapi.json -o <temp>/schema.ts` | PASS, OpenAPI/TS/region drift |
| Expanded: `uv run pytest tests/integration` | PASS, 26 tests including migration harness and all MT tests |
| `uv run python scripts/docker_smoke.py --project domsignal-smoke-a15 --api-port 18085` | PASS, clean Compose DB/migration/seed/API+worker/restart; dedicated smoke volume removed |
| `docker compose -f compose.yaml -f compose.prod.yaml config --format json` with synthetic config-only env | PASS, no db published ports, db/api/worker/caddy share default network |
| `uv run pytest tests/integration/test_tenant_access.py::test_mt07_management_switch -q` | PASS; prepares meaningful switch dataset for restore check |
| `uv run python scripts/backup_postgres.py --container domsignal-a15-db --directory <temp>/domsignal-a15/backups` + seven calls to same backup function | PASS, 8 pg_dump successes, last 7 retained |
| `docker exec domsignal-a15-db createdb -U domsignal a15_restore_verification`; `docker cp <dump> ...:/tmp/a15-restore.dump`; `pg_restore -U domsignal -d a15_restore_verification --exit-on-error --no-owner --no-acl /tmp/a15-restore.dump` via docker exec | PASS, all 15 table counts/full-row hashes identical; temporary restore DB dropped |
| `uv run uvicorn domsignal.main:create_app --factory --host 127.0.0.1 --port 8019` with test/off env | Real browser API started |
| `npm --prefix miniapp run test:browser` with PLAYWRIGHT_BASE_URL=8019, PLAYWRIGHT_CHANNEL=chrome (explicit Node 24 npm-cli) | PASS, 8; initial default headless shell missing, rerun using installed Chrome |
| `uv run pytest tests/integration/test_tenant_access.py::test_mt03_resident -q` | PASS, final extra assertion: foreign report create 404 and no data mutation |
| `git diff --check` | PASS |

B-02 browser screenshots inspected (ignored miniapp/test-results/real-detail.png).
Real create/board/detail/reload, outsider 404 clears private cached detail, retry,
keyboard/axe/contrast, 320/430/1280 light/dark and unknown/null data all PASS.
No frontend UI implementation change needed; one browser expectation moved 403→404.
Existing Starlette/httpx/anyio deprecation and browser color-env notices remain;
no checks suppressed. Query-plan benchmarking was not needed for this fixture scale.

A-15/MT-01…MT-10 individual outcomes are in scenarios/acceptance.md, separately
namespaced from the wider ARCH MT-01…MT-20 target matrix. Full platform scenarios
are not claimed PASS by the foundation tests.

## Deployment / recovery / next

Existing production Compose already keeps PostgreSQL private; no deployment
performed or broker added. scripts/backup_postgres.py and deploy/database.md cover
pg_dump, last-seven rotation, protected off-host target guidance, restore commands
and guarded downgrade. Local restore VERIFIED; off-host copies/scheduler/VPS
restore are NOT VERIFIED/NOT CONFIGURED, not an asserted backup platform.

NOT VERIFIED: live MAX Web/iOS/Android, real initData/webhook/host reload, public
TLS/VPS and external providers; second-developer review/current main CI/merge.
ChatBinding/Ticket/onboarding/admin UI and archive-history APIs remain out of scope.

One recommended next DEV-B task after review/integration: **A-07 — verified house/chat
connection**, separately authorized. It has not started; do not begin A-16 or admin UI.
