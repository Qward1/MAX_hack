"""ND real HTTP + PG + separate worker, then API/worker restart. Synthetic MAX only.

Use a dedicated test DATABASE_URL, migrated to head. --browser also runs the
resident/employee browser regressions while these loopback processes are alive.
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select, update

from domsignal.db.models import NotificationDelivery, ResultObservation, Ticket, User, WorkAttempt
from domsignal.db.session import create_engine, create_session_factory
from domsignal.settings import Settings
from domsignal.tools.seed_demo import seed
from domsignal.tools.seed_tickets import seed as seed_tickets
from domsignal.tools.seed_tickets import seed_id

ROOT = Path(__file__).resolve().parents[1]


async def wait_api(client, path="/ready"):
    for _ in range(100):
        try:
            response = await client.get(path)
            if response.status_code == 200:
                return
        except httpx.RequestError:
            pass
        await asyncio.sleep(0.1)
    raise RuntimeError("Fixture server did not start")


async def scenario(api_port, provider_port, restart):
    engine = create_engine(os.environ["DATABASE_URL"])
    sessions = create_session_factory(engine)
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{api_port}", timeout=10) as api:
        await wait_api(api)
        headers = {}
        for actor in ("resident", "responsible", "outsider"):
            response = await api.post("/api/v1/auth/test-session", json={"actor": f"a16-{actor}"})
            response.raise_for_status()
            headers[actor] = {"Authorization": "Bearer " + response.json()["access_token"]}

        async def get(path, actor="resident"):
            response = await api.get(path, headers=headers[actor])
            response.raise_for_status()
            return response.json()

        created = await api.post(
            "/api/v1/reports",
            headers={**headers["resident"], "Idempotency-Key": str(uuid4())},
            json={
                "house_id": str(seed_id("a1")),
                "category": "water",
                "description": "ND synthetic network smoke " + str(uuid4()),
            },
        )
        created.raise_for_status()
        incident = created.json()["incident"]["id"]
        current = await get(f"/api/v1/incidents/{incident}/work-status")
        ticket_id = current["ticket_id"]

        async def command(action, **body):
            view = await get(f"/api/v1/tickets/{ticket_id}", "responsible")
            result = await api.post(
                f"/api/v1/tickets/{ticket_id}/{action}",
                headers={**headers["responsible"], "Idempotency-Key": str(uuid4())},
                json={"expected_version": view["version"], **body},
            )
            result.raise_for_status()
            return result.json()

        async def wait_delivery(attempt_id, *, reconciled=False):
            for _ in range(150):
                async with sessions() as s:
                    row = await s.scalar(
                        select(NotificationDelivery).where(
                            NotificationDelivery.ticket_id == UUID(ticket_id),
                            NotificationDelivery.work_attempt_id == UUID(attempt_id),
                        )
                    )
                    ticket = await s.get(Ticket, UUID(ticket_id))
                    if (
                        row
                        and row.status == "accepted"
                        and (not reconciled or row.applied_version == ticket.version)
                    ):
                        return row
                await asyncio.sleep(0.1)
            raise AssertionError("Durable delivery did not reach expected provider state")

        await command("accept")
        await command("start")
        first = (await command("work-attempts", public_description="ND первая публичная работа"))[
            "attempt_id"
        ]
        row1 = await wait_delivery(first)
        launch = await get(f"/api/v1/notification-launch/{row1.launch_ref}")
        assert launch["incident_id"] == incident and launch["work_attempt_id"] == first
        foreign = await api.get(
            f"/api/v1/notification-launch/{row1.launch_ref}", headers=headers["outsider"]
        )
        assert foreign.status_code == 404 and incident not in foreign.text
        assert (await get(f"/api/v1/incidents/{incident}/work-status"))["latest_attempt"][
            "id"
        ] == first
        observation = await api.post(
            f"/api/v1/work-attempts/{first}/observations",
            headers={**headers["resident"], "Idempotency-Key": str(uuid4())},
            json={"outcome": "unresolved"},
        )
        observation.raise_for_status()
        assert observation.json()["current"]["ticket_id"] == ticket_id
        assert observation.json()["current"]["status"] == "in_progress"
        await wait_delivery(first, reconciled=True)
        second = (await command("work-attempts", public_description="ND вторая публичная работа"))[
            "attempt_id"
        ]
        row2 = await wait_delivery(second)
        event = {
            "update_type": "message_callback",
            "timestamp": int(time.time() * 1000),
            "callback": {
                "timestamp": int(time.time() * 1000),
                "callback_id": "nd-" + str(uuid4()),
                "payload": row2.launch_ref + ":resolved",
                "user": {"user_id": 91001, "is_bot": False},
            },
            "message": {
                "recipient": {"chat_id": 101001, "chat_type": "dialog"},
                "body": {"mid": row2.provider_message_id},
            },
        }
        for duplicate in (False, True):
            result = await api.post(
                "/max/webhook",
                json=event,
                headers={"X-Max-Bot-Api-Secret": "nd-synthetic-webhook-secret"},
            )
            result.raise_for_status()
            assert result.json()["duplicate"] is duplicate
        for _ in range(100):
            current = await get(f"/api/v1/incidents/{incident}/work-status")
            if current["status"] == "closed":
                break
            await asyncio.sleep(0.1)
        assert current["status"] == "closed" and current["ticket_id"] == ticket_id
        await wait_delivery(second, reconciled=True)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{provider_port}") as provider:
            for _ in range(100):
                recording = (await provider.get("/fixture-events")).json()
                if any(
                    x["operation"] == "answer"
                    and x["callback_id"] == event["callback"]["callback_id"]
                    for x in recording["events"]
                ):
                    break
                await asyncio.sleep(0.1)
            else:
                raise AssertionError("Committed callback answer was not delivered")
            for row in (row1, row2):
                body = recording["messages"][row.provider_message_id]
                assert len(body["attachments"][0]["payload"]["buttons"]) == 1
            personal = [
                x
                for x in recording["events"]
                if x["operation"] == "send"
                and x["mid"] in {row1.provider_message_id, row2.provider_message_id}
            ]
            assert len(personal) == 2 and {x["destination"] for x in personal} == {"91001"}
        restart()
        await wait_api(api)
        saved = await get(f"/api/v1/incidents/{incident}/work-status")
        assert saved["status"] == "closed" and saved["latest_attempt"]["id"] == second
        async with sessions() as s:
            attempts = await s.scalar(
                select(func.count())
                .select_from(WorkAttempt)
                .where(WorkAttempt.ticket_id == UUID(ticket_id))
            )
            observations = await s.scalar(
                select(func.count())
                .select_from(ResultObservation)
                .join(WorkAttempt)
                .where(WorkAttempt.ticket_id == UUID(ticket_id))
            )
            rows = list(
                await s.scalars(
                    select(NotificationDelivery).where(
                        NotificationDelivery.ticket_id == UUID(ticket_id),
                    )
                )
            )
            assert attempts == observations == 2
            assert len(
                {(r.outbox_message_id, r.recipient_user_id, r.channel) for r in rows}
            ) == len(rows)
            assert {r.provider_message_id for r in rows if r.work_attempt_id} == {
                row1.provider_message_id,
                row2.provider_message_id,
            }
        print(
            json.dumps(
                {
                    "result": "PASS HTTP+PG+worker+restart",
                    "ticket_id": ticket_id,
                    "incident_id": incident,
                    "attempts": attempts,
                    "observations": observations,
                    "deliveries": [
                        {"status": r.status, "provider_message_id": r.provider_message_id}
                        for r in rows
                    ],
                },
                ensure_ascii=True,
            ),
            flush=True,
        )
    await engine.dispose()


async def prepare():
    if os.getenv("APP_ENV") != "test" or os.getenv("ND_FIXTURES") != "1":
        raise RuntimeError("APP_ENV=test and ND_FIXTURES=1 required; use a dedicated DB")
    config = Settings(_env_file=None, app_env="test", database_url=os.environ["DATABASE_URL"])
    await seed(config)
    await seed_tickets(config)
    engine = create_engine(config.database_url)
    async with create_session_factory(engine)() as s, s.begin():
        await s.execute(
            update(User)
            .where(User.id == seed_id("resident"))
            .values(
                max_user_id="91001",
                max_identity_verified_at=datetime.now(UTC),
            )
        )
    await engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-port", type=int, default=18088)
    parser.add_argument("--provider-port", type=int, default=18089)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    asyncio.run(prepare())
    env = {
        **os.environ,
        "ND_PROVIDER_PORT": str(args.provider_port),
        "ND_RUN_ID": uuid4().hex,
        "B14_BROWSER_FIXTURES": "1",
        "PLAYWRIGHT_BASE_URL": f"http://127.0.0.1:{args.api_port}",
        "PYTHONPATH": os.pathsep.join(
            [str(ROOT), str(ROOT / "src"), sysconfig.get_path("purelib")]
        ),
    }
    with tempfile.TemporaryDirectory(prefix="domsignal-nd-") as tmp:
        logs = open(Path(tmp) / "processes.log", "w+", encoding="utf-8", errors="replace")
        processes = []

        def start(*arguments):
            p = subprocess.Popen(
                [getattr(sys, "_base_executable", sys.executable), *arguments],
                cwd=ROOT,
                env=env,
                stdout=logs,
                stderr=subprocess.STDOUT,
            )
            processes.append(p)
            return p

        api = worker = None

        def restart():
            nonlocal api, worker
            for p in (api, worker):
                if p is not None:
                    p.terminate()
                    p.wait(timeout=15)
            api = start(
                "-m",
                "uvicorn",
                "tests.fakes.notification_runtime:app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.api_port),
            )
            worker = start("-m", "tests.fakes.notification_runtime", "worker")

        try:
            start(
                "-m",
                "uvicorn",
                "tests.fakes.notification_runtime:provider_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.provider_port),
            )
            restart()
            asyncio.run(scenario(args.api_port, args.provider_port, restart))
            if args.browser:
                subprocess.run(
                    [shutil.which("npm") or "npm", "run", "test:browser"],
                    cwd=ROOT / "miniapp",
                    env=env,
                    check=True,
                )
        except BaseException:
            logs.flush()
            logs.seek(0)
            print(logs.read()[-16000:], file=sys.stderr)
            raise
        finally:
            for p in processes:
                if p.poll() is None:
                    p.terminate()
                    p.wait(timeout=15)
            logs.close()


if __name__ == "__main__":
    main()
