# DEV-B — current handoff
Updated: 2026-09-17T19:49:00+03:00
Branch: dev/b-experience
Current task: B-02
State: PARTIAL / BLOCKED ON B-00 PRODUCER

## Active/recent tasks
| ID | State | Result / blocker | Tested reference |
|---|---|---|---|
| B-00 | DONE | UX/acceptance and target API v0.1; target is not an implemented producer | `f8335c5` |
| B-02 | PARTIAL | Working C0 board/detail, visual layer, MAX wrapper and frontend checks; full target fields/actions/provenance require DEV-A contract reconciliation | FND-01 `c939ccf` merged into DEV-B by `faca33d` with explicit user authorization; current B-02 change set |

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
| `{code, enabled, reason}[]` | String `view` only | NextAction semantic support is tested, but no appeal/join/feedback CTA works against this producer. DEV-A must publish supported descriptors/endpoints; frontend must not infer permissions from status |
| Four provenance origin types | Detail `rule.verification_status`, house `is_demo` | Only explicit demo has equivalent semantics; other rules remain neutral. Publish origin separately from verification freshness |
| Seven statuses / self-reported filing | `open/resolved/dismissed`, no filing endpoint | Four future status labels are frontend-tested inputs only; no lifecycle or filing functionality claimed |
| UserContext UX capabilities | Separate `/capabilities`, C0 flags | UI respects actual board/detail/report flags; agree producer migration to five B-00 flags |
| Location, residents affected, route/recipient, update time, appeal summary | Description, report count, reports and demo rule only | UI shows messages, not unique residents; publish missing DTO fields. B-02 prompt says `affected_count`, B-00 says `participant_count`: agree canonical semantics/name |
| `retryable/trace_id/field_errors` | `request_id/errors` | Explicit retryable is respected if received; otherwise documented C0 transport retry applies. Agree error migration; no unsafe body/auth details are displayed |

These are pre-existing target/producer differences, not silently changed UX
rules. Missing planned functionality is not implemented by mocks or disabled
product buttons. Full B-02 is **not DONE** despite passing local checks.

## Checks

- Node 24: typecheck, 67 Vitest tests (including foundation scenarios), production build PASS.
- Chromium/Chrome: 8 Playwright tests PASS. Real HTTP → PostgreSQL report/board/detail/reload, network retry and actual outsider 403; fixture-only torture/error branches. MAX CDN blocked in tests, no unstable external service dependency.
- 320/430/1280px × light/dark: no horizontal overflow; 100 incidents, long unbroken address/description/source name, 0/1/9999 message counts, null source/deadline, unknown enums. Keyboard Enter/Space/Tab/Shift+Tab/back and browser axe including contrast PASS.
- Foundation backend: ruff, strict mypy, 13 unit/contract tests PASS; generated OpenAPI/TS/region checks PASS; 5 PostgreSQL integration tests PASS. Separate local B-02 DB, MAX transport off; no shared sessions reset.
- `git diff --check` PASS. No separate frontend lint exists in foundation. Production contains neither diagnostics nor fixture data.
- Actual MAX web/iOS/Android clients, live initData and MAX-controlled appearance: NOT VERIFIED (no accessible live environment). Viewport/theme emulation and wrapper tests are not live MAX evidence. Clean internal links exclude launch/auth parameters; live reload must confirm that the host supplies fresh initData after navigation, since C0 bearer sessions stay in memory.

## Next / for teammate

DEV-A agrees the producer differences above and publishes C0/B-00 convergence;
DEV-B then binds the already-tested presentation to the generated contract and
rechecks missing real-data fields/actions. No later roadmap task started.
Integrator-owned `IMPLEMENTATION_CONTEXT.md` is unchanged. FND-01 merge into
DEV-B is a user-authorized development base, not an approval or merge to main.
