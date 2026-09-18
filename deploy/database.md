# PostgreSQL: local, server and recovery

PostgreSQL 16 + asyncpg is the only supported DomSignal runtime database for
API, worker, local development, integration tests and server deployment.
SQLite is not a runtime option or fallback. Settings/engine reject other URLs.

## Local development and integration

`docker compose up --build` supplies PostgreSQL on the private Compose network.
For host-side Python tests use a separate disposable PostgreSQL container:

```sh
docker run --name domsignal-a15-db \
  -e POSTGRES_USER=domsignal -e POSTGRES_PASSWORD=domsignal \
  -e POSTGRES_DB=domsignal -p 127.0.0.1:55474:5432 -d postgres:16.10-bookworm
export DATABASE_URL=postgresql+asyncpg://domsignal:domsignal@127.0.0.1:55474/domsignal
uv run python scripts/check.py --scope integration
```

These are synthetic local credentials, never server credentials. Integration
fixtures truncate their selected database; never point them at shared or server
data. Migration tests create/drop uniquely named temporary databases and require
CREATEDB. Migration `20260918_0002` installs `btree_gist`; the migration account
needs permission to install that PostgreSQL extension. Production runtime need
not have schema/extension privileges. Run migrations with a separate deploy role.

## Server readiness (not a deployment)

`compose.yaml` + `compose.prod.yaml`: Caddy reverse proxy, API/webhook, worker
and PostgreSQL share the Compose default private network. PostgreSQL has **no
published host port** in either file. Server DATABASE_URL uses `db:5432`, not a
public address. API remains bound to loopback; public HTTPS goes through Caddy.
Do not add a public 5432 mapping. Use protected local env files for the required
server variables; keep test session/demo seed disabled. MAX transport remains off
until separately authorized and verified. No Redis/broker/Kubernetes is needed.

## Migrations and rollback

Back up before `alembic upgrade head`. The A-15 migration preserves existing
house/report/incident/session/receipt IDs and text. Demo houses get explicit demo
company/management; non-demo legacy houses get isolated suspended/unverified
records rather than fabricated ownership. Resident verification remains unverified.
The active management exclusion constraint covers finite and open intervals,
including concurrent inserts. Incident scope and management identity are immutable.

`alembic downgrade 20260917_0001` supports a pristine C0 backfill and preserves
legacy role/evidence/created_at. It fails closed once organization memberships,
assignments, revokes/expiry, management switches or platform roles cannot be
represented safely by C0. Do not force this downgrade: restore a pre-A15 backup
into a separate database with the matching C0 application version.

## Backup: seven successful copies

Find the DB container with `docker compose -f compose.yaml -f compose.prod.yaml
ps -q db`. Run from the repository using a private directory outside the checkout:

```sh
uv run python scripts/backup_postgres.py \
  --container <db-container-id> --user domsignal --database domsignal \
  --directory /private-backups/domsignal
```

The script uses `pg_dump --format=custom --no-owner --no-acl`, publishes the dump
only after success, then retains the seven newest `domsignal-*.dump` files in
that directory. Failed dumps never rotate successful copies. Protect directory
permissions and copy backups to protected storage outside the VPS. Scheduling,
off-host transport/encryption and monitoring remain operational setup, not an
implemented backup platform. Avoid concurrent runs against the same directory.

## Restore into a separate database first

Keep API/worker away from the target while restoring. Use the PostgreSQL version
compatible with the dump. With the named target DB absent:

```sh
docker exec <db-container-id> createdb -U domsignal domsignal_restore
docker cp /private-backups/domsignal/<selected>.dump <db-container-id>:/tmp/restore.dump
docker exec <db-container-id> pg_restore -U domsignal -d domsignal_restore \
  --exit-on-error --no-owner --no-acl /tmp/restore.dump
```

Check Alembic revision, counts/content, management history, constraints and access
with a matching application version before choosing a server cutover. A restore
is not verified merely because a dump exists. Do not overwrite the source DB
as part of a test. Remove only the explicitly created temporary DB after checks.

Local evidence, 18.09.2026: PostgreSQL 16 in isolated `domsignal-a15-db`; eight
successful pg_dump runs retained seven files. pg_restore into
`a15_restore_verification` succeeded; row counts and canonical full-row hashes
matched across all 15 public tables, including Alpha→Beta history, incidents,
assignments and memberships. The temporary restore DB was removed. This is
**LOCAL VERIFIED**, not VPS restore/off-site backup or production deployment.
