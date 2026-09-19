"""Local test-only CLI/OTP harness; no API endpoint and no production bypass."""

import asyncio
import contextlib
import io
import json
import subprocess
import sys

import pyotp
from sqlalchemy import select

from domsignal.bootstrap import build_container
from domsignal.db.models import AuthChallenge, EmployeeCredential
from domsignal.services.employee_auth import EmployeeAuthService
from domsignal.settings import AppEnvironment, get_settings
from domsignal.tools.seed_tickets import seed, seed_id


async def main():
    settings = get_settings()
    if settings.app_env != AppEnvironment.TEST or not settings.test_session_enabled:
        raise RuntimeError("This helper requires APP_ENV=test and ALLOW_TEST_SESSION=true")
    container = build_container(settings)
    try:
        if sys.argv[1] in {"setup", "setup-beta"}:
            actor = "admin" if sys.argv[1] == "setup" else "beta-admin"
            with contextlib.redirect_stdout(io.StringIO()):
                await seed(settings)
            async with container.session_factory() as db:
                exists = await db.scalar(
                    select(EmployeeCredential).where(EmployeeCredential.user_id == seed_id(actor))
                )
            if exists:
                await asyncio.to_thread(
                    subprocess.run,
                    [
                        sys.executable,
                        "-m",
                        "domsignal.tools.employee_auth",
                        "reset-mfa",
                        "--user-id",
                        str(seed_id(actor)),
                    ],
                    check=True,
                    capture_output=True,
                )
            process = await asyncio.to_thread(
                subprocess.run,
                [
                    sys.executable,
                    "-m",
                    "domsignal.tools.employee_auth",
                    "reset-password" if exists else "create",
                    "--user-id",
                    str(seed_id(actor)),
                    "--login-name",
                    "browser.employee" if actor == "admin" else "browser.beta",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            output = json.loads(process.stdout)
            print(
                json.dumps({"password": output["temporary_password"], "house": str(seed_id("a1"))})
            )
        elif sys.argv[1] == "otp":
            async with container.session_factory() as db:
                row = await db.scalar(
                    select(AuthChallenge)
                    .where(
                        AuthChallenge.stage == "mfa_enroll",
                        AuthChallenge.consumed_at.is_(None),
                        AuthChallenge.encrypted_totp_secret.is_not(None),
                    )
                    .order_by(AuthChallenge.created_at.desc())
                )
                secret = (
                    EmployeeAuthService(settings)
                    .cipher()
                    .decrypt(row.encrypted_totp_secret.encode())
                    .decode()
                )
                print(json.dumps({"code": pyotp.TOTP(secret).now()}))
        else:
            raise ValueError("Unsupported test command")
    finally:
        await container.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
