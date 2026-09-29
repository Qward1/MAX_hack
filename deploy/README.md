# Production VPS runbook

This runbook deploys the API/webhook, the operational worker, the AI worker,
PostgreSQL and the Caddy HTTPS edge. It does not create a MAX subscription
automatically. Local Compose remains offline; the production overlay is
intentionally fail-closed and always selects the real MAX webhook/HTTP providers.

Overview in Russian — [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md); release and
version check — [`docs/RELEASE.md`](../docs/RELEASE.md).

## 1. External prerequisites

- Rent a Linux VPS with a public IPv4 address and install Docker Engine plus the
  current Docker Compose plugin.
- Point an `A` record for a dedicated hostname to the VPS. Add an `AAAA` record
  only when IPv6 is actually routed to the server.
- Allow inbound TCP 22, 80 and 443. UDP 443 is optional HTTP/3. Do not publish
  PostgreSQL 5432.
- Wait until the hostname resolves publicly. Caddy obtains and renews the trusted
  TLS certificate; a self-signed certificate is not accepted by MAX.

Verify outbound DNS and NTP before installing packages. The current VPS image
needed explicit DNS servers in a `systemd-resolved` drop-in and replacement of an
unresolvable Ubuntu apt mirror with the official Ubuntu archive. Keep the old
configuration as a backup and verify resolution and time synchronization afterward.

Host firewall rules do not open a cloud security group. If Caddy listens locally
and both ACME challenges time out, inspect Docker/UFW rules and capture inbound
SYN packets on the public-facing interface during an external probe. No arriving
packets indicates an upstream ingress gate; allow TCP 80/443 in the attached cloud
security group. Keep 5432 private and never bypass TLS validation to proceed.

## 2. Checkout and secrets

```bash
git clone <REPOSITORY_URL> domsignal
cd domsignal
git switch main
git pull --ff-only origin main

cp deploy/.env.example deploy/.env.production
chmod 600 deploy/.env.production
openssl rand -hex 32  # POSTGRES_PASSWORD
openssl rand -hex 48  # SESSION_SECRET
openssl rand -hex 32  # MAX_WEBHOOK_SECRET
nano deploy/.env.production
```

Fill only these values:

- `PUBLIC_DOMAIN`: hostname only, without `https://`, path or port;
- `POSTGRES_PASSWORD`: the generated 64-character hex value;
- `SESSION_SECRET`: the generated 96-character hex value;
- `MAX_BOT_TOKEN`: issued token for `t480_hakaton_max_bot`;
- `MAX_WEBHOOK_SECRET`: the generated 64-character hex value;
- `AUTH_MFA_ENCRYPTION_KEY`: generated once on the VPS, see §8.

The overlay fixes `APP_ENV=production`, `ALLOW_TEST_SESSION=false`,
`DEMO_SEED=false`, `MAX_TRANSPORT=webhook`, the issued bot username and
`https://platform-api2.max.ru`. It derives `PUBLIC_BASE_URL` and `CORS_ORIGINS`
from `PUBLIC_DOMAIN`. Do not add secrets to tracked files or command arguments.
The root `.dockerignore` excludes `.env` and nested `.env.*` files so that the
production environment file is not sent to the Docker builder.

The production Caddy service has `PUBLIC_DOMAIN` as a Docker network alias.
Containers therefore reach Caddy directly when checking the HTTPS hostname;
certificate-chain and hostname verification remain enabled. This supports cloud
networks that cannot loop back through the VPS public IP. The subscription CLI's
container preflight does not prove external reachability: also check public HTTPS
and webhook authentication from a machine outside the VPS before registration.

MAX currently uses the Russian Trusted Root CA. The runtime image installs the
public root from `deploy/ca/russian_trusted_root_ca.crt`; its SHA-256 fingerprint
is `D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31`.
The certificate source is the Ministry CDP URL embedded in the live MAX chain:
`http://nuc-cdp.digital.gov.ru/cdp/rootca_ssl_rsa2022.crt`. Never disable TLS
verification; re-verify the subject, validity and fingerprint before replacing it.

## 3. Validate and start

```bash
export BUILD_COMMIT="$(git rev-parse HEAD)"

docker compose --project-name domsignal-prod \
  --env-file deploy/.env.production \
  -f compose.yaml -f compose.prod.yaml config --quiet

docker compose --project-name domsignal-prod \
  --env-file deploy/.env.production \
  -f compose.yaml -f compose.prod.yaml up -d --build

docker compose --project-name domsignal-prod \
  --env-file deploy/.env.production \
  -f compose.yaml -f compose.prod.yaml ps
```

Expected long-running services are `db`, `api`, `worker`, `ai-worker` and
`caddy`; `migrate` and the disabled production `seed` job must exit with code 0.
PostgreSQL has a persistent named volume and no host port. API is reachable
externally only through Caddy; its loopback binding is available for VPS
diagnostics. Long-running services use restart policies, while migrations remain
one-shot.

If startup fails, inspect sanitized service logs without copying environment output:

```bash
docker compose --project-name domsignal-prod \
  --env-file deploy/.env.production \
  -f compose.yaml -f compose.prod.yaml logs --tail=200 api worker ai-worker caddy db
```

Database backup and separate-restore verification are documented in
[`database.md`](database.md).

## 4. Public HTTPS and webhook authentication checks

Run these after DNS and Caddy certificate issuance. They are safe before a MAX
subscription exists:

```bash
set -a
. deploy/.env.production
set +a
export PUBLIC_BASE_URL="https://${PUBLIC_DOMAIN}"

curl --fail-with-body --silent --show-error "${PUBLIC_BASE_URL}/ready"

test "$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  --request POST --header 'Content-Type: application/json' --data '{}' \
  "${PUBLIC_BASE_URL}/max/webhook")" = "401"

test "$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  --request POST --header 'Content-Type: application/json' \
  --header "X-Max-Bot-Api-Secret: ${MAX_WEBHOOK_SECRET}" --data '{}' \
  "${PUBLIC_BASE_URL}/max/webhook")" = "422"
```

`422` for `{}` with the valid secret is expected: authentication passed and the
payload was rejected before any business event was persisted.

The equivalent guarded check from the production image is:

```bash
export BUILD_COMMIT="$(git rev-parse HEAD)"
docker compose --project-name domsignal-prod \
  --env-file deploy/.env.production \
  -f compose.yaml -f compose.prod.yaml run --rm --no-deps api \
  python -m domsignal.tools.max_subscription preflight
```

## 5. Inspect, register, update or delete the MAX subscription

The operator CLI always performs `GET /subscriptions` first. It refuses to mutate
anything if another URL or more than one subscription exists. Registration also
rechecks public `/ready`, the missing-secret `401`, and the valid-secret `422`.

```bash
export BUILD_COMMIT="$(git rev-parse HEAD)"

# Read-only: expected initial result is subscriptions: []
docker compose --project-name domsignal-prod \
  --env-file deploy/.env.production \
  -f compose.yaml -f compose.prod.yaml run --rm --no-deps api \
  python -m domsignal.tools.max_subscription list

# POST /subscriptions, then GET and exact URL/update_types verification
docker compose --project-name domsignal-prod \
  --env-file deploy/.env.production \
  -f compose.yaml -f compose.prod.yaml run --rm --no-deps api \
  python -m domsignal.tools.max_subscription register

# Read-only verification
docker compose --project-name domsignal-prod \
  --env-file deploy/.env.production \
  -f compose.yaml -f compose.prod.yaml run --rm --no-deps api \
  python -m domsignal.tools.max_subscription list
```

The exact subscription set is:

```text
bot_started, bot_stopped, bot_added, bot_removed, message_created, message_callback,
user_added, user_removed
```

All eight names are present in the current official MAX `Update` object.
`user_added`/`user_removed` grant and end resident membership by chat
([RESIDENT-BY-CHAT-2026-09-25](../docs/decisions.md#resident-by-chat-2026-09-25));
the URL does not change. A deployment that still has the six-type subscription is
moved with `replace` below (record `list` before and after, never the secret). To
rotate the secret or correct update types for the same expected URL, use the
documented POST update operation:

```bash
docker compose --project-name domsignal-prod \
  --env-file deploy/.env.production \
  -f compose.yaml -f compose.prod.yaml run --rm --no-deps api \
  python -m domsignal.tools.max_subscription replace
```

To delete only the one exact expected URL and verify it disappeared:

```bash
docker compose --project-name domsignal-prod \
  --env-file deploy/.env.production \
  -f compose.yaml -f compose.prod.yaml run --rm --no-deps api \
  python -m domsignal.tools.max_subscription delete
```

The underlying official calls are `GET /subscriptions`, `POST /subscriptions`
with `{url, update_types, secret}`, and `DELETE /subscriptions?url=...`, all with
`Authorization: <MAX_BOT_TOKEN>`. The CLI uses those exact methods while keeping
credentials out of shell arguments and checking `success=true`, not only HTTP 200.

## 6. Safe redeploy

`up` runs the one-shot `migrate` service, so the database backup comes **first**:
no backup — no redeploy with migrations. Record the deployed SHA and keep the
previous image under its own tag for rollback.

```bash
PREVIOUS="$(git rev-parse HEAD)"
sudo docker tag domsignal-backend:local "domsignal-backend:pre-${PREVIOUS:0:7}"
# Private directory outside the checkout. The script checks the new dump with
# `pg_restore --list` itself; --keep 1000 leaves earlier manual copies in place
# (the daily timer rotates only its own daily/ directory, see §7).
sudo sh -c 'umask 077; python3 scripts/backup_postgres.py \
  --container domsignal-prod-db-1 --directory /var/backups/domsignal --keep 1000'

git fetch origin --prune
git merge --ff-only origin/main
export BUILD_COMMIT="$(git rev-parse HEAD)"
docker compose --project-name domsignal-prod \
  --env-file deploy/.env.production \
  -f compose.yaml -f compose.prod.yaml up -d --build
curl --fail-with-body --silent --show-error "https://$(sed -n 's/^PUBLIC_DOMAIN=//p' deploy/.env.production)/ready"
```

Without GitHub access on the VPS, move the commits as a verified bundle over SSH
instead of `git fetch origin`:

```bash
# local
git bundle create release.bundle <branch> ^<deployed-sha>
scp -i <ssh-key> release.bundle <user>@<vps-host>:
# VPS
git bundle verify ~/release.bundle
git fetch ~/release.bundle <branch>:refs/bundles/<branch>
git merge --ff-only <exact-sha>
```

`BUILD_COMMIT` must equal that SHA; `/version` then shows it. Then check `/ready`,
`/version` and the webhook without the secret → 401 (§4) and run
`uv run python scripts/release_check.py --fetch` from a checkout
([`docs/RELEASE.md`](../docs/RELEASE.md)). Rollback: check out the previous SHA
detached, retag `domsignal-backend:pre-<sha>` as `domsignal-backend:local` and
`up -d --no-build`. Additive migrations stay; if a downgrade refuses, restore the
backup into a **separate** database first — never over the live one.

Do not run `down -v` in production. Normal `down`/`up` preserves named volumes;
backup and restore must still be tested independently. Docker on the VPS is used
through `sudo -n`; never print production environment files.

## 7. Daily database backup and external monitoring

A systemd timer makes a verified copy every day at 03:00 Moscow time.
`scripts/backup_postgres.py` refuses to start below 2 GB free, dumps, checks
the new file with `pg_restore --list` (an unreadable dump is removed and the
unit fails), then keeps the 14 newest `domsignal-*.dump` in
`/var/backups/domsignal/daily`. Manual pre-deploy copies in
`/var/backups/domsignal` are outside that directory and never rotated by it.

```bash
sudo install -m 644 deploy/systemd/domsignal-backup.service \
  deploy/systemd/domsignal-backup.timer /etc/systemd/system/
sudo install -d -m 700 /var/backups/domsignal/daily
sudo systemctl daemon-reload
sudo systemctl enable --now domsignal-backup.timer
sudo systemctl start domsignal-backup.service      # the first copy right away
systemctl list-timers domsignal-backup.timer --no-pager
sudo journalctl -u domsignal-backup.service -n 5 --no-pager   # path, size, toc_entries, free_mb
```

External monitoring is `.github/workflows/uptime.yml`. The `probe` job checks
`/ready` 200, `/version` with a commit and the webhook without the secret → 401:
hourly until 29.09, every 30 minutes on 30.09, every 15 minutes during the jury
period 1–14.10 and hourly again 15–29.10. A failed run is reported by GitHub to
the author of the schedule and sends:
- an e-mail to the repository variable `ALERT_EMAIL` (comma-separated list)
  from the mailbox in the variable `ALERT_SMTP_USER`; the mailbox app
  password is the repository secret named `ALERT_SMTP_PASSWORD`, the server —
  the variable `ALERT_SMTP_HOST` (default `smtp.mail.ru`, SSL port 465);
- a MAX message with secrets `ALERT_MAX_BOT_TOKEN` and `ALERT_MAX_USER_ID`
  (that user must have started a dialog with that bot).

All of them are changed in GitHub → Settings → Secrets and variables →
Actions, without code changes; secrets are set there and never committed. A
manual run with `test_alert` fails on purpose to test the alerts. The public
address can be overridden by the repository variable `DOMSIGNAL_URL`.

The `showcase` job runs once a day until 29.10: `scripts/showcase_check.py` with
the secret `SHOWCASE_CHECK_TOKEN` (the same value as in `deploy/.env.production`)
checks the jury showcase and opens an issue if an invariant is broken. Recovery —
[`docs/RELEASE.md`](../docs/RELEASE.md), «Витрина жюри».

## 8. Employee authentication operations

Generate `AUTH_MFA_ENCRYPTION_KEY` once **on the VPS**, using
`cryptography.fernet.Fernet.generate_key()`, and append it directly to the protected
`deploy/.env.production` (mode 600). Never print/commit the key or rotate it on
deployment. Production settings and Compose fail closed without a valid key.
Back up this env/key separately in protected storage alongside the DB backup;
losing it makes enrolled MFA secrets unreadable. `SESSION_SECRET` also protects
session/recovery digests; unplanned rotation invalidates those proofs.

Before a migration that touches credentials, record the deployed SHA and run
`backup_postgres.py` with a private backup directory (§6). Restore the dump to a
separate verification DB and compare preserved domain rows; never reset the live
DB. Upgrade is additive. Downgrade refuses credential/audit loss; use a separate
earlier backup with the matching application if a rollback is necessary. Keep
the MAX subscription/token and webhook secret unchanged. Caddy retains TLS/HSTS;
admin-only CSP is set by the backend. The production API remains
loopback/private-network-only: its proxy-header trust depends on Caddy being the
sole untrusted-client ingress.

Inside the production API container, using an **existing** employee UUID:

```sh
python -m domsignal.tools.employee_auth create --user-id <UUID> --login-name <login>
python -m domsignal.tools.employee_auth status --user-id <UUID>
python -m domsignal.tools.employee_auth reset-password --user-id <UUID>
python -m domsignal.tools.employee_auth reset-mfa --user-id <UUID>
python -m domsignal.tools.employee_auth revoke --user-id <UUID>
```

`create` and `reset-password` return a strong temporary password only in operator
stdout after commit. Deliver privately, never via command arguments/docs/logs.
It expires in 24 hours and is consumed by the first password stage; abandoning
that constrained flow may require operator reset. Reset-password explicitly
reactivates a revoked credential only if active employee membership still exists.
Reset-MFA clears encrypted secret/recovery proofs; subsequent password login
requires fresh enrollment. All three reset/revoke commands invalidate employee
web sessions and preauth challenges, preserving resident MAX sessions.

Defaults/configuration: `AUTH_PASSWORD_MAX_LENGTH=1024`;
`AUTH_CHALLENGE_SECONDS=600`; `AUTH_TEMPORARY_PASSWORD_SECONDS=86400`;
`AUTH_SESSION_IDLE_SECONDS=1800`; `AUTH_SESSION_ABSOLUTE_SECONDS=28800`;
`AUTH_RATE_THRESHOLD=10`; `AUTH_RATE_WINDOW_SECONDS=300`;
`AUTH_RATE_BACKOFF_SECONDS=300`. IP threshold is five times the identifier
threshold. MFA is required in every employee flow, including production. Local
deterministic OTP helpers live only under tests, require `APP_ENV=test` and
test-auth opt-in, and must never be used for ownership of a live enrollment.

## 9. Model, passive reading and AI pool

Only `ai-worker` receives the model key: `api`, `worker`, `migrate` and `seed`
stay on `LLM_PROVIDER=rules` (they analyse with rules only) and never get
`LLM_API_KEY`. The API advertises `ai_analysis` from `AI_POOL_LLM_PROVIDER`,
which Compose derives from the same `LLM_PROVIDER` value. Variables in
`deploy/.env.production` (defaults are safe — rules, no key, reading off):

| Variable | Service | Default | Demo/check value |
|---|---|---|---|
| `LLM_PROVIDER` | ai-worker (+ capability in api) | `rules` | `openai_compatible` |
| `LLM_BASE_URL` | ai-worker | `https://foundation-models.api.cloud.ru/v1` | same — Cloud.ru Evolution Foundation Models ([LLM-PROVIDER-2026-09-27](../docs/decisions.md#llm-provider-2026-09-27)) |
| `LLM_API_KEY` | ai-worker only | empty | Cloud.ru key, appended on the VPS only |
| `LLM_MODEL` | ai-worker | empty | `Qwen/Qwen3-30B-A3B` (open weights, Apache 2.0; an "external" model in the Cloud.ru catalogue: data is processed outside Cloud.ru infrastructure) |
| `LLM_TIMEOUT_SECONDS` | ai-worker | empty — the model profile applies (`Qwen3-30B-A3B`: 20 s) | empty; a number overrides the profile |
| `LLM_DAILY_CALL_BUDGET` | ai-worker | `300` | `500` in production (≈ 0.1 ₽ per window → ≈ 50 ₽ a day; [budget decision](../docs/decisions.md#llm-budget-f1-2026-09-29)) |
| `LLM_CHAT_DAILY_SHARE` | ai-worker | `0.2` | `0.2` |
| `LLM_TOKENS_PER_MINUTE` | ai-worker | `80000` | `80000` (80 % of the Cloud.ru key limit, shared by all processes) |
| `AI_WORKER_LEASE_SECONDS` | ai-worker | `80` | `80`; must be ≥ model timeout + 20 s or the AI worker refuses to start |
| `PASSIVE_CAPTURE_ENABLED` | api, worker, ai-worker | `false` | `true` |
| `PASSIVE_WINDOW_SILENCE_SECONDS` | api, worker, ai-worker | `120` | `30` |
| `PASSIVE_WINDOW_MAX_LINES` | api, worker, ai-worker | `6` | `6` |
| `PASSIVE_LLM_ENABLED` | api, worker, ai-worker | `true` | `true` |

Model profiles (default and the fallback `deepseek-ai/DeepSeek-V4-Flash`) are in
`src/domsignal/ai/resources/models.v1.yaml`. Append the key without echoing it
(stdin, not an argument), e.g. pipe the single `LLM_API_KEY=` line into
`cat >> deploy/.env.production` over SSH; keep mode 600. The Cloud.ru key is
limited to 100 000 tokens a minute (≈ 15 windows a minute); above that the
provider answers HTTP 429 and the window is analysed by rules. American and
proprietary models are not allowed by the hackathon rules.
`openai_compatible` without a key or model stops only `ai-worker` (settings
validation); rules and the report/window watchdogs keep the product working.
The operational lease stays 30 s; `report.fallback` (30 s) and
`chat.window.fallback` (90 s) are unchanged.
The 30 s `report.fallback` rules watchdog answers `/report` within 30 s only
while the AI pool has not yet claimed the intake (pool stopped, backlog, no
key); once `ai-worker` has claimed it, the watchdog exits quietly, so a slow
model delays the answer up to the model timeout, after which the same job
settles with the rules result (`fallback_timeout`).
Changing only model variables needs `up -d --no-deps ai-worker`; note that
`docker compose start ai-worker` also starts its one-shot dependencies
(`migrate`, `seed`), which are no-ops at head.

## 10. House routing profile, chat reading and staff

Run inside the production API container (`docker compose ... run --rm --no-deps
api python -m ...`). In production the routing-profile CLI accepts only the
active audited live-test house (§12) and requires an operator and reason; it
writes an `operator.house_routing_profile` receipt with the previous and new
profile:

```bash
python -m domsignal.tools.house_routing_profile --house-id <live-house> \
  --region RU-TA --municipality kazan --territory mixed \
  --operator <name> --reason <authorization-reference>
```

Passive reading needs both the global `PASSIVE_CAPTURE_ENABLED=true` and the
per-binding switch by a user with `chat.connect` (in the cabinet: «MAX-чаты» →
«Включить чтение чата»; for the live-test company — the scoped CLI company admin
from §13). Enabling queues one reading notice in the chat per binding version:

```bash
python -m domsignal.tools.passive_capture --binding <binding-id> --actor <company-admin-id> --enable
python -m domsignal.tools.signals_preview --house <live-house>   # read-only check
```

`live_staff grant` gives one MAX user (after a real mini app login, not the
fixture resident) the `operator` role in the live-test company and an `operator`
assignment to its house only — `ticket.read`/`ticket.work`, no
`chat.connect`/`ticket.manage` — so that a danger alert there has a personal MAX
recipient. One grant per database, audited as `operator:live-smoke-staff:v1`;
`revoke` ends both rows and keeps history:

```bash
python -m domsignal.tools.live_staff grant --user-id <validated-max-user> \
  --operator <name> --reason <authorization-reference>
```

### Passive model switch

`PASSIVE_LLM_ENABLED` (default `true`) keeps the model in chat-window analysis.
Set it to `false` in `deploy/.env.production` and recreate only `ai-worker`
(`up -d --no-deps ai-worker`, and `api` so that `/api/v1/capabilities`
reports `passive_ai_analysis: false`) to analyse chat windows with rules only;
the explicit `/report` path keeps the model. Production keeps the model on. The
cabinet page «MAX-чаты» shows the actual mode next to a chat with reading on.

The bot writes the safety memo in the chat only for high-precision rule hits
(`chat_memo_eligible`: «пахнет газом», «застряли в лифте», «дым из подвала»…);
drills, thanks after the fix, the past, hypotheses and phrases without a place
(«и дымом тоже тянет») still alert the operator but give no memo
(`chat_memo_not_eligible` in the signal journal).

### Role-play session export

After a role-play session in a test chat (with the participants' consent),
export the session lines from the buffer (≤ 72 h) inside the API container,
read-only:

```bash
python -m domsignal.tools.d2_export --binding <test-chat-binding> --session S1 \
  --since 2026-09-24T19:00:00+03:00 --until 2026-09-24T19:40:00+03:00 \
  --operator <name> --reason <authorization-reference> > session-S1.jsonl
```

The file holds no MAX ids or people ids (hashed message ids, buffer aliases);
keep it outside git.

## 11. Logs without client IP addresses and log rotation

The API runs uvicorn with `--proxy-headers --no-access-log`: uvicorn's access
log would write the full client address from `X-Forwarded-For`. The application
logs one `http_request` line per request instead — `request_id` (equal to the
`X-Request-ID` response header), method, path without the query string and
without invitation/launch secrets, status, duration and the client network
truncated to /24 (IPv4) or /48 (IPv6). Every log line of `api`, `worker` and
`ai-worker` is scrubbed of full addresses, including tracebacks. Caddy has no
access log; its proxy error lines mask `remote_ip`/`client_ip` the same way
and drop forwarding headers. The login rate limiter stores an HMAC slot
number, never the address.

Every production service uses the `json-file` driver with `max-size: 10m`
and `max-file: 5`. The option applies when a container is (re)created (named
volumes are kept). Check after a deploy without printing log contents:

```bash
for c in api worker ai-worker caddy db; do
  sudo docker inspect -f '{{.Name}} {{.HostConfig.LogConfig.Type}} {{json .HostConfig.LogConfig.Config}}' "domsignal-prod-$c-1"
done
# Full IPv4 addresses per container (masked networks end in .0/24 and are not counted):
sudo docker logs domsignal-prod-api-1 2>&1 | grep -cE '([0-9]{1,3}\.){3}[0-9]{1,3}(:[0-9]+)?([^/0-9]|$)'
```

`DISPLAY_TIMEZONE` (default `Europe/Moscow`) is the fallback time zone for
houses without a region profile; staff messages, quiet hours, the 09:00 digest
and company dashboards use the zone of the house region pack (`timezone` in
`regions/<code>/responsibility.yaml`). An unknown zone stops the process at
settings validation.

## 12. Explicit isolated live-test resident scope

Resident bootstrap is `capabilities` → `POST /api/v1/auth/max` with raw
`init_data` → `GET /api/v1/me`. The last response contains `houses`; there is
no separate `/me/houses` endpoint. MAX Bridge is loaded from the official CDN.
The server validates HMAC-SHA256 with `WebAppData` and the bot token, constant-time
signature comparison, duplicate/unknown fields, auth_date (300 seconds, up to
30 seconds future clock tolerance), and typed user data. Only then is a canonical
User found/created and a random 256-bit session issued (900 seconds; only its
HMAC digest is stored). `max_identity_verified_at` is set only on this validated
path. No raw initData, signature, bearer or bot token belongs in logs/evidence.
`initDataUnsafe`, chat, start_param and browser house selectors grant no access.
Official reference: [MAX validation](https://dev.max.ru/docs/webapps/validation).

For an explicitly authorized smoke only, the production operator CLI below
creates a singleton ManagementCompany, House, active HouseManagement (ticket
intake enabled), and ResidentMembership for an **existing server-validated**
non-demo MAX User. It never creates identity/session/staff/Superadmin grants.
The scope is labelled `LIVE TEST` and is not a real address or residence claim.
MembershipService/AccessPolicy remains the access authority.

Run inside the production API container using the existing Compose invocation:

```bash
python -m domsignal.tools.live_fixture create \
  --user-id <validated-canonical-user-uuid> \
  --operator <operator-name> --reason <explicit-authorization-reference>
```

The `operator:live-smoke-house:v1` receipt (`operator.live_fixture`, **not** a
webhook) retains exact IDs, operator, reason and action timestamps. Transactions
and a singleton advisory lock make repeated create idempotent for the same user;
another owner or silent recreation after retirement is refused. Only one fixture
is permitted per DB. No HTTP seed/reset endpoint, demo seed or test auth is used.

Use the same arguments with `revoke` to revoke resident access, end management
and archive the test company without erasing history. `delete-empty` removes only
the four recorded scope rows after checking all mapped FK dependencies (including
cascades). It refuses product/connection history or additional grants. The User
and operator audit are retained. A fixture containing business history must be
revoked and handled under the existing retention process, not force-deleted.

For live confirmation, require a fresh actual MAX launch, correlate auth/max and
me HTTP success with the verified user/session timestamps, inspect the authorized
house list and board request, and distinguish an operator service/API check from
a MAX-client interaction. Never replay or manufacture initData to obtain evidence.

## 13. Live-test chat connection by an operator

`python -m domsignal.tools.live_connection prepare --chat-id=<real-chat-id>
--operator <name> --reason <authorization-reference>` is confined to the singleton
active fixture and a group already observed in an authenticated bot_added receipt.
It creates one labelled CLI User with **no MAX identity, session or platform role**
and company_admin membership only in the test company. The real resident remains
resident. It calls the existing ChatConnectionService.initiate and returns the
one-time `?start=connect_...` link; the raw token is never in DB/audit/docs.
This explicit service account supports authorized test-company backend actions;
it is not a fake MAX identity or employee web-auth bypass.

The connector must open that link in MAX before adding the bot. If the bot was
added before the request existed, a fresh addition after bot_started is required
by the connection's temporal correlation. Do not backdate requests, fabricate
events, assign candidate IDs directly or infer binding from title. Original
receipts remain.

After real correlation, `python -m domsignal.tools.live_connection approve
--chat-id=<same-real-chat-id> --operator <name> --reason <authorization-reference>
--confirm` checks pinned chat/connector/management and calls the existing service
approve. That service rechecks management/tenant/staff authority and fresh MAX
rights before creating an ACTIVE binding. No new HTTP endpoint or alternate
binding transition. Operator audit `operator:live-smoke-connection:v1` records
request/principal/scope and activation IDs, distinct from MAX webhook evidence.
Repeat prepare returns no new token and grants no additional account. An
expired/lost request must be cancelled and recreated through the same application
service with an explicit operator audit. Fixture `revoke` also revokes the CLI
company membership; history remains intact.
