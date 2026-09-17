# DEV-A — current handoff
Updated: 2026-09-17T22:15:00+03:00 (ownership metadata only)
Branch: dev/a-core
Current task: FND-01
State: READY_FOR_REVIEW

## Active/recent tasks

| ID | State | Result / blocker | PR or tested reference |
|---|---|---|---|
| BOOT-01 | BASELINE | Repository workflow was present on main before this task | `a70df01` |
| FND-01 | READY_FOR_REVIEW | C0 UI→API→PostgreSQL slice, auth boundary, jobs, generated contracts, Compose/Caddy and real checks implemented; live MAX remains not verified | local `dev/a-core`; PR pending owner action |
| A-03/AI | NEXT | NLP extraction/risk baseline and evaluation under the new AI/NLP/ML ownership; no product backend or public DTO implementation is assigned here | Starts after FND-01 handoff/review boundary |

## Result

- Test session → closed demo house membership → manual Report/Incident → board/detail → reload works.
- C0 OpenAPI 3.1 and generated TS types are synchronized; routes/appeals are absent and capabilities are false.
- PostgreSQL inbox/outbox/jobs include commit-before-accept, `SKIP LOCKED` lease recovery and stale-token protection.
- MAX initData HMAC has negative tests; transport is only off/recording and normalized replay is explicitly diagnostic.
- One backend image serves API/static and runs worker/migrate/seed; production overlay adds Caddy without webhook side effects.

## Checks recorded for FND-01

These results are preserved from the FND-01 handoff at `dev/a-core@c939ccf`.
The organizational ownership patch did not rerun or upgrade them.

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

DEV-B reviews C0 semantics and mobile UX, then DEV-A opens the FND-01 PR from
its own branch and CI verifies the GitHub merge result. After an accepted merge,
integrator DEV-B updates `IMPLEMENTATION_CONTEXT.md`. DEV-A then takes A-03/AI:
typed category/field extraction, risk signal, uncertainty/fallback and an
evaluation regression set. A-08 follows only if a useful provider is available;
no RAG/vector DB/multimodality is added to manufacture AI work.

## For teammate

Use `docs/openapi.json`, `miniapp/src/shared/api/schema.ts`, `MaxTransport`, `NormalizedInboundEvent` and capability flags. Do not infer a live MAX payload from diagnostic replay or expose appeals/routes before their contracts exist.

DEV-B now owns public contracts, core/services, DB/migrations, common worker and
all product integration, including A-01 convergence for B-02. DEV-A supplies
typed AI analysis and remains mandatory reviewer of DEV-B PRs; it is not the
waiting producer for the C0/B-00 product contract.
