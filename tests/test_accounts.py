from datetime import date

import pytest

from finanzas import db
from finanzas.analysis import accounts
from tests.test_spending import seed


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    seed(connection)
    yield connection
    connection.close()


def test_account_infos_labels_and_coverage(conn) -> None:
    infos = accounts.account_infos(conn)

    assert len(infos) == 3
    kinds = [i.kind for i in infos]
    assert kinds == sorted(kinds, key=lambda kind: kind != "credit_card")
    assert kinds.count("credit_card") == 2
    for info in infos:
        if info.kind == "credit_card":
            assert info.label.endswith("···" + _last4(conn, info))
        else:
            name = conn.execute("SELECT name FROM accounts WHERE key = ?", (info.key,)).fetchone()
            assert info.label == name[0]
        latest = conn.execute(
            "SELECT MAX(s.period_end) FROM statements s JOIN accounts a ON a.id = s.account_id "
            "WHERE a.key = ?",
            (info.key,),
        ).fetchone()[0]
        assert info.through == date.fromisoformat(latest)


def _last4(conn, info: accounts.AccountInfo) -> str:
    row = conn.execute(
        "SELECT c.last4 FROM cards c JOIN accounts a ON a.id = c.account_id WHERE a.key = ? "
        "ORDER BY c.last_seen DESC LIMIT 1",
        (info.key,),
    ).fetchone()
    return row[0]
