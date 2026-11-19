"""Esquema 16 (recurrentes del hogar): cadencia y grupo a mano en `recurring_marks` y la tabla
`recurring_unions`; migración desde el 15 sin perder marcas (confirmadas, descartadas,
canceladas, con cuotas) ni entradas de la bitácora, que se siguen pudiendo deshacer. Las marcas
de comercios que ahora van en un proveedor se leen como del proveedor. Datos inventados."""

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest

from finanzas import db
from finanzas.analysis import categories as cat
from finanzas.analysis import changelog, corrections, providers, spending
from finanzas.analysis import recurring_marks as marks
from finanzas.web import recurring as recurring_view
from tests.test_spending import _add_bank_rows, seed

TEL = "proveedor:telfic"
# `recurring_marks` tal como quedó en el esquema 15.
_V15_MARKS = """CREATE TABLE recurring_marks (
    merchant TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT CHECK (status IN ('confirmed', 'dismissed', 'cancelled')),
    installments_left INTEGER CHECK (installments_left IS NULL OR installments_left >= 0),
    status_on TEXT,
    installments_on TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (merchant, currency)
)"""
_V15_COLUMNS = "merchant, currency, status, installments_left, status_on, installments_on, "
_V15_COLUMNS += "updated_at"
# (comercio, estado, cuotas, día de la marca)
_MARKS = (
    ("TELFIC PAGO", "confirmed", None, date(2026, 1, 3)),
    ("TELFIC WB", "cancelled", None, date(2026, 1, 20)),
    ("TELFIC IBANKING", None, 4, date(2026, 1, 21)),
    ("GIMNASIO INVENTADO", "dismissed", None, date(2026, 1, 5)),
    ("TIENDA CUOTAS INVENTADA", "confirmed", 6, date(2026, 1, 6)),
)


@pytest.fixture(autouse=True)
def fake_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = providers.make_provider("telfic", "Telefónica Ficticia", r"TELFIC")
    monkeypatch.setattr(providers, "PROVIDERS", (fake,))


def _v15(path: Path) -> None:
    """Una base del esquema 15: pagos inventados de un proveedor con tres nombres (en
    Servicios), marcas de todo tipo hechas con la bitácora, y `recurring_marks` sin las columnas
    nuevas ni `recurring_unions`."""
    with closing(db.connect(path)) as conn:
        seed(conn)
        _add_bank_rows(
            conn,
            [
                ("2026-01-05", "TELFIC PAGO 0001", "debit", "150000"),
                ("2026-01-12", "TELFIC WB 0002", "debit", "90000"),
                ("2026-01-18", "TELFIC IBANKING 0003", "debit", "60000"),
            ],
        )
        with conn:
            for name in ("TELFIC PAGO", "TELFIC WB", "TELFIC IBANKING"):
                corrections.set_merchant_category(conn, name, cat.UTILITIES)
        for merchant, status, left, day in _MARKS:
            with (
                conn,
                changelog.track(conn, "recurrente", "recurrente", f"{merchant} · DOP", merchant),
            ):
                marks.set_status(conn, merchant, "DOP", status, day)  # type: ignore[arg-type]
                marks.set_installments(conn, merchant, "DOP", left, day)
    with closing(sqlite3.connect(path)) as raw:
        raw.execute(_V15_MARKS.replace("recurring_marks", "recurring_marks_v15", 1))
        raw.execute(
            f"INSERT INTO recurring_marks_v15 ({_V15_COLUMNS}) "
            f"SELECT {_V15_COLUMNS} FROM recurring_marks"
        )
        raw.execute("DROP TABLE recurring_marks")
        raw.execute("ALTER TABLE recurring_marks_v15 RENAME TO recurring_marks")
        raw.execute("DROP TABLE recurring_unions")
        raw.execute("PRAGMA user_version = 15")
        raw.commit()


def _rows(conn: sqlite3.Connection, table: str, columns: str = "*") -> list[tuple]:
    return [tuple(r) for r in conn.execute(f"SELECT {columns} FROM {table} ORDER BY rowid")]


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_v15_marks_and_log_survive_and_marks_follow_the_provider(tmp_path: Path) -> None:
    path = tmp_path / "v15.db"
    _v15(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 15
        assert "cadence" not in _columns(raw, "recurring_marks")
        old_marks = _rows(raw, "recurring_marks")
        old_log = _rows(raw, "change_log")
        assert len(old_marks) == len(_MARKS) and len(old_log) == len(_MARKS)
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 16
        assert {"cadence", "group_key"} <= _columns(conn, "recurring_marks")
        assert _rows(conn, "recurring_unions") == []
        # Ninguna marca se movió ni se perdió; las columnas nuevas quedan vacías.
        assert _rows(conn, "recurring_marks", _V15_COLUMNS) == old_marks
        assert _rows(conn, "recurring_marks", "cadence, group_key") == [(None, None)] * 5
        assert _rows(conn, "change_log") == old_log
        # Cada entrada se sigue pudiendo deshacer (la más reciente primero).
        entries = changelog.load(conn)
        assert all(changelog.undo_state(conn, e).allowed for e in entries)
        # Las marcas de los tres nombres se leen como del proveedor: el estado de la marcada
        # más tarde (cancelada el 20) y las cuotas anotadas (4).
        flow = [m for m in spending.load_all(conn) if m.kind == "gasto"]
        by_series = recurring_view.series_marks(flow, marks.load_for(conn, flow))
        assert by_series[(TEL, "DOP")] == marks.Mark(
            "cancelled", 4, date(2026, 1, 20), date(2026, 1, 21)
        )
        assert ("TELFIC PAGO", "DOP") not in by_series
        assert by_series[("GIMNASIO INVENTADO", "DOP")].status == "dismissed"
        assert by_series[("TIENDA CUOTAS INVENTADA", "DOP")].installments_left == 6
        # Lo nuevo funciona: una unión queda en la bitácora y se deshace.
        with (
            conn,
            changelog.track(conn, "recurrente_union", "recurrente", "TELFIC WB", "x") as draft,
        ):
            marks.set_union(conn, "TELFIC WB", "TELFIC WB")
        assert marks.load_unions(conn) == {"TELFIC WB": "TELFIC WB"}
        with conn:
            changelog.undo(conn, draft.entry_id)
        assert marks.load_unions(conn) == {}
        # Y deshacer una marca vieja (la cancelada) vuelve a como estaba antes de marcarla.
        cancelled = next(e for e in entries if e.subject == "TELFIC WB")
        with conn:
            changelog.undo(conn, cancelled.id)
        assert ("TELFIC WB", "DOP") not in marks.load(conn)
    with closing(db.connect(path)) as again:  # idempotente
        assert again.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert len(changelog.load(again)) == len(_MARKS) + 3


def test_a_failed_v16_migration_leaves_the_v15_database_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v15.db"
    _v15(path)
    with closing(sqlite3.connect(path)) as raw:
        before = _rows(raw, "recurring_marks")
    monkeypatch.setattr(db, "RECURRING_SCHEMA", ("CREATE TABLE roto (",))
    with pytest.raises(sqlite3.OperationalError):
        db.connect(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 15
        assert "cadence" not in _columns(raw, "recurring_marks")
        assert _rows(raw, "recurring_marks") == before
