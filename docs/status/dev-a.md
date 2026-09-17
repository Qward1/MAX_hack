# DEV-A — current handoff
Updated: 2026-09-17T15:35:00+03:00
Branch: dev/a-core
Current task: FND-01
State: READY_FOR_REVIEW

## Active/recent tasks

| ID | State | Result / blocker | PR or tested reference |
|---|---|---|---|
| BOOT-01 | BASELINE | Repository workflow was present on main before this task | `a70df01` |
| FND-01 | READY_FOR_REVIEW | C0 UI→API→PostgreSQL slice, auth boundary, jobs, generated contracts, Compose/Caddy and real checks implemented; live MAX remains not verified | local `dev/a-core`; PR pending owner action |

## Result

- Test session → closed demo house membership → manual Report/Incident → board/detail → reload works.
- C0 OpenAPI 3.1 and generated TS types are synchronized; routes/appeals are absent and capabilities are false.
- PostgreSQL inbox/outbox/jobs include commit-before-accept, `SKIP LOCKED` lease recovery and stale-token protection.
- MAX initData HMAC has negative tests; transport is only off/recording and normalized replay is explicitly diagnostic.
- One backend image serves API/static and runs worker/migrate/seed; production overlay adds Caddy without webhook side effects.

## Checks

- `python scripts/check.py --scope backend`: pass — ruff, strict mypy, 13 unit/contract tests.
- `python scripts/check.py --scope frontend`: pass — TypeScript, 2 Vitest tests, Vite production build.
- `python scripts/check.py --scope contracts`: pass — OpenAPI, generated TS and region schema have no diff/errors.
- `python scripts/check.py --scope integration`: pass against PostgreSQL 16 — 5 tests.
- `python scripts/docker_smoke.py --project domsignal-smoke-local`: pass — clean store, create, API restart, persisted read, cleanup.
- Playwright real-browser check: pass at desktop/mobile — create, board refresh, reload, detail, error-free console after favicon fix.
- Local and production-overlay `docker compose config --quiet`: pass with explicit safe production variables.

## Not verified / blockers

Live MAX initData/webhook/API, real MAX group permissions, public DNS/TLS deployment and organizer DATA-API format were not tested. Legal routes, appeals, reminders, classifier quality and the complete demo scenario are intentionally outside FND-01.

## Next

DEV-B reviews C0 semantics and mobile UX, then A opens the PR and CI verifies the GitHub merge result. After merge, the integrator updates `IMPLEMENTATION_CONTEXT.md`; A can begin A-01…A-05 and B can begin B-02…B-05 against the published C0 boundary.

## For teammate

Use `docs/openapi.json`, `miniapp/src/shared/api/schema.ts`, `MaxTransport`, `NormalizedInboundEvent` and capability flags. Do not infer a live MAX payload from diagnostic replay or expose appeals/routes before their contracts exist.
