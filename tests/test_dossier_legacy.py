"""Insights saved before the English rename stay fresh, and their dossier header is still read.

`fixtures/schema_v17_dossier_hashes.json` holds the dossier hash the previous release computed
from `fixtures/schema_v17.sql` for every month with data and a few account selections (key:
"<month> <keys or legacy.DOSSIER_ALL_ACCOUNTS>"), i.e. the `data_hash` an insight saved by
that release stores. It was produced by running the previous release's `dossier.build` over
the fixture, so these tests compare the rebuilt legacy hash against the real old code, not
against a translation of itself.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db, dossier, legacy
from michelito.analysis import insights, providers, spending
from michelito.i18n import t
from michelito.web.app import create_app
from tests import e2e_server as e2e

FIXTURES = Path(__file__).parent / "fixtures"
OLD_HASHES: dict[str, str] = json.loads(
    (FIXTURES / "schema_v17_dossier_hashes.json").read_text(encoding="utf-8")
)
# The fixture's saved insight: January, for the cash box and one savings account.
INSIGHT_MONTH = "2026-01"
INSIGHT_ACCOUNTS = f"{legacy.CASH_BOX_KEY},popular:savings:FIC-3"


@pytest.fixture(autouse=True)
def _demo_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixture's recurring series use the e2e server's made-up providers."""
    known = {p.key for p in providers.PROVIDERS}
    extra = tuple(p for p in e2e.DEMO_PROVIDERS if p.key not in known)
    monkeypatch.setattr(providers, "PROVIDERS", (*providers.PROVIDERS, *extra))


@pytest.fixture
def v17(tmp_path: Path) -> Path:
    """The schema-17 fixture database, migrated to the current schema on first connect."""
    path = tmp_path / "v17.db"
    with closing(sqlite3.connect(path)) as raw:
        raw.executescript((FIXTURES / "schema_v17.sql").read_text(encoding="utf-8"))
    with closing(db.connect(path)):
        pass
    return path


def _accounts(old: str) -> list[str] | None:
    if old == legacy.DOSSIER_ALL_ACCOUNTS:
        return None
    return [legacy.translate_key(key) for key in old.split(",")]


def test_the_legacy_hash_is_the_one_the_previous_release_computed(v17: Path) -> None:
    with closing(db.connect(v17)) as conn:
        flow = spending.load_all(conn, ())
        for key, old_hash in OLD_HASHES.items():
            month, old_accounts = key.split(" ")
            built = dossier.build(conn, month, accounts=_accounts(old_accounts), flow=flow)
            assert built.legacy_hash == old_hash, key
            assert built.data_hash != old_hash, key  # the English data hashes differently


def test_an_insight_saved_before_the_rename_is_fresh_and_gets_the_new_hash(v17: Path) -> None:
    old_hash = OLD_HASHES[f"{INSIGHT_MONTH} {INSIGHT_ACCOUNTS}"]
    with closing(db.connect(v17)) as conn, conn:
        # What the previous release stored when it saved this insight.
        conn.execute("UPDATE insights SET data_hash = ? WHERE month = ?", (old_hash, INSIGHT_MONTH))
        current = dossier.build(conn, INSIGHT_MONTH, accounts=_accounts(INSIGHT_ACCOUNTS))
    client = TestClient(create_app(v17), "http://127.0.0.1")
    [item] = client.get("/api/insights").json()
    assert (item["month"], item["stale"]) == (INSIGHT_MONTH, False)
    assert item["accounts"] == ["manual:cash-box", "popular:savings:FIC-3"]
    with closing(db.connect(v17)) as conn:
        found = insights.get(conn, INSIGHT_MONTH)
    assert found is not None and found.data_hash == current.data_hash
    assert client.get(f"/api/insights/{INSIGHT_MONTH}").json()["stale"] is False


def test_an_unknown_hash_stays_stale(v17: Path) -> None:
    # The fixture's insight hash matches neither the new nor the old dossier.
    client = TestClient(create_app(v17), "http://127.0.0.1")
    assert client.get(f"/api/insights/{INSIGHT_MONTH}").json()["stale"] is True
    with closing(db.connect(v17)) as conn:
        found = insights.get(conn, INSIGHT_MONTH)
    assert found is not None and found.data_hash == "hash-ficticio"


def test_dossier_data_restores_the_old_keys_and_values() -> None:
    new = {
        "month": "2026-01",
        "account_keys": ["popular:savings:FIC-3", "manual:cash-box", "a:z"],
        "what_happened": [{"side": "expense"}, {"side": "income"}],
        "transactions": [
            {"kind": "transfer", "fingerprint": "cash-12", "link": "cash_box", "note": None},
            {"kind": "expense", "fingerprint": "cashier-1", "category": "income"},
        ],
        "to_review": [{"kind": "possible_return", "fingerprint": "cash-3", "reviewed": True}],
        "shared_and_exchanges": {"owed_to_me": "1.00", "exchanges_pending": None},
    }
    # The pre-rename (Spanish) dossier keys and values.
    # spanish-data: begin
    assert legacy.dossier_data(new) == {
        "mes": "2026-01",
        "claves_de_cuentas": ["a:z", "manual:caja-fuerte", "popular:savings:FIC-3"],
        "que_paso": [{"lado": "gasto"}, {"lado": "ingreso"}],
        "movimientos": [
            {"tipo": "transferencia", "huella": "caja-12", "vinculo": "cash_box", "nota": None},
            {"tipo": "gasto", "huella": "cashier-1", "categoria": "income"},
        ],
        "para_revisar": [{"tipo": "cobro_posible", "huella": "caja-3", "revisado": True}],
        "compartidos_y_cambios": {"te_deben": "1.00", "cambios_pendientes": None},
    }
    # spanish-data: end


@pytest.mark.parametrize(
    ("header", "accounts"),
    [
        # The header written before the rename.
        # spanish-data: begin
        ("<!-- dossier finanzas: mes=2026-01 cuentas=todas -->", None),
        (
            "<!-- dossier finanzas: mes=2026-01 cuentas=popular:x,manual:caja-fuerte -->",
            ["manual:cash-box", "popular:x"],
        ),
        # spanish-data: end
        ("<!-- michelito dossier: month=2026-01 accounts=all -->", None),
        ("<!-- michelito dossier: month=2026-01 accounts=b,a -->", ["a", "b"]),
    ],
)
def test_the_header_is_read_in_both_forms(header: str, accounts: list[str] | None) -> None:
    pasted = dossier.split_header(f"{header}\n## January\n\nAll good.", "2026-01")
    assert pasted.has_header and pasted.accounts == accounts
    assert pasted.text == "\n## January\n\nAll good."
    other_month = t("dossier.other_month", found="2026-01", month="2026-02")
    with pytest.raises(ValueError, match=re.escape(other_month)):
        dossier.split_header(header, "2026-02")
