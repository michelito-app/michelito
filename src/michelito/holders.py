"""The account holders of a workspace (to tell transfers between one's own accounts).

The local board and the demo read `holders.txt` from the data folder, as always. A hosted account
(an encrypted workspace) keeps them **inside its encrypted database** (the `holders` table, one
row with the same text as the file), so nothing about the person sits in plaintext at rest.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

from michelito import db
from michelito.analysis.transfers import Holders, load_holders, parse_holders
from michelito.web.workspace import Workspace


def read(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT content FROM holders WHERE id = 1").fetchone()
    return str(row[0]) if row else ""


def write(conn: sqlite3.Connection, content: str) -> None:
    """Replace the holders (the caller commits)."""
    conn.execute(
        "INSERT INTO holders (id, content) VALUES (1, ?) "
        "ON CONFLICT (id) DO UPDATE SET content = excluded.content",
        (content,),
    )


def of(workspace: Workspace, conn: sqlite3.Connection | None = None) -> Holders:
    """The workspace's holders: from its encrypted database when it has a key (with `conn` if
    one is open), else from its holders file."""
    if workspace.key is None:
        return load_holders(workspace.holders)
    if conn is not None:
        return parse_holders(read(conn))
    with closing(db.connect(workspace.database, workspace.key)) as opened:
        return parse_holders(read(opened))
