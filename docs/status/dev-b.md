# DEV-B — current handoff
Updated: 2026-09-17T22:15:00+03:00
Branch: dev/b-experience
Current task: B-02; next backend slice A-01 contract convergence
State: PARTIAL / BLOCKED ON DEV-B-OWNED CONTRACT CONVERGENCE

## Active/recent tasks
| ID | State | Result / blocker | Tested reference |
|---|---|---|---|
| B-00 | DONE | UX/acceptance and target API v0.1; target is not an implemented producer | `f8335c5` |
| B-02 | PARTIAL | Working C0 board/detail, visual layer, MAX wrapper and frontend checks; full target binding requires A-01 producer/consumer convergence by DEV-B | FND-01 `c939ccf` merged into DEV-B by `faca33d` with explicit user authorization; B-02 `c4492dd` |
| A-01 | NEXT | Minimal C0/B-00 convergence: structured actions, provenance/freshness, capabilities, count semantics, read model, errors, generated types and checks; future actions stay unpublished | Planning/ownership only; implementation not started by this docs patch |

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

## Next / for teammate

DEV-B implements existing A-01 as the next backend slice: one Pydantic producer
→ OpenAPI → generated TS → frontend binding → contract/negative test diff. It
does not publish unsupported future actions or implement all target endpoints.
Then DEV-B rechecks B-02 real-data fields/actions. DEV-A reviews the PR and may
proceed independently with A-03/AI against the typed analysis boundary.

DEV-B is now the default integrator and updates `IMPLEMENTATION_CONTEXT.md`
after significant accepted merges using a verified main/ref. FND-01 merge into
DEV-B remains a user-authorized development base, not approval or merge to
main. Actual MAX clients, live initData and MAX-controlled appearance remain
**NOT VERIFIED**. No later product task has started.
