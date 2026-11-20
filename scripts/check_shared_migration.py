#!/usr/bin/env python3
"""Check the schema 19 migration (shared groups -> ledger) on a COPY of a schema 18 database.

Usage:

    cp <your database> /tmp/copy.db      # never point it at the original
    uv run python scripts/check_shared_migration.py /tmp/copy.db [--figures]

It reads the old groups with the old math (`migrations_v19.legacy_snapshot`), opens the copy the
normal way (`db.connect`, which migrates and checks the invariant itself, rolling everything back
on a difference), then recomputes every group with the ledger and compares, by group (through
the old -> new id map, `ledger_migration`) and currency, the user's share, what was paid back,
what is pending and what was written off; what each expense counts as spending; and which
credits count nothing for lack of a rate. It also counts (no amounts) the expenses and credits
kept dormant (`ledger_dormant`: they counted nothing in the old math). It prints one line per
group (`OK` or `DIFF`) and, with `--figures`, the amounts. Exits 1 on any difference. The copy
is migrated in place: make a new copy to run it again.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from michelito import db, migrations_v19
from michelito.analysis import ledger, ledger_store, rates, spending

Totals = dict[str, tuple[Decimal, ...]]


def _cents(totals: Totals) -> dict[str, tuple[int, ...]]:
    return {c: tuple(int(v * 100) for v in values) for c, values in sorted(totals.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("copy", type=Path, help="a copy of the database (it gets migrated)")
    parser.add_argument("--figures", action="store_true", help="print the amounts too")
    args = parser.parse_args()
    path: Path = args.copy
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 2
    with closing(sqlite3.connect(path)) as raw:
        version = raw.execute("PRAGMA user_version").fetchone()[0]
    if version != 18:
        print(f"expected a schema 18 database, found {version}", file=sys.stderr)
        return 2
    with closing(sqlite3.connect(path)) as raw:
        raw.row_factory = sqlite3.Row
        groups, old, _, _ = migrations_v19.legacy_snapshot(raw)
    counted_before = {e.move.fingerprint: e.counted for s in old.values() for e in s.expenses}
    uncounted_before = {fp for s in old.values() for fp in s.uncounted}
    print(f"old groups: {len(groups)} ({len(old)} with expenses present)")
    try:
        conn = db.connect(path)
    except migrations_v19.MigrationMismatch as exc:
        print(f"DIFF: the migration refused ({exc}); the copy is left at schema 18")
        return 1
    with closing(conn):
        book = ledger_store.load(conn)
        states = ledger.states(book, rates.load(conn))
        moves = {m.fingerprint: m for m in spending.load_all(conn)}
        mapping = dict(conn.execute("SELECT link_id, group_id FROM ledger_migration"))
        dormant = migrations_v19.dormant_counts(conn)
    failures = 0
    for old_id, state in sorted(old.items()):
        new = states.get(mapping.get(old_id, -1))
        before = _cents(state.totals())
        after = (
            None
            if new is None
            else _cents(
                {t.currency: (t.share, t.reimbursed, t.pending, t.written_off) for t in new.totals}
            )
        )
        same = after == before
        failures += not same
        line = f"group {old_id} -> {None if new is None else new.id}: {'OK' if same else 'DIFF'}"
        if args.figures or not same:
            line += f"  before={before} after={after}"
        print(line)
    wrong = [
        fp
        for fp, value in counted_before.items()
        if moves.get(fp) is None or moves[fp].amount != value
    ]
    uncounted_after = {fp for s in states.values() for fp in s.uncounted}
    print(f"expenses counted the same: {len(counted_before) - len(wrong)}/{len(counted_before)}")
    print(f"credits without a rate: {'same' if uncounted_after == uncounted_before else 'DIFF'}")
    failures += len(wrong) + (uncounted_after != uncounted_before)
    failures += sum(1 for g in groups if g.id not in mapping)
    print(
        f"old groups mapped to a new one: {sum(1 for g in groups if g.id in mapping)}/{len(groups)}"
    )
    print(
        "kept dormant (counted nothing before nor now): "
        f"{dormant.get('expense', 0)} expense(s), {dormant.get('payment', 0)} credit(s)"
    )
    print("RESULT:", "OK" if failures == 0 else f"{failures} difference(s)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
