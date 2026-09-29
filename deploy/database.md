# PostgreSQL: local, server and recovery

PostgreSQL 16 + asyncpg is the only supported DomSignal runtime database for
API, workers, local development, integration tests and server deployment.
SQLite is not a runtime option or fallback. Settings/engine reject other URLs.

## Local development and integration

`docker compose up --build` supplies PostgreSQL on the private Compose network.
For host-side Python tests use a separate disposable PostgreSQL container:

```sh
docker run --name domsignal-test-db \
  -e POSTGRES_USER=domsignal -e POSTGRES_PASSWORD=domsignal \
  -e POSTGRES_DB=domsignal -p 127.0.0.1:55474:5432 -d postgres:16.10-bookworm
export DATABASE_URL=postgresql+asyncpg://domsignal:domsignal@127.0.0.1:55474/domsignal
uv run python scripts/check.py --scope integration
```

These are local test credentials, never server credentials. Integration
fixtures truncate their selected database; never point them at shared or server
data. Migration tests create/drop uniquely named temporary databases and require
CREATEDB. Migration `20260918_0002` installs `btree_gist`; the migration account
needs permission to install that PostgreSQL extension. Production runtime need
not have schema/extension privileges. Run migrations with a separate deploy role.

## Server layout

`compose.yaml` + `compose.prod.yaml`: Caddy reverse proxy, API/webhook, workers
and PostgreSQL share the Compose default private network. PostgreSQL has **no
published host port** in either file. Server DATABASE_URL uses `db:5432`, not a
public address. API remains bound to loopback; public HTTPS goes through Caddy.
Do not add a public 5432 mapping. Use protected local env files for the required
server variables; keep test session/demo seed disabled. Local Compose keeps the
MAX transport off; the production overlay selects the webhook transport
([`README.md`](README.md) §2). No Redis/broker/Kubernetes is needed.

## Migrations and rollback

Back up before `alembic upgrade head`. The tenant-access migration
(`20260918_0002`) preserves existing house/report/incident/session/receipt IDs
and text. Demo houses get explicit demo company/management; non-demo legacy
houses get isolated suspended/unverified records rather than fabricated
ownership. Resident verification remains unverified. The active management
exclusion constraint covers finite and open intervals, including concurrent
inserts. Incident scope and management identity are immutable.

`alembic downgrade 20260917_0001` supports a pristine backfill and preserves
legacy role/evidence/created_at. It fails closed once organization memberships,
assignments, revokes/expiry, management switches or platform roles cannot be
represented safely by the `20260917_0001` schema. Do not force this downgrade:
restore a backup taken before `20260918_0002` into a separate database with the
matching application version.

## Backup: verified copies, fourteen by default

Find the DB container with `docker compose -f compose.yaml -f compose.prod.yaml
ps -q db`. Run from the repository using a private directory outside the checkout:

```sh
uv run python scripts/backup_postgres.py \
  --container <db-container-id> --user domsignal --database domsignal \
  --directory /private-backups/domsignal
```

The script uses `pg_dump --format=custom --no-owner --no-acl`, publishes the dump
only after success, checks it with `pg_restore --list` (an unreadable dump is
removed), then retains the `--keep` newest (14 by default) `domsignal-*.dump` files in
that directory. Failed dumps never rotate successful copies. Protect directory
permissions and copy backups to protected storage outside the VPS. The daily
schedule is a systemd timer (`deploy/systemd`; see [`README.md`](README.md) §7);
off-host transport and encryption remain operational setup. Avoid concurrent
runs against the same directory.

## Restore into a separate database first

Keep API/workers away from the target while restoring. Use the PostgreSQL version
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

Local check, 18.09.2026, PostgreSQL 16 in an isolated container: `pg_restore`
into a separate verification database succeeded; row counts and canonical
full-row hashes matched across all public tables of that schema version,
including management history, incidents, assignments and memberships. The
temporary restore DB was removed.
