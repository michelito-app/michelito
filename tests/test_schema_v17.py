"""Esquema 17 (presupuesto y reservas): migración desde el 16 sin perder vínculos, lo revisado ni
la bitácora (que se sigue pudiendo deshacer); después caben una reserva con su gasto, un tope y
una sugerencia descartada, y todo eso se registra y se deshace. Datos inventados."""

import sqlite3
from contextlib import closing
from decimal import Decimal as D
from pathlib import Path

import pytest

from finanzas import db
from finanzas.analysis import (
    budget,
    budget_store,
    catalog,
    changelog,
    links,
    reserve_store,
    review_marks,
    spending,
)
from finanzas.analysis import categories as cat
from tests.test_spending import seed

_RESERVE_COLUMNS = [name for name, _ in db.RESERVE_COLUMNS["links"]]
# Lo que el esquema 17 agregó a cada CHECK (para volver a como eran en el 16).
_ADDED = {
    "links": ", 'reserve'",
    "link_members": ", 'reserved'",
    "review_marks": ", 'reserva_posible'",
}


def _downgrade(raw: sqlite3.Connection) -> None:
    """Deja la base como en el esquema 16: sin las columnas ni las tablas nuevas y con los CHECK
    de antes (rehaciendo cada tabla con sus filas, como `db._rebuild_check`)."""
    for column in reversed(_RESERVE_COLUMNS):
        raw.execute(f"ALTER TABLE links DROP COLUMN {column}")
    for table, added in _ADDED.items():
        sql = raw.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()[0]
        assert added in sql
        columns = ", ".join(r[1] for r in raw.execute(f"PRAGMA table_info({table})"))
        old = sql.replace(added, "").replace(
            f"CREATE TABLE {table}", f"CREATE TABLE {table}_v16", 1
        )
        old = old.replace(f'CREATE TABLE "{table}"', f"CREATE TABLE {table}_v16", 1)
        seq = raw.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
        raw.execute(old)
        raw.execute(f"INSERT INTO {table}_v16 ({columns}) SELECT {columns} FROM {table}")
        raw.execute(f"DROP TABLE {table}")
        raw.execute(f"ALTER TABLE {table}_v16 RENAME TO {table}")
        if seq is not None:  # como en una base del 16 de verdad: la secuencia no baja
            raw.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (seq[0], table))
    raw.execute("DROP TABLE budget_caps")
    raw.execute("DROP TABLE reserve_dismissals")
    raw.execute("PRAGMA user_version = 16")
    raw.commit()


def _v16(path: Path) -> dict[str, str]:
    """Una base del esquema 16: un gasto compartido y lo revisado de un movimiento, hechos con la
    bitácora. Devuelve las huellas que se usan."""
    with closing(db.connect(path)) as conn:
        seed(conn)
        flow = [m for m in spending.load_all(conn) if m.kind == "gasto" and m.amount > 0]
        shared, reviewed, free = flow[0], flow[1], flow[2]
        with conn, changelog.track(conn, "compartido", "transaccion", shared.fingerprint, "x"):
            links.set_shared(conn, shared.fingerprint, shared.amount, people=2)
        with conn, changelog.track(conn, "revisado", "transaccion", reviewed.fingerprint, "y"):
            review_marks.set_reviewed(conn, reviewed.fingerprint, "duplicado", True)
    with closing(sqlite3.connect(path)) as raw:
        _downgrade(raw)
    return {
        "shared": shared.fingerprint,
        "reviewed": reviewed.fingerprint,
        "free": free.fingerprint,
    }


def _rows(conn: sqlite3.Connection, table: str, columns: str = "*") -> list[tuple]:
    return [tuple(r) for r in conn.execute(f"SELECT {columns} FROM {table} ORDER BY rowid")]


def _sql(conn: sqlite3.Connection, table: str) -> str:
    return conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()[0]


def test_v16_rows_and_log_survive_and_reserves_fit(tmp_path: Path) -> None:
    path = tmp_path / "v16.db"
    fps = _v16(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 16
        assert "'reserve'" not in _sql(raw, "links")
        before = {t: _rows(raw, t) for t in ("links", "link_members", "review_marks", "change_log")}
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 17
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert "'reserve'" in _sql(conn, "links")
        assert "'reserved'" in _sql(conn, "link_members")
        assert "'reserva_posible'" in _sql(conn, "review_marks")
        assert "AUTOINCREMENT" in _sql(conn, "budget_caps")
        assert "AUTOINCREMENT" in _sql(conn, "reserve_dismissals")
        # Ninguna fila se perdió ni cambió; las columnas nuevas quedan vacías.
        old = [c for c in (r[1] for r in conn.execute("PRAGMA table_info(links)"))]
        kept = ", ".join(c for c in old if c not in _RESERVE_COLUMNS)
        assert _rows(conn, "links", kept) == before["links"]
        assert _rows(conn, "links", "reserve_cents, category_id, multiple") == [(None, None, 0)]
        for table in ("link_members", "review_marks", "change_log"):
            assert _rows(conn, table) == before[table], table
        # Lo de antes se sigue pudiendo deshacer.
        assert all(changelog.undo_state(conn, e).allowed for e in changelog.load(conn))

        # Lo nuevo cabe: una reserva con su gasto, un tope y una sugerencia descartada.
        tax = catalog.resolve_ref(conn, cat.GOVERNMENT)
        with conn, changelog.track(conn, "reserva", "vinculo", "0", "Marbete") as made:
            reserve = reserve_store.create(
                conn, name="Marbete", amount=D(3500), category_id=tax, due_month="2027-01",
                every_months=12,
            )  # fmt: skip
        with conn, changelog.track(conn, "reserva_gasto", "transaccion", fps["free"], "z") as tied:
            reserve_store.add_member(conn, reserve, fps["free"])
        with pytest.raises(links.AlreadyLinked):  # una huella, un solo vínculo
            reserve_store.add_member(conn, reserve, fps["shared"])
        with conn, changelog.track(conn, "presupuesto", "categoria", str(tax), "Gob") as capped:
            budget_store.set_cap(conn, tax, D(2000))
        with conn, changelog.track(conn, "reserva_descarte", "vinculo", "k", "k") as dropped:
            reserve_store.dismiss(conn, "pico:x:12")
        assert links.load(conn).reserve_for(fps["free"]) == reserve
        assert budget_store.load(conn) == {tax: budget.Cap(tax, D(2000), True, None)}
        assert reserve_store.dismissed(conn) == {"pico:x:12"}
        # Cada una quedó en la bitácora y se deshace (también el ensayo en un SAVEPOINT).
        for draft in (dropped, capped, tied, made):
            assert draft.entry_id is not None
            entry = changelog.get(conn, draft.entry_id)
            assert changelog.undo_state(conn, entry).allowed
            with conn:
                changelog.undo(conn, draft.entry_id)
        assert reserve_store.load(conn) == [] and budget_store.load(conn) == {}
        assert reserve_store.dismissed(conn) == frozenset()
        assert links.load(conn).reserve_for(fps["free"]) is None
    with closing(db.connect(path)) as again:  # idempotente
        assert again.execute("PRAGMA user_version").fetchone()[0] == 17


def test_a_failed_v17_migration_leaves_the_v16_database_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v16.db"
    _v16(path)
    with closing(sqlite3.connect(path)) as raw:
        before = _rows(raw, "links")
    monkeypatch.setattr(db, "BUDGET_SCHEMA", ("CREATE TABLE roto (",))
    with pytest.raises(sqlite3.OperationalError):
        db.connect(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 16
        assert "'reserve'" not in _sql(raw, "links")
        assert _rows(raw, "links") == before


def test_deleting_a_category_moves_its_reserves_and_drops_its_cap(tmp_path: Path) -> None:
    with closing(db.connect(tmp_path / "x.db")) as conn:
        with conn:
            mine = catalog.create(conn, "Colegio inventado", "gasto")
            other = catalog.create(conn, "Educación inventada", "gasto")
            reserve = reserve_store.create(
                conn, name="Inscripción", amount=D(9000), category_id=mine.id,
                due_month="2026-08", every_months=None,
            )  # fmt: skip
            budget_store.set_cap(conn, mine.id, D(5000))
        assert catalog.in_use(conn, mine.id)
        with pytest.raises(catalog.Forbidden):
            catalog.delete(conn, mine.id, None)
        with conn:
            catalog.delete(conn, mine.id, other.id)
        assert reserve_store.get(conn, reserve).category_id == other.id
        assert budget_store.load(conn) == {}


def test_rebuilding_links_keeps_the_sequence_of_deleted_ids(tmp_path: Path) -> None:
    """Un vínculo borrado deja la secuencia por encima del id más alto: rehacer `links` no la
    baja, así el id borrado no se reusa y su «Deshacer» viejo sigue en pie."""
    path = tmp_path / "v16.db"
    _v16(path)
    with closing(db.connect(path)) as conn:
        flow = [m for m in spending.load_all(conn) if m.kind == "gasto" and m.amount > 0]
        gone = flow[3]
        with conn, changelog.track(conn, "compartido", "transaccion", gone.fingerprint, "w"):
            links.set_shared(conn, gone.fingerprint, gone.amount, people=2)
        with conn, changelog.track(conn, "compartido", "transaccion", gone.fingerprint, "w") as d:
            links.unshare(conn, gone.fingerprint)
        deleted = d.entry_id
    with closing(sqlite3.connect(path)) as raw:
        _downgrade(raw)
        seq = raw.execute("SELECT seq FROM sqlite_sequence WHERE name = 'links'").fetchone()[0]
        top = raw.execute("SELECT MAX(id) FROM links").fetchone()[0]
        assert seq > top
    with closing(db.connect(path)) as conn:
        after = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'links'").fetchone()
        assert after[0] == seq
        assert deleted is not None
        assert changelog.undo_state(conn, changelog.get(conn, deleted)).allowed
        with conn:
            new = reserve_store.create(
                conn,
                name="Nueva",
                amount=D(100),
                category_id=catalog.resolve_ref(conn, cat.GOVERNMENT),
                due_month="2027-01",
                every_months=12,
            )
        assert new > seq
