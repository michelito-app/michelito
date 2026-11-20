"""Hosted-mode server for the e2e tests (synthetic accounts, emails written to an outbox folder).

    uv run python -m tests.e2e_hosted_server --port 8636 --dir /tmp/michelito-hosted-e2e-8636
    uv run python -m tests.e2e_hosted_server expire-step-up --dir DIR --email EMAIL

The folder is wiped on start (it must be under the system's temporary folder and carry the
`michelito-hosted-e2e-` prefix). Every email goes to `<dir>/outbox/` as a JSON file, which the
Playwright specs read to get the code: nothing is sent anywhere. The cookie has no Secure flag
(local http), the minimum answer time is short and the per-IP limits are high (every test comes
from 127.0.0.1); the per-email limit, the attempts and the expiries are the real ones. People
are invited with `michelito invite EMAIL --data DIR --mailer outbox`, as on a server. The master
key is a throwaway one, generated next to the folder (`<dir>.master.key`, never inside it) and
removed with it.

`expire-step-up` makes every session's last verification older than the step-up window, so a
spec can prove the step-up is demanded without waiting ten minutes. It never touches real data.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import uvicorn

from michelito import cli
from michelito.hosted.app import Settings, create_hosted_app
from michelito.hosted.keys import write_master
from michelito.hosted.limits import Caps
from michelito.hosted.mailer import OutboxMailer
from michelito.hosted.store import FILENAME

PREFIX = "michelito-hosted-e2e-"
PORT_ENV = "E2E_HOSTED_PORT"


def _checked(directory: str) -> Path:
    path = Path(directory).resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    if not (path.name.startswith(PREFIX) and path.parent == temp):
        raise SystemExit(f"the e2e folder must be {temp}/{PREFIX}*")
    return path


def serve(port: int, directory: Path, demo_url: str) -> None:
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(mode=0o700)
    master = directory.with_name(f"{directory.name}.master.key")
    master.unlink(missing_ok=True)
    write_master(master)
    settings = Settings(
        data=directory,
        public_url=f"http://127.0.0.1:{port}",
        demo_url=demo_url,
        secure_cookie=False,
        floor=0.05,
        caps=Caps(codes_per_ip=10_000, verifications_per_ip=10_000, emails_per_ip_day=10_000),
        master_key=master,
    )
    app = create_hosted_app(settings, OutboxMailer(directory / "outbox"), cli.STATIC_DIR)
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        app.state.dispatcher.stop()
        shutil.rmtree(directory, ignore_errors=True)
        master.unlink(missing_ok=True)


def expire_step_up(directory: Path, email: str) -> None:
    """Only the sessions of that (made-up) email: other specs' sessions are left alone."""
    with sqlite3.connect(directory / FILENAME) as conn:
        conn.execute(
            "UPDATE sessions SET verified_at = 0 WHERE account_id IN "
            "(SELECT id FROM accounts WHERE email = ?)",
            (email,),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("serve", "expire-step-up"), default="serve")
    parser.add_argument("--port", type=int, default=int(os.environ.get(PORT_ENV, "8636")))
    parser.add_argument("--dir", required=True)
    parser.add_argument("--email", help="expire-step-up: whose sessions")
    parser.add_argument("--demo-url", default="https://demo.example", help="the demo to link")
    args = parser.parse_args()
    directory = _checked(args.dir)
    if args.action == "expire-step-up":
        if not args.email:
            parser.error("expire-step-up needs --email")
        expire_step_up(directory, args.email)
    else:
        serve(args.port, directory, args.demo_url)


if __name__ == "__main__":
    main()
