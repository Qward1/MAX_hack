"""Real network HTTP A-16 smoke. Run seed_tickets separately against an isolated DB.

Creates one synthetic report/work chain per run; does not reset any data or send MAX.
--read-incident UUID performs the persistence check after an API/worker restart.
"""

import argparse
import asyncio
import json
from uuid import UUID, uuid4

import httpx

from domsignal.tools.seed_tickets import seed_id


async def smoke(base_url: str, read_incident: UUID | None) -> None:
    # This script uses test-session credentials and must never target a public deployment.
    if httpx.URL(base_url).host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Smoke must target a loopback test server")
    async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
        headers = {}
        for actor in ("resident", "responsible"):
            response = await client.post(
                "/api/v1/auth/test-session", json={"actor": f"a16-{actor}"}
            )
            response.raise_for_status()
            headers[actor] = {"Authorization": "Bearer " + response.json()["access_token"]}

        async def get_status(incident: str) -> dict:
            response = await client.get(
                f"/api/v1/incidents/{incident}/work-status", headers=headers["resident"]
            )
            response.raise_for_status()
            return response.json()

        if read_incident:
            current = await get_status(str(read_incident))
            assert (
                current["status"] == "in_progress" and current["latest_attempt"]["rework_required"]
            )
            print(
                json.dumps(
                    {
                        "result": "PASS restart read",
                        "incident_id": str(read_incident),
                        "ticket_id": current["ticket_id"],
                        "version": current["version"],
                    }
                )
            )
            return

        created = await client.post(
            "/api/v1/reports",
            headers={**headers["resident"], "Idempotency-Key": str(uuid4())},
            json={
                "house_id": str(seed_id("a1")),
                "category": "water",
                "description": "A16 reproducible synthetic HTTP smoke",
            },
        )
        created.raise_for_status()
        incident = created.json()["incident"]["id"]
        current = await get_status(incident)
        ticket_id = current["ticket_id"]
        version = current["version"]
        attempt_id = None
        for action in ("accept", "start", "work-attempts"):
            payload = {"expected_version": version}
            if action == "work-attempts":
                payload["public_description"] = "Тестовый публичный отчёт о результате"
            response = await client.post(
                f"/api/v1/tickets/{ticket_id}/{action}",
                headers={**headers["responsible"], "Idempotency-Key": str(uuid4())},
                json=payload,
            )
            response.raise_for_status()
            version = response.json()["ticket"]["version"]
            attempt_id = response.json()["attempt_id"]
        for outcome, expected in (("resolved", "closed"), ("unresolved", "in_progress")):
            response = await client.post(
                f"/api/v1/work-attempts/{attempt_id}/observations",
                headers={**headers["resident"], "Idempotency-Key": str(uuid4())},
                json={"outcome": outcome},
            )
            response.raise_for_status()
            assert response.json()["current"]["status"] == expected
        current = await get_status(incident)
        assert current["ticket_id"] == ticket_id and current["latest_attempt"]["rework_required"]
        print(
            json.dumps(
                {
                    "result": "PASS HTTP lifecycle",
                    "incident_id": incident,
                    "ticket_id": ticket_id,
                    "attempt_id": attempt_id,
                    "version": current["version"],
                }
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8026")
    parser.add_argument("--read-incident", type=UUID)
    args = parser.parse_args()
    asyncio.run(smoke(args.base_url, args.read_incident))
