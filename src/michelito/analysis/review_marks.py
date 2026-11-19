"""What was marked "Already reviewed" in "To review", by fingerprint and kind (see
`analysis.review`).

Kept apart from `transactions` (like the corrections), so it survives `parse --retry`. One-off
expenses don't go here: their "reviewed" is the usual dismissal (`one_off_dismissals`).
Nothing here commits: the caller wraps the write in `with conn:`.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from michelito.db import REVIEW_MARK_KINDS


def load(conn: sqlite3.Connection) -> frozenset[tuple[str, str]]:
    rows = conn.execute("SELECT fingerprint, kind FROM review_marks")
    return frozenset((str(row[0]), str(row[1])) for row in rows)


def set_reviewed(conn: sqlite3.Connection, fingerprint: str, kind: str, reviewed: bool) -> None:
    if kind not in REVIEW_MARK_KINDS:
        raise ValueError(f"unknown review kind: {kind}")
    if not reviewed:
        conn.execute(
            "DELETE FROM review_marks WHERE fingerprint = ? AND kind = ?", (fingerprint, kind)
        )
        return
    conn.execute(
        "INSERT INTO review_marks (fingerprint, kind, reviewed_at) VALUES (?, ?, ?) "
        "ON CONFLICT(fingerprint, kind) DO NOTHING",
        (fingerprint, kind, datetime.now(UTC).isoformat(timespec="seconds")),
    )
