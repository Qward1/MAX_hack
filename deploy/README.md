# Production VPS runbook

This runbook deploys the existing API/webhook, durable worker, PostgreSQL and
Caddy HTTPS edge. It does not create a MAX subscription automatically. Local
Compose remains offline; the production overlay is intentionally fail-closed and
always selects the real MAX webhook/HTTP providers.

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
git switch dev/b-experience
git pull --ff-only origin dev/b-experience

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
- `MAX_WEBHOOK_SECRET`: the generated 64-character hex value.

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

Expected long-running services are `db`, `api`, `worker` and `caddy`; `migrate`
and the disabled production `seed` job must exit with code 0. PostgreSQL has a
persistent named volume and no host port. API is reachable externally only through
Caddy; its loopback binding is available for VPS diagnostics. API/worker/db/Caddy
use restart policies, while migrations remain one-shot.

If startup fails, inspect sanitized service logs without copying environment output:

```bash
docker compose --project-name domsignal-prod \
  --env-file deploy/.env.production \
  -f compose.yaml -f compose.prod.yaml logs --tail=200 api worker caddy db
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
bot_started, bot_stopped, bot_added, bot_removed, message_created, message_callback
```

All six names are present in the current official MAX `Update` object. To rotate
the secret or correct update types for the same expected URL, use the documented
POST update operation:

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

```bash
git fetch origin --prune
git merge --ff-only origin/dev/b-experience
export BUILD_COMMIT="$(git rev-parse HEAD)"
docker compose --project-name domsignal-prod \
  --env-file deploy/.env.production \
  -f compose.yaml -f compose.prod.yaml up -d --build
curl --fail-with-body --silent --show-error "https://$(sed -n 's/^PUBLIC_DOMAIN=//p' deploy/.env.production)/ready"
```

Do not run `down -v` in production. Normal `down`/`up` preserves named volumes;
backup and restore must still be tested independently.

## 7. Explicit isolated live resident scope

SSH on the current host uses `user1@176.108.244.168` and the existing
`domsignal_codex_ed25519` key with BatchMode/strict host checking; Docker uses
`sudo -n`. Do not regenerate keys or print production environment files.

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
The scope is labelled LIVE TEST and is not a real address or residence claim.
MembershipService/AccessPolicy remains the access authority. General resident
onboarding and ChatBinding-derived automatic membership are not implemented.

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

## 8. Live A-07 operator connection

`python -m domsignal.tools.live_connection prepare --chat-id=<real-chat-id>
--operator <name> --reason <authorization-reference>` is confined to the singleton
active fixture and a group already observed in an authenticated bot_added receipt.
It creates one labelled CLI User with **no MAX identity, session or platform role**
and company_admin membership only in the test company. The real resident remains
resident. It calls existing ChatConnectionService.initiate and returns the
one-time `?start=connect_...` link; the raw token is never in DB/audit/docs.
This explicit service account supports authorized test-company backend actions;
it is not a fake MAX identity or employee web-auth bypass.

The connector must open that link in MAX before adding the bot. If the capability
smoke added it before the request existed, a fresh addition after bot_started is
required by A-07's temporal correlation. Do not backdate requests, fabricate events,
assign candidate IDs directly or infer binding from title. Original receipts remain.

After real correlation, `python -m domsignal.tools.live_connection approve
--chat-id=<same-real-chat-id> --operator <name> --reason <authorization-reference>
--confirm` checks pinned chat/connector/management and calls existing service approve.
That service rechecks management/tenant/staff authority and fresh MAX rights before
creating ACTIVE binding. No new HTTP endpoint or alternate binding transition.
Operator audit `operator:live-smoke-connection:v1` records request/principal/scope
and activation IDs, distinct from MAX webhook evidence. Repeat prepare returns no
new token and grants no additional account. An expired/lost request must be cancelled
and recreated through the same application service with an explicit operator audit.
Fixture `revoke` also revokes the CLI company membership; history remains intact.
