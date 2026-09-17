# DEV-B — current handoff
Updated: 2026-09-17T19:14:48+03:00
Branch: dev/b-experience
Current task: B-02
State: BLOCKED

## Active/recent tasks
| ID | State | Result / blocker | PR or tested reference |
|---|---|---|---|
| B-00 | DONE | Five-screen UX contract, 48 acceptance scenarios and target API v0.1; no runtime implementation | `docs/UX.md`, `scenarios/acceptance.md`, `docs/CONTRACTS.md`; coverage audit and `git diff --check` pass |
| B-02 | BLOCKED | Accepted FND-01/C0 absent; local foundation API differs from B-00. No competing scaffold or runtime changes created | Read-only audit of local `dev/a-core@c939ccf`; fetched `origin/main` and `origin/dev/a-core` both at `a70df01` |

## Next
DEV-A publishes FND-01 for review/integration and agrees the B-00 producer contract before B-02 implementation. Using the unmerged local foundation for a partial B-02 requires an explicit exception to the accepted-work sync rule; this does not resolve API incompatibilities. No later roadmap task started.

## For teammate
Target paths are requirements, not implemented endpoints. See `Contract conflicts / decisions required` before changing C0/OpenAPI.

### B-02 dependency audit

The current DEV-B checkout has no `miniapp/`, package manifest, backend or runnable frontend checks. Local `c939ccf` is read-only evidence, not an accepted dependency or a new test run. It already includes React 19, MAX UI 0.5.0 (`MaxUI`, `Button`), Vite, TypeScript, Vitest/Testing Library, generated OpenAPI types and a fetch client without a query library. Preserve that foundation once available.

| Expected for B-02 | Actual in local C0 | Impact / required decision |
|---|---|---|
| `allowed_actions: {code, enabled, reason}[]` | Only string `view` | Cannot implement B-00 NextAction/disabled reasons against real responses; DEV-A must publish compatible descriptors and supported operations |
| Origin `official/product_derived/user_reported/demo` | Detail `rule.verification_status: verified/needs_verification/demo`; house `is_demo` | Verification is not origin; agree origin DTO without frontend relabelling |
| Seven statuses and self-reported filing semantics | Only `open/resolved/dismissed`; no filing endpoint | Additional statuses can only be tested as future inputs until producer supports them; no filing claim or synthetic mutation |
| UserContext capabilities | Separate `/capabilities` with C0 flags | Agree capability contract; do not invent enabled capabilities |
| Location, participant/affected count, route/recipient, updated time and optional filing data | Description/report count; detail reports and rule only | Report count cannot be presented as distinct affected residents; producer must define missing data semantics. Request also says `affected_count`, while B-00 names `participant_count`: agree the field in generated DTOs |
| Retryable problem metadata | `request_id/errors`, no `retryable/trace_id/field_errors` | Agree error contract before claiming B-00 retry semantics |

Available read endpoints in local C0: `/api/v1/capabilities`, `/api/v1/me` (includes houses), `/api/v1/houses/{house_id}/incidents` (limit/offset), `/api/v1/incidents/{incident_id}`. Auth routes and `POST /api/v1/reports` also exist there. None were started or called during this audit. Target houses list, appeal, join and feedback endpoints are absent; they must not be represented by production fixtures or working buttons.

## Checks
B-00 previous checks: requested P0/P1/P2 IDs and DTO/status/action/capability/endpoint inventories present; `git diff --check` passed.

B-02: branch/status and fresh remote refs checked; UX/contracts/acceptance and local foundation source audited. Frontend tests, typecheck, production build, browser/reload/keyboard/theme/torture checks and actual MAX mobile/web validation were not run: no accepted runtime exists in this checkout. B-02 acceptance 1–19 is unverified, not passed; criterion 20 (no competing architecture) is preserved. Only this handoff changes; integrator-owned implementation context and existing untracked `.playwright-cli/` files are untouched.
