"""Seeding a hosted **test** account with made-up data at an onboarding stage
(`michelito seed-test-account`), to walk through the onboarding with Claude in claude.ai and
start over as often as needed.

- Only an email the operator marked as a test account (`Store.mark_test_email`, set by
  `michelito invite --test`) can be seeded: a real account is never touched.
- And only a database the seeder made (or an empty one): one with any document that did not
  come from here (`_PREFIX`) is refused, even if its email was marked by mistake.
- The account's database is **replaced in place**: the same account, data key and folder, so its
  sessions and its AI connections keep working across runs. The new content is generated
  straight into an encrypted file with the account's key (nothing in plaintext on disk) and
  copied over the live database with SQLite's backup API (`encrypted.copy_into`), which is safe
  while the server holds connections to it.
- Stages (`STAGES`):
  - `first-statement`: right after the first upload, one credit card statement of the demo's
    made-up data (`demo.generate`, through the real validation and ingestion), with the dollar
    rates; no rules, nothing reviewed, no links, no onboarding flags.
"""

from __future__ import annotations

import os
from contextlib import closing
from datetime import date
from pathlib import Path

from michelito import db, encrypted
from michelito.analysis import rates
from michelito.demo import generate
from michelito.hosted.store import Store
from michelito.web.workspace import Workspace

FIRST_STATEMENT = "first-statement"
STAGES = (FIRST_STATEMENT,)
_SUFFIX = ".seeding"
_PREFIX = "seed-"


class SeedError(ValueError):
    """The account cannot be seeded (the message says why, with no data)."""


def seed(store: Store, email: str, workspace: Workspace, stage: str, today: date) -> None:
    """Replace the test account's database with `stage`'s made-up data (see the module)."""
    if stage not in STAGES:
        raise SeedError(f"unknown stage (one of: {', '.join(STAGES)})")
    if not store.is_test_email(email):
        raise SeedError("that email is not marked as a test account (michelito invite --test)")
    if workspace.key is None:
        raise SeedError("only encrypted hosted databases can be seeded")
    if workspace.database.exists() and _foreign_documents(workspace):
        raise SeedError("that database has documents not from the seeder: it is not replaced")
    staging = workspace.database.with_name(workspace.database.name + _SUFFIX)
    _remove(staging)
    try:
        _fill_first_statement(staging, workspace.key, today)
        if not workspace.database.exists():
            with closing(db.connect(workspace.database, workspace.key)):
                pass  # created and migrated, so there is a database to copy into
        encrypted.copy_into(staging, workspace.database, workspace.key)
    finally:
        _remove(staging)


def _foreign_documents(workspace: Workspace) -> bool:
    assert workspace.key is not None
    with closing(db.connect(workspace.database, workspace.key)) as conn:
        row = conn.execute(
            "SELECT 1 FROM documents WHERE filename NOT LIKE ? LIMIT 1", (f"{_PREFIX}%",)
        ).fetchone()
    return row is not None


def _fill_first_statement(path: Path, key: bytes, today: date) -> None:
    cards = [s for s in generate.statements(today) if s.is_liability]
    if not cards:
        raise SeedError("the generator made no card statement for that day")
    with closing(db.connect(path, key)) as conn:
        stored = generate.store(conn, cards[-1], f"{_PREFIX}000", today)
        if stored.status != "parsed":
            raise SeedError(f"the made-up statement did not square ({stored.status})")
        with conn:
            rates.store_bcrd(conn, generate.dollar_rates(today))


def _remove(path: Path) -> None:
    for leftover in (path, Path(f"{path}-wal"), Path(f"{path}-shm"), Path(f"{path}-journal")):
        if leftover.exists():
            os.remove(leftover)
