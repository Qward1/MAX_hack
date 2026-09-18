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
