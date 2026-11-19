"""Demo server for the e2e tests (made-up data from the generator).

Usage: `uv run python -m tests.e2e_demo_server --port 8600`. The demo folder (template, copies,
feedback.db) is temporary and removed on exit (uvicorn shuts down cleanly on SIGINT and SIGTERM);
if the process dies without cleaning up (SIGKILL), the next run removes the folders of servers
that are no longer alive (`_clean_orphans`, using the PID stored in each one). The cookie has no
Secure flag (local http) and the quotas are high (every test comes from 127.0.0.1). It never
touches real data.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import time
from pathlib import Path

import uvicorn

from michelito import cli
from michelito.demo.app import Settings, create_demo_app
from michelito.demo.copies import Limits

PREFIX = "michelito-demo-e2e-"
PID_FILE = "server.pid"
ORPHAN_AFTER = 600.0  # seconds: a folder without a PID older than this was orphaned


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _clean_orphans() -> None:
    """Remove the folders of earlier test servers that are no longer running."""
    for folder in Path(tempfile.gettempdir()).glob(f"{PREFIX}*"):
        pid_file = folder / PID_FILE
        try:
            pid: int | None = int(pid_file.read_text())
        except (OSError, ValueError):
            pid = None
        if (
            pid is None
        ):  # no PID: just created by another server, or from an old version if it is old
            orphan = time.time() - folder.stat().st_mtime > ORPHAN_AFTER
        else:
            orphan = not _alive(pid)
        if orphan:
            shutil.rmtree(folder, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8600)
    args = parser.parse_args()
    _clean_orphans()
    with tempfile.TemporaryDirectory(prefix=PREFIX) as directory:
        (Path(directory) / PID_FILE).write_text(str(os.getpid()))
        settings = Settings(
            data=Path(directory),
            public_host="demo.example",
            secure_cookie=False,
            repo="https://example.com/michelito",
            limits=Limits(per_ip=500, max_live=500, per_minute_new=500, per_minute=10_000),
        )
        app = create_demo_app(settings, cli.STATIC_DIR)
        try:
            uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
        finally:
            app.state.maintenance.stop()


if __name__ == "__main__":
    main()
