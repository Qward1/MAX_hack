# DEV-B — current handoff
Updated: 2026-09-17 (ARCH-PLATFORM-v1 documentation adoption)
Branch: dev/b-experience
Current task: ARCH-PLATFORM-v1 documentation adoption
State: DOCUMENTATION COMPLETE; B-02 PARTIAL; next A-01 is not started

## Active/recent tasks
| ID | State | Result / blocker | Tested reference |
|---|---|---|---|
| B-00 | DONE | UX/acceptance and target API v0.1; target is not an implemented producer | `f8335c5` |
| B-02 | PARTIAL | Working C0 board/detail, visual layer, MAX wrapper and frontend checks; full target binding requires A-01 producer/consumer convergence by DEV-B | FND-01 `c939ccf` merged into DEV-B by `faca33d` with explicit user authorization; B-02 `c4492dd` |
| A-01 | NEXT / NOT STARTED | Minimal tenant/house/access context decision plus C0/B-00 convergence: structured actions, provenance/freshness, capabilities, count semantics, read model, errors, generated types and checks; future actions stay unpublished | Planning/ownership only; implementation not started by this docs patch |

## ARCH-PLATFORM-v1 — documentation result

- Canonical agreed TARGET: [PRODUCT_ARCHITECTURE](../PRODUCT_ARCHITECTURE.md).
  Instructions, technical map, contracts, UX, acceptance and the existing roadmap
  now point to the same product model. Tenant/access, verified connections,
  separate web office and Ticket are not implemented by this patch.
- A-01/C1, B-02, A-07/B-03/B-07, A-10/B-09 and incidents/routing/jobs/recovery
  cards are clarified. New A-15, A-16 and B-14 cover missing access foundation,
  Ticket backend and Ticket UI; each has one Owner DEV-B, dependencies, bounds
  and acceptance. MT-01…MT-20 are future checks, all NOT RUN.
- Baseline read after fetch: HEAD, local main, origin/main and origin/dev/b-experience
  are `3d4a095`; merge `e3ab6b7` already includes FND-01 and B-02. Existing
  implementation/evidence below is preserved; this docs patch is not MERGED TO MAIN.
  `origin/dev/a-core@a70df01` handoff is older; the colleague's status is untouched.
- No runtime, migration, OpenAPI/generated types, tests or dependency changes;
  no next implementation task, Git cleanup, branch rename or merge to main.
- MAX source-check date is inherited from the supplied architecture, not a new
  verification by this agent. Live MAX and external access remain NOT VERIFIED.
  The cited hackathon PDF is absent from the available checkout/workspace.

## Result

Preserved React/MAX UI 0.5.0/Vite/generated types/fetch foundation. No second
scaffold, backend DTO/DB changes or production fixtures. Board/detail read real
API, URL/reload restores context, requests cancel and late responses cannot
replace a newer screen. Errors/access denial clear private data as appropriate;
retry/stale/refetch and capability-disabled states are covered. Existing manual
report survives; ambiguous retries now reuse Idempotency-Key.

MAX UI owns theme, typography, controls and surfaces. Added semantic statuses,
source disclosure, cards, state/next-action panels, facts, message timeline,
demo/header. Bridge globals are isolated, BackButton unsubscribes, links retain
browser fallback. Diagnostics is dev-only. See `miniapp/README.md` for structure
and repeatable checks.

## Expected / actual / impact / decision required

| B-00 expected | Actual producer C0 | Impact and required decision |
|---|---|---|
| `{code, enabled, reason}[]` | String `view` only | NextAction semantic support is tested, but no appeal/join/feedback CTA works against this producer. DEV-B must publish only supported descriptors in A-01; frontend must not infer permissions from status |
| Four provenance origin types | Detail `rule.verification_status`, house `is_demo` | Only explicit demo has equivalent semantics; other rules remain neutral. Publish origin separately from verification freshness |
| Seven statuses / self-reported filing | `open/resolved/dismissed`, no filing endpoint | Four future status labels are frontend-tested inputs only; no lifecycle or filing functionality claimed |
| UserContext UX capabilities | Separate `/capabilities`, C0 flags | UI respects actual board/detail/report flags; DEV-B aligns the source and five B-00 flags in A-01 |
| Location, residents affected, route/recipient, update time, appeal summary | Description, report count, reports and demo rule only | UI shows messages, not unique residents; DEV-B publishes honest nullable read-model fields and separates message/report counts from unique `participant_count` |
| `retryable/trace_id/field_errors` | `request_id/errors` | Explicit retryable is respected if received; otherwise documented C0 transport retry applies. DEV-B owns the producer+consumer error migration; no unsafe body/auth details are displayed |

These are pre-existing target/producer differences, not silently changed UX
rules. Missing planned functionality is not implemented by mocks or disabled
product buttons. Full B-02 is **not DONE** despite passing local checks.

## Checks recorded for B-02

These results are preserved from `dev/b-experience@c4492dd`. The ownership
documentation change does not turn them into a new run or raise LIVE status.

- Node 24: typecheck, 67 Vitest tests (including foundation scenarios), production build PASS.
- Chromium/Chrome: 8 Playwright tests PASS. Real HTTP → PostgreSQL report/board/detail/reload, network retry and actual outsider 403; fixture-only torture/error branches. MAX CDN blocked in tests, no unstable external service dependency.
- 320/430/1280px × light/dark: no horizontal overflow; 100 incidents, long unbroken address/description/source name, 0/1/9999 message counts, null source/deadline, unknown enums. Keyboard Enter/Space/Tab/Shift+Tab/back and browser axe including contrast PASS.
- Foundation backend: ruff, strict mypy, 13 unit/contract tests PASS; generated OpenAPI/TS/region checks PASS; 5 PostgreSQL integration tests PASS. Separate local B-02 DB, MAX transport off; no shared sessions reset.
- `git diff --check` PASS. No separate frontend lint exists in foundation. Production contains neither diagnostics nor fixture data.
- Actual MAX web/iOS/Android clients, live initData and MAX-controlled appearance: NOT VERIFIED (no accessible live environment). Viewport/theme emulation and wrapper tests are not live MAX evidence. Clean internal links exclude launch/auth parameters; live reload must confirm that the host supplies fresh initData after navigation, since C0 bearer sessions stay in memory.

## Checks for the ownership documentation patch

- Local equivalent of `repository-sanity`: PASS (required files, AGENTS pointer, conflict markers).
- `git diff --check`: PASS; changed-path audit contains only documentation and `.github/CODEOWNERS`.
- All 28 A-/B- roadmap cards contain an explicit Owner or owner-specific split; changed local Markdown links and table shapes: PASS.
- Runtime, API, schema, dependency and E2E checks were not rerun because this patch changes no product code or generated contract.

## Checks for ARCH-PLATFORM-v1 documentation adoption

- Repository-sanity equivalent: PASS (19 workflow-required files, AGENTS pointer,
  no conflict markers). Local Markdown links/table shapes: PASS (25 links).
- Task audit: PASS, all 31 prior roadmap IDs preserved, 3 new cards with explicit
  DEV-B ownership; FND-01 and B-00 card bodies unchanged. Reviewed task/stage
  dependency graph has no cycles; future tenant/connection gates are distinct
  from existing sender/early-deploy stages.
- C01–C49 IDs retained; only C39–C41 move their future admin surface to the web
  office. MT-01…MT-20 all NOT RUN. Historical B-02/ownership check blocks retained;
  historical product plan changed only by a superseding-decision pointer.
- One canonical architecture; supplied sections 1–16 retained verbatim. Reading
  guidance is scoped to relevant work; source notes disclose inherited MAX
  document-check date and unavailable PDF, without new VERIFIED claims.
- `git diff --check`: PASS. Changed-path audit: 13 Markdown files only;
  runtime, OpenAPI/generated types, locks, tests and colleague status unchanged.
  Runtime/DB/browser suites were not rerun for this documentation-only change;
  earlier PASS records above remain attached to their original tested refs.
- Delivery follows END to `dev/b-experience` only; no merge to main, cleanup or
  next task. Commit/ref is reported at handoff, without another hash-only commit.

## Next / for teammate

**One next DEV-B task for separate discussion: A-01.** Audit the current C0/B-00
producer/consumer, complete the minimal convergence and define honest compatible
tenant/house/access context. Use one Pydantic → OpenAPI → generated TS → consumer
contract/negative-test slice; do not implement tenant persistence, web office,
onboarding or Ticket in A-01. It has not started in this documentation session.

After a separately accepted A-01, roadmap places A-15 access foundation before
the new tenant binding in B-02; recheck existing B-02 fields/actions and keep its
live MAX gate separate. DEV-A reviews the product boundary and may continue
A-03/AI independently. B-01 feasibility can proceed in parallel when authorized.

Historical foundation integration into DEV-B required user authorization; the
later `e3ab6b7` merge and checked `origin/main@3d4a095` now establish MERGED TO MAIN
for that existing code. This does not raise B-02 to DONE or imply LIVE VERIFIED.
No Git cleanup or previous Git-repair completion is claimed by this patch.
