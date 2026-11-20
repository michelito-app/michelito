"""Builds `schema_v18_shared.sql` and `schema_v18_shared_expected.json` with the code of the
schema 18 release (commit 0be7009), so the schema 19 tests start from a file that release wrote
and compare against figures its own math computed. Synthetic data only (tests/samples.py).

It is not a test and does not run with today's code. To rebuild the fixture:

    git archive 0be7009 src tests | tar -x -C /tmp/old
    PYTHONPATH=/tmp/old/src:/tmp/old uv run python tests/fixtures/make_schema_v18_shared.py \
        tests/fixtures/schema_v18_shared.sql tests/fixtures/schema_v18_shared_expected.json
"""

import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import michelito
from michelito import db
from michelito.analysis import changelog, links, rates, shared, spending
from tests.test_spending import _add_bank_rows, seed

assert db.SCHEMA_VERSION == 18, f"run it with the schema 18 code, not {michelito.__file__}"
out_sql, out_json = Path(sys.argv[1]), Path(sys.argv[2])

path = Path(tempfile.mkdtemp()) / "v18.db"
with closing(db.connect(path)) as conn:
    seed(conn)
    _add_bank_rows(
        conn,
        [
            ("2026-01-04", "TOKE DE PEDRO INVENTADO", "credit", "5000"),
            ("2026-01-06", "TOKE DE LUISA INVENTADA", "credit", "5000"),
            ("2026-01-07", "TRANSFERENCIA DE ANA FICTICIA", "credit", "200000"),
            ("2026-01-09", "TOKE DE ROSA FICTICIA", "credit", "123457"),
            ("2026-01-12", "TOKE DE LUIS INVENTADO", "credit", "40000"),
            ("2026-01-14", "DEPOSITO DE PRIMA FICTICIA", "credit", "6000"),
            ("2026-01-16", "TOKE DE ANA FICTICIA", "credit", "777700"),
        ],
    )
    with conn:
        rates.store_bcrd(conn, {"2025-12": D("60"), "2026-01": D("61.5")})
    flow = spending.load_all(conn)
    by_text = {m.description: m for m in flow}
    expenses = [m for m in flow if m.kind == "expense" and m.amount > 0]
    credits = [m for m in flow if m.amount < 0 and m.kind != "transfer"]
    cafe = next(m for m in expenses if m.description.startswith("CAFE"))
    pharmacy = next(m for m in expenses if m.description.startswith("FARMACIA"))
    online = [m for m in expenses if m.description.startswith("TIENDA ONLINE")]
    market = next(m for m in expenses if m.description.startswith("SUPERMERCADO"))
    colmado = next(m for m in expenses if m.description.startswith("COLMADO"))
    with conn:
        # 1. "We were 3" with one name, a credit and a manual one (in another account).
        g1 = links.set_shared(conn, cafe.fingerprint, cafe.amount, people=3, with_whom="Ana")
        links.add_reimbursement(conn, g1, by_text["TOKE DE PEDRO INVENTADO"].fingerprint)
        place = "Banco Ficticio"  # spanish-data
        links.add_manual(conn, g1, D(25), date(2026, 1, 3), "DOP", "Ana", place)
        # 2. Two people, a US$ expense "for someone else" and a RD$ one "my share"; a RD$ credit
        # converted to US$; written off.
        g2 = links.set_shared(
            conn, online[0].fingerprint, online[0].amount, for_other=True, with_whom="Luis y Rosa"
        )
        links.add_expense(conn, g2, pharmacy.fingerprint, pharmacy.amount, my_share=D(100))
        links.add_reimbursement(conn, g2, by_text["TOKE DE ROSA FICTICIA"].fingerprint)
        links.set_group(conn, g2, name="Casa")
        links.set_written_off(conn, g2, True)
        # 3. One person, paid back in excess (a repeated credit): stays unattributed.
        g3 = links.set_shared(conn, colmado.fingerprint, colmado.amount, people=2, with_whom="Ana")
        links.add_reimbursement(conn, g3, by_text["TOKE DE ANA FICTICIA"].fingerprint)
        # 4. One person, partly paid back in US$ by hand (multi-currency, attributed).
        g4 = links.set_shared(conn, market.fingerprint, market.amount, people=2, with_whom="Luis")
        links.add_manual(conn, g4, D("5.00"), date(2026, 1, 2), "USD", "Luis")
        links.add_reimbursement(conn, g4, by_text["TOKE DE LUIS INVENTADO"].fingerprint)
        # 5. A US$ group with a dormant expense (its transaction will be gone) and a credit
        # that will stop being a credit.
        g5 = links.set_shared(
            conn, online[1].fingerprint, online[1].amount, people=4, with_whom="Rosa, Pedro & Ana"
        )
        links.add_reimbursement(conn, g5, by_text["DEPOSITO DE PRIMA FICTICIA"].fingerprint)
        # 6. A dormant group: its only expense will be gone; its credit stays.
        g6 = links.set_shared(conn, "0f0f0f0f0f0f0f0f0f0f0f0f", D(500), people=2)
        links.add_reimbursement(conn, g6, by_text["TOKE DE LUISA INVENTADA"].fingerprint)
    # The change log of the old release: creating a group and deleting a manual reimbursement
    # (its "after" is nothing: before schema 19 it could be undone).
    with conn, changelog.track(conn, "shared", "link", str(g1), "Ana") as made:
        manual = links.add_manual(conn, g1, D(30), date(2026, 1, 5), "DOP", "Ana")
    with conn, changelog.track(conn, "shared", "link", str(g1), "Ana") as removed:
        links.remove_manual(conn, g1, manual)
    # Group 5's credit stops being a credit (it becomes a debit): a dormant link.
    with conn:
        conn.execute(
            "UPDATE transactions SET direction = 'debit' WHERE description = ?",
            ("DEPOSITO DE PRIMA FICTICIA",),
        )
    # Expected, with the old code.
    flow = spending.load_all(conn)
    found = links.load(conn)
    states = shared.states(flow, found, rates.load(conn))
    expected = {
        "groups": {
            str(gid): {
                t.currency: [str(t.share), str(t.reimbursed), str(t.pending), str(t.written_off)]
                for t in st.totals
            }
            for gid, st in states.items()
        },
        "movements": {
            m.fingerprint: [str(m.amount), m.link]
            for m in flow
            if m.link in ("shared", "reimbursement")
        },
        "dormant_groups": [g for g in (g6,) if g not in states],
        "log": {"made": made.entry_id, "removed": removed.entry_id},
        "ids": {"g1": g1, "g2": g2, "g3": g3, "g4": g4, "g5": g5, "g6": g6},
    }
with closing(sqlite3.connect(path)) as raw:
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 18
    lines = list(raw.iterdump())
out_sql.write_text("PRAGMA user_version = 18;\n" + "\n".join(lines) + "\n", encoding="utf-8")
out_json.write_text(json.dumps(expected, indent=1, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(expected["groups"], indent=1))
