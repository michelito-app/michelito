"""Vínculos entre movimientos: grupos compartidos (gastos y sus reembolsos) y cambios de divisas.

Un solo modelo guardado para los dos (tablas `links`, `link_members` y `link_manual`):
- Un **grupo compartido** (`kind = 'shared'`) tiene uno o más gastos (`role = 'expense'`), cada
  uno con su reparto (`people` iguales, `my_share_cents` o `for_other`: "Lo pagué por otra
  persona", en `link_members`), los créditos que los reembolsan (`role = 'reimbursement'`) y los
  reembolsos anotados a mano (`link_manual`: efectivo u otra cuenta que no se importa). El grupo
  tiene «Con quién» (`with_whom`), un nombre opcional (`name`) y "No me lo van a pagar"
  (`written_off`). Un grupo sin gastos no existe: quitar el último lo borra.
- Un **cambio de divisas** (`kind = 'exchange'`) agrupa patas (`role = 'leg'`) en dos monedas,
  con una tasa acordada opcional y si ya se dio por completo.
- Una **inversión** (`kind = 'investment'`, esquema 13) tiene aportes (`role = 'contribution'`:
  débitos), rendimientos (`'return'`: créditos que son ingreso), devoluciones de capital
  (`'capital'`: créditos que no son ingreso) y créditos mixtos (`'mixed'`: `capital_cents` de
  capital, en la moneda del crédito, y el resto rendimiento). Tiene «Con quién», un nombre
  opcional y «Dada por perdida» (`written_off`). Una inversión sin aportes no existe: quitar el
  último la borra (sus créditos quedan libres). Las cuentas están en `investments`.
- Una **caja fuerte** (`kind = 'cash_box'`, esquema 14) es una cuenta manual (`account_key`):
  sus miembros son los retiros guardados en ella (`role = 'stored'`: débitos que no son gasto) y
  los depósitos al banco que salieron de ella (`'deposit'`: créditos que no son ingreso; si sale
  de la caja en otra moneda, `box_currency` y, opcional, `box_amount_cents`). Lo anotado a mano
  en la caja va en `cash_entries` (`cash_box_store`); las cuentas, en `cash_box`.

Todo va por huella (`corrections.fingerprint`), así sobrevive a `parse --retry`. Cada huella está
a lo sumo en un vínculo (índice único): un crédito reembolsa un solo grupo, un gasto está en un
solo grupo, una pata en un solo cambio y nada es a la vez dos cosas. Una huella que ya no existe
(un estado que cambió) se ignora al calcular.

Aquí solo se lee y escribe; la cuenta de cada vínculo está en `shared`, `exchanges` e
`investments`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from functools import cached_property
from typing import TYPE_CHECKING, Literal, get_args

if TYPE_CHECKING:
    from finanzas.analysis.spending import Movement

PERSON_MAX = 80
RATE_MAX = Decimal(1_000_000)

InvestmentRole = Literal["contribution", "return", "capital", "mixed"]
INVESTMENT_ROLES: tuple[InvestmentRole, ...] = get_args(InvestmentRole)
CashBoxRole = Literal["stored", "deposit"]
CASH_BOX_ROLES: tuple[CashBoxRole, ...] = get_args(CashBoxRole)


class LinkError(ValueError):
    """Pedido inválido sobre un vínculo (422)."""


class AlreadyLinked(LinkError):
    """La huella ya está en otro vínculo (409)."""


@dataclass(frozen=True)
class ManualEntry:
    """Reembolso anotado a mano: en efectivo o en una cuenta que no se importa."""

    id: int
    amount: Decimal
    day: date
    currency: str  # la del dinero (los del esquema 11, la de su gasto: ver `db`)
    person: str = ""
    place: str = ""  # "" = efectivo


@dataclass(frozen=True)
class SharedExpense:
    """Un gasto del grupo y su reparto (exactamente una forma)."""

    fingerprint: str
    people: int | None = None  # "Éramos N"
    my_share: Decimal | None = None  # "Mi parte: RD$ X"
    for_other: bool = False  # "Lo pagué por otra persona": mi parte es 0


@dataclass(frozen=True)
class Shared:
    """Un grupo compartido: sus gastos (en el orden en que se agregaron), sus reembolsos y
    con quién."""

    id: int
    expenses: tuple[SharedExpense, ...]
    with_whom: str = ""  # «Con quién»
    name: str = ""  # opcional: «Viaje Isla Ficticia»
    written_off: bool = False  # "No me lo van a pagar"
    reimbursements: tuple[str, ...] = ()  # huellas de los créditos
    manual: tuple[ManualEntry, ...] = ()

    @classmethod
    def one(
        cls,
        id: int,  # noqa: A002
        expense: str,
        *,
        people: int | None = None,
        my_share: Decimal | None = None,
        for_other: bool = False,
        with_whom: str = "",
        name: str = "",
        written_off: bool = False,
        reimbursements: tuple[str, ...] = (),
        manual: tuple[ManualEntry, ...] = (),
    ) -> Shared:
        """Un grupo de un solo gasto (como eran todos antes del esquema 12)."""
        return cls(
            id,
            (SharedExpense(expense, people, my_share, for_other),),
            with_whom,
            name,
            written_off,
            reimbursements,
            manual,
        )

    def split(self, fingerprint: str) -> SharedExpense | None:
        return next((e for e in self.expenses if e.fingerprint == fingerprint), None)


@dataclass(frozen=True)
class Exchange:
    id: int
    legs: tuple[str, ...]  # huellas, en el orden en que se agregaron
    agreed_rate: Decimal | None = None  # RD$ por US$ acordados
    closed: bool = False  # "Cambio completo"


@dataclass(frozen=True)
class InvestmentMember:
    """Un movimiento de una inversión: su rol y, en un crédito mixto, la parte de capital."""

    fingerprint: str
    role: InvestmentRole
    capital: Decimal | None = None  # solo "mixed": capital en la moneda del crédito


@dataclass(frozen=True)
class Investment:
    """Una inversión: sus movimientos (en el orden en que se agregaron), con quién y su estado."""

    id: int
    members: tuple[InvestmentMember, ...]
    with_whom: str = ""
    name: str = ""
    written_off: bool = False  # «Dada por perdida»

    @property
    def contributions(self) -> tuple[str, ...]:
        return tuple(m.fingerprint for m in self.members if m.role == "contribution")

    def member(self, fingerprint: str) -> InvestmentMember | None:
        return next((m for m in self.members if m.fingerprint == fingerprint), None)


@dataclass(frozen=True)
class CashBoxMember:
    """Un retiro guardado en la caja o un depósito que salió de ella."""

    fingerprint: str
    role: CashBoxRole
    # Solo en un depósito que sale de la caja en otra moneda que la del crédito: esa moneda y,
    # si se dijo, cuánto salió en ella (si no, se convierte a la tasa del mes del depósito).
    box_currency: str | None = None
    box_amount: Decimal | None = None


@dataclass(frozen=True)
class CashBox:
    """Una caja fuerte: su cuenta manual y sus retiros guardados y depósitos (en el orden en que
    se agregaron)."""

    id: int
    account_key: str
    members: tuple[CashBoxMember, ...] = ()

    def member(self, fingerprint: str) -> CashBoxMember | None:
        return next((m for m in self.members if m.fingerprint == fingerprint), None)


@dataclass(frozen=True)
class Candidate:
    """Una opción de un selector de vínculos, ya ordenada: `primary` dice si va en la parte
    visible (la interfaz muestra unas pocas y deja el resto tras «Ver más»)."""

    move: Movement
    primary: bool


@dataclass(frozen=True)
class Links:
    shared: tuple[Shared, ...] = ()
    exchanges: tuple[Exchange, ...] = field(default_factory=tuple)
    investments: tuple[Investment, ...] = ()
    cash_boxes: tuple[CashBox, ...] = ()
    # Gastos vinculados a una reserva (esquema 17): huella -> id de la reserva. El vínculo no
    # cambia su categoría (ver `reserve_store`).
    reserved: Mapping[str, int] = field(default_factory=dict)

    @cached_property
    def _by_expense(self) -> dict[str, Shared]:
        return {e.fingerprint: s for s in self.shared for e in s.expenses}

    @cached_property
    def _by_credit(self) -> dict[str, Shared]:
        return {credit: s for s in self.shared for credit in s.reimbursements}

    @cached_property
    def _by_leg(self) -> dict[str, Exchange]:
        return {leg: e for e in self.exchanges for leg in e.legs}

    def shared_for(self, fingerprint: str) -> Shared | None:
        """El grupo compartido que tiene este gasto."""
        return self._by_expense.get(fingerprint)

    def reimbursed(self, fingerprint: str) -> Shared | None:
        """El grupo compartido que reembolsa este crédito."""
        return self._by_credit.get(fingerprint)

    def group(self, link_id: int) -> Shared | None:
        return next((s for s in self.shared if s.id == link_id), None)

    @cached_property
    def _by_investment(self) -> dict[str, Investment]:
        return {m.fingerprint: i for i in self.investments for m in i.members}

    def investment_for(self, fingerprint: str) -> Investment | None:
        """La inversión que tiene este movimiento (como aporte o como crédito)."""
        return self._by_investment.get(fingerprint)

    def investment(self, investment_id: int) -> Investment | None:
        return next((i for i in self.investments if i.id == investment_id), None)

    @cached_property
    def _by_cash_box(self) -> dict[str, CashBox]:
        return {m.fingerprint: box for box in self.cash_boxes for m in box.members}

    def cash_box_for(self, fingerprint: str) -> CashBox | None:
        """La caja de este retiro guardado o depósito."""
        return self._by_cash_box.get(fingerprint)

    def exchange_for(self, fingerprint: str) -> Exchange | None:
        return self._by_leg.get(fingerprint)

    def exchange(self, exchange_id: int) -> Exchange | None:
        return next((e for e in self.exchanges if e.id == exchange_id), None)

    def is_linked(self, fingerprint: str) -> bool:
        return (
            fingerprint in self._by_expense
            or fingerprint in self._by_credit
            or fingerprint in self._by_leg
            or fingerprint in self._by_investment
            or fingerprint in self._by_cash_box
            or fingerprint in self.reserved
        )

    @cached_property
    def fingerprints(self) -> frozenset[str]:
        """Todas las huellas que están en algún vínculo."""
        return frozenset(
            (
                *self._by_expense,
                *self._by_credit,
                *self._by_leg,
                *self._by_investment,
                *self._by_cash_box,
                *self.reserved,
            )
        )

    def reserve_for(self, fingerprint: str) -> int | None:
        """La reserva que cubre este gasto."""
        return self.reserved.get(fingerprint)


NONE = Links()


def load(conn: sqlite3.Connection) -> Links:
    members: dict[int, list[sqlite3.Row]] = {}
    for row in conn.execute("SELECT * FROM link_members ORDER BY added_at, rowid"):
        members.setdefault(row["link_id"], []).append(row)
    manual: dict[int, list[ManualEntry]] = {}
    for row in conn.execute("SELECT * FROM link_manual ORDER BY day, id"):
        manual.setdefault(row["link_id"], []).append(
            ManualEntry(
                id=row["id"],
                amount=Decimal(row["amount_cents"]) / 100,
                day=date.fromisoformat(row["day"]),
                person=row["person"] or "",
                place=row["place"] or "",
                currency=row["currency"],
            )
        )
    shared: list[Shared] = []
    exchanges: list[Exchange] = []
    investments: list[Investment] = []
    boxes: list[CashBox] = []
    reserved: dict[str, int] = {}
    for row in conn.execute("SELECT * FROM links ORDER BY id"):
        rows = members.get(row["id"], [])
        if row["kind"] == "reserve":
            reserved.update((m["fingerprint"], int(row["id"])) for m in rows)
            continue
        if row["kind"] == "cash_box":
            boxes.append(_cash_box(row, rows))
            continue
        if row["kind"] == "exchange":
            exchanges.append(_exchange(row, rows))
            continue
        if row["kind"] == "investment":
            found = _investment(row, rows)
            if found.contributions:
                investments.append(found)
            continue
        expenses = tuple(_split(m) for m in rows if m["role"] == "expense")
        if not expenses:
            continue
        shared.append(
            Shared(
                id=row["id"],
                expenses=expenses,
                with_whom=row["with_whom"] or "",
                name=row["name"] or "",
                written_off=bool(row["written_off"]),
                reimbursements=tuple(
                    m["fingerprint"] for m in rows if m["role"] == "reimbursement"
                ),
                manual=tuple(manual.get(row["id"], ())),
            )
        )
    return Links(tuple(shared), tuple(exchanges), tuple(investments), tuple(boxes), reserved)


def _cash_box(row: sqlite3.Row, members: Iterable[sqlite3.Row]) -> CashBox:
    found = []
    for m in members:
        if m["role"] not in CASH_BOX_ROLES:
            continue
        cents = m["box_amount_cents"]
        found.append(
            CashBoxMember(
                fingerprint=m["fingerprint"],
                role=m["role"],
                box_currency=m["box_currency"],
                box_amount=None if cents is None else Decimal(cents) / 100,
            )
        )
    return CashBox(id=row["id"], account_key=row["account_key"] or "", members=tuple(found))


def _investment(row: sqlite3.Row, members: Iterable[sqlite3.Row]) -> Investment:
    found = []
    for m in members:
        if m["role"] not in INVESTMENT_ROLES:
            continue
        cents = m["capital_cents"]
        capital = None if cents is None or m["role"] != "mixed" else Decimal(cents) / 100
        found.append(InvestmentMember(m["fingerprint"], m["role"], capital))
    return Investment(
        id=row["id"],
        members=tuple(found),
        with_whom=row["with_whom"] or "",
        name=row["name"] or "",
        written_off=bool(row["written_off"]),
    )


def _split(row: sqlite3.Row) -> SharedExpense:
    cents = row["my_share_cents"]
    return SharedExpense(
        fingerprint=row["fingerprint"],
        people=row["people"],
        my_share=None if cents is None else Decimal(cents) / 100,
        for_other=bool(row["for_other"]),
    )


def _exchange(row: sqlite3.Row, members: Iterable[sqlite3.Row]) -> Exchange:
    return Exchange(
        id=row["id"],
        legs=tuple(m["fingerprint"] for m in members if m["role"] == "leg"),
        agreed_rate=None if row["agreed_rate"] is None else Decimal(row["agreed_rate"]),
        closed=bool(row["closed"]),
    )


# --- Grupos compartidos -------------------------------------------------------------------


def set_shared(
    conn: sqlite3.Connection,
    expense: str,
    amount: Decimal,
    *,
    people: int | None = None,
    my_share: Decimal | None = None,
    for_other: bool = False,
    with_whom: str | None = None,
) -> int:
    """Marca (o cambia) el reparto de un gasto; exactamente una de las tres formas.

    Si el gasto ya está en un grupo, cambia su reparto (el grupo y sus reembolsos quedan); si
    no, crea un grupo nuevo con él (`with_whom`: «Con quién», opcional). `amount`: el monto del
    gasto (positivo), para validar mi parte (0 < X <= monto). Devuelve el id del grupo.
    """
    _check_split(amount, people, my_share, for_other)
    current = _shared_id(conn, expense)
    if current is not None:
        conn.execute(
            "UPDATE link_members SET people = ?, my_share_cents = ?, for_other = ? "
            "WHERE link_id = ? AND fingerprint = ? AND role = 'expense'",
            (people, _share_cents(my_share), int(for_other), current, expense),
        )
        _touch(conn, current)
        return current
    if _link_of(conn, expense) is not None:
        raise AlreadyLinked("la transacción ya está en otro vínculo")
    now = _now()
    cursor = conn.execute(
        "INSERT INTO links (kind, with_whom, created_at, updated_at) VALUES ('shared', ?, ?, ?)",
        (_text(with_whom, "con quién"), now, now),
    )
    found = int(cursor.lastrowid or 0)
    _insert_expense(conn, found, expense, people, my_share, for_other)
    return found


def add_expense(
    conn: sqlite3.Connection,
    link_id: int,
    expense: str,
    amount: Decimal,
    *,
    people: int | None = None,
    my_share: Decimal | None = None,
    for_other: bool = False,
) -> None:
    """Suma un gasto (con su reparto) a un grupo que ya existe."""
    _require_group(conn, link_id)
    _check_split(amount, people, my_share, for_other)
    if _link_of(conn, expense) is not None:
        raise AlreadyLinked("la transacción ya está en otro vínculo")
    _insert_expense(conn, link_id, expense, people, my_share, for_other)
    _touch(conn, link_id)


def _insert_expense(
    conn: sqlite3.Connection,
    link_id: int,
    expense: str,
    people: int | None,
    my_share: Decimal | None,
    for_other: bool,
) -> None:
    conn.execute(
        "INSERT INTO link_members (link_id, fingerprint, role, added_at, people, "
        "my_share_cents, for_other) VALUES (?, ?, 'expense', ?, ?, ?, ?)",
        (link_id, expense, _now(), people, _share_cents(my_share), int(for_other)),
    )


def _share_cents(my_share: Decimal | None) -> int | None:
    return None if my_share is None else _to_cents(my_share)


def _check_split(
    amount: Decimal, people: int | None, my_share: Decimal | None, for_other: bool
) -> None:
    if amount <= 0:
        raise LinkError("solo un gasto (monto positivo) se puede compartir")
    given = sum((people is not None, my_share is not None, for_other))
    if given != 1:
        raise LinkError("elige una forma de repartir: «Éramos N», «Mi parte» u «otra persona»")
    if people is not None and not 2 <= people <= 100:
        raise LinkError("«Éramos N» va de 2 a 100 personas")
    if my_share is not None and not 0 < my_share <= amount:
        raise LinkError("tu parte tiene que ser mayor que 0 y no más que el gasto")


def unshare(conn: sqlite3.Connection, expense: str) -> bool:
    """Quita el gasto de su grupo; los reembolsos se quedan en el grupo. Si era el último
    gasto, borra el grupo: sus créditos vuelven a su categoría y los anotados a mano se borran.
    Devuelve si borró el grupo."""
    found = _shared_id(conn, expense)
    if found is None:
        return False
    conn.execute(
        "DELETE FROM link_members WHERE link_id = ? AND fingerprint = ? AND role = 'expense'",
        (found, expense),
    )
    left = conn.execute(
        "SELECT COUNT(*) FROM link_members WHERE link_id = ? AND role = 'expense'", (found,)
    ).fetchone()[0]
    if left == 0:
        conn.execute("DELETE FROM links WHERE id = ?", (found,))
        return True
    _touch(conn, found)
    return False


def set_group(
    conn: sqlite3.Connection,
    link_id: int,
    *,
    name: str | None | object = ...,
    with_whom: str | None | object = ...,
) -> None:
    """Nombre y «Con quién» del grupo: ausente (`...`) no lo toca; vacío o None lo borra."""
    _require_group(conn, link_id)
    if name is not ...:
        text = _text(name if isinstance(name, str) else None, "nombre")
        conn.execute("UPDATE links SET name = ? WHERE id = ?", (text, link_id))
    if with_whom is not ...:
        text = _text(with_whom if isinstance(with_whom, str) else None, "con quién")
        conn.execute("UPDATE links SET with_whom = ? WHERE id = ?", (text, link_id))
    _touch(conn, link_id)


def set_written_off(conn: sqlite3.Connection, link_id: int, written_off: bool) -> None:
    _require_group(conn, link_id)
    conn.execute(
        "UPDATE links SET written_off = ?, updated_at = ? WHERE id = ?",
        (int(written_off), _now(), link_id),
    )


def add_reimbursement(conn: sqlite3.Connection, link_id: int, credit: str) -> None:
    _require_group(conn, link_id)
    if _link_of(conn, credit) is not None:
        raise AlreadyLinked("ese crédito ya está enlazado")
    conn.execute(
        "INSERT INTO link_members (link_id, fingerprint, role, added_at) "
        "VALUES (?, ?, 'reimbursement', ?)",
        (link_id, credit, _now()),
    )


def remove_reimbursement(conn: sqlite3.Connection, link_id: int, credit: str) -> None:
    _require_group(conn, link_id)
    cursor = conn.execute(
        "DELETE FROM link_members WHERE link_id = ? AND fingerprint = ? AND role = 'reimbursement'",
        (link_id, credit),
    )
    if cursor.rowcount == 0:
        raise LookupError("ese crédito no es un reembolso del grupo")


def add_manual(
    conn: sqlite3.Connection,
    link_id: int,
    amount: Decimal,
    day: date,
    currency: str,
    person: str | None = None,
    place: str | None = None,
) -> int:
    """Reembolso en efectivo (`place` vacío) o en otra cuenta (`place`: dónde), en `currency`
    (siempre se guarda: si después se suma un gasto en otra moneda, no cambia)."""
    _require_group(conn, link_id)
    if amount <= 0:
        raise LinkError("el monto tiene que ser mayor que 0")
    if currency not in ("DOP", "USD"):
        raise LinkError("la moneda es RD$ o US$")
    cursor = conn.execute(
        "INSERT INTO link_manual (link_id, amount_cents, day, person, place, currency, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            link_id,
            _to_cents(amount),
            day.isoformat(),
            _text(person, "de quién"),
            _place(place),
            currency,
            _now(),
        ),
    )
    return int(cursor.lastrowid or 0)


def remove_manual(conn: sqlite3.Connection, link_id: int, entry_id: int) -> None:
    _require_group(conn, link_id)
    cursor = conn.execute(
        "DELETE FROM link_manual WHERE id = ? AND link_id = ?", (entry_id, link_id)
    )
    if cursor.rowcount == 0:
        raise LookupError("ese reembolso a mano no es del grupo")


def places(conn: sqlite3.Connection) -> list[str]:
    """Dónde se anotaron reembolsos antes (sin efectivo), el más reciente primero."""
    rows = conn.execute(
        "SELECT place, MAX(created_at) AS last FROM link_manual WHERE place IS NOT NULL "
        "GROUP BY place ORDER BY last DESC, place"
    )
    return [row["place"] for row in rows]


def _place(place: str | None) -> str | None:
    text = _text(place, "dónde")
    return None if text is None or text.casefold() == "efectivo" else text


# --- Cambios de divisas -------------------------------------------------------------------


def create_exchange(
    conn: sqlite3.Connection, legs: Iterable[str], agreed_rate: Decimal | None = None
) -> int:
    """Nuevo cambio con estas patas (quien llama valida monedas y direcciones)."""
    chosen = list(dict.fromkeys(legs))
    if len(chosen) < 2:
        raise LinkError("un cambio necesita al menos una pata en cada moneda")
    for leg in chosen:
        if _link_of(conn, leg) is not None:
            raise AlreadyLinked("una de las transacciones ya está en otro vínculo")
    now = _now()
    cursor = conn.execute(
        "INSERT INTO links (kind, agreed_rate, created_at, updated_at) "
        "VALUES ('exchange', ?, ?, ?)",
        (_rate_text(agreed_rate), now, now),
    )
    found = int(cursor.lastrowid or 0)
    _insert_legs(conn, found, chosen, now)
    return found


def add_legs(conn: sqlite3.Connection, exchange_id: int, legs: Iterable[str]) -> None:
    _require_exchange(conn, exchange_id)
    chosen = list(dict.fromkeys(legs))
    for leg in chosen:
        if _link_of(conn, leg) is not None:
            raise AlreadyLinked("una de las transacciones ya está en otro vínculo")
    _insert_legs(conn, exchange_id, chosen, _now())


def _insert_legs(conn: sqlite3.Connection, exchange_id: int, legs: list[str], now: str) -> None:
    conn.executemany(
        "INSERT INTO link_members (link_id, fingerprint, role, added_at) VALUES (?, ?, 'leg', ?)",
        [(exchange_id, leg, now) for leg in legs],
    )


def remove_leg(conn: sqlite3.Connection, exchange_id: int, leg: str) -> None:
    _require_exchange(conn, exchange_id)
    conn.execute(
        "DELETE FROM link_members WHERE link_id = ? AND fingerprint = ?", (exchange_id, leg)
    )


def update_exchange(
    conn: sqlite3.Connection,
    exchange_id: int,
    *,
    agreed_rate: Decimal | None | object = ...,
    closed: bool | None = None,
) -> None:
    """`agreed_rate`: ausente (`...`) no la toca; `None` vuelve a la tasa implícita."""
    _require_exchange(conn, exchange_id)
    if agreed_rate is not ...:
        rate = agreed_rate if isinstance(agreed_rate, Decimal) else None
        conn.execute(
            "UPDATE links SET agreed_rate = ? WHERE id = ?", (_rate_text(rate), exchange_id)
        )
    if closed is not None:
        conn.execute("UPDATE links SET closed = ? WHERE id = ?", (int(closed), exchange_id))
    conn.execute("UPDATE links SET updated_at = ? WHERE id = ?", (_now(), exchange_id))


def delete_exchange(conn: sqlite3.Connection, exchange_id: int) -> None:
    conn.execute("DELETE FROM links WHERE id = ? AND kind = 'exchange'", (exchange_id,))


def _rate_text(rate: Decimal | None) -> str | None:
    if rate is None:
        return None
    if not rate.is_finite() or not 0 < rate < RATE_MAX:
        raise LinkError("la tasa tiene que ser mayor que 0")
    return str(rate.quantize(Decimal("0.0001")))


# --- Inversiones -----------------------------------------------------------------------------


def create_investment(
    conn: sqlite3.Connection,
    contribution: str,
    *,
    with_whom: str | None = None,
    name: str | None = None,
) -> int:
    """Nueva inversión con este aporte (quien llama valida que sea un débito)."""
    if _link_of(conn, contribution) is not None:
        raise AlreadyLinked("la transacción ya está en otro vínculo")
    with_text, name_text = _text(with_whom, "con quién"), _text(name, "nombre")
    now = _now()
    cursor = conn.execute(
        "INSERT INTO links (kind, with_whom, name, created_at, updated_at) "
        "VALUES ('investment', ?, ?, ?, ?)",
        (with_text, name_text, now, now),
    )
    found = int(cursor.lastrowid or 0)
    _insert_member(conn, found, contribution, "contribution", None)
    return found


def add_investment_member(
    conn: sqlite3.Connection,
    investment_id: int,
    fingerprint: str,
    role: InvestmentRole,
    amount: Decimal,
    capital: Decimal | None = None,
) -> None:
    """Suma un aporte o un crédito a la inversión. `amount`: el monto del movimiento (positivo),
    para validar la parte de capital de un mixto (0 < capital < monto)."""
    _require_investment(conn, investment_id)
    _check_role(role, amount, capital)
    if _link_of(conn, fingerprint) is not None:
        raise AlreadyLinked("la transacción ya está en otro vínculo")
    _insert_member(conn, investment_id, fingerprint, role, capital)
    _touch(conn, investment_id)


def set_investment_role(
    conn: sqlite3.Connection,
    investment_id: int,
    fingerprint: str,
    role: InvestmentRole,
    amount: Decimal,
    capital: Decimal | None = None,
) -> None:
    """Cambia el tipo de un crédito de la inversión (rendimiento, capital o mixto)."""
    _require_investment(conn, investment_id)
    if role == "contribution":
        raise LinkError("un crédito no puede ser un aporte")
    _check_role(role, amount, capital)
    cursor = conn.execute(
        "UPDATE link_members SET role = ?, capital_cents = ? WHERE link_id = ? "
        "AND fingerprint = ? AND role IN ('return', 'capital', 'mixed')",
        (role, _capital_cents(role, capital), investment_id, fingerprint),
    )
    if cursor.rowcount == 0:
        raise LookupError("ese crédito no es de la inversión")
    _touch(conn, investment_id)


def remove_investment_member(
    conn: sqlite3.Connection, investment_id: int, fingerprint: str
) -> bool:
    """Quita el movimiento de la inversión. Si era el último aporte, borra la inversión (sus
    créditos vuelven a su categoría). Devuelve si la borró."""
    _require_investment(conn, investment_id)
    cursor = conn.execute(
        "DELETE FROM link_members WHERE link_id = ? AND fingerprint = ?",
        (investment_id, fingerprint),
    )
    if cursor.rowcount == 0:
        raise LookupError("ese movimiento no es de la inversión")
    left = conn.execute(
        "SELECT COUNT(*) FROM link_members WHERE link_id = ? AND role = 'contribution'",
        (investment_id,),
    ).fetchone()[0]
    if left == 0:
        conn.execute("DELETE FROM links WHERE id = ?", (investment_id,))
        return True
    _touch(conn, investment_id)
    return False


def set_investment(
    conn: sqlite3.Connection,
    investment_id: int,
    *,
    name: str | None | object = ...,
    with_whom: str | None | object = ...,
    written_off: bool | None = None,
) -> None:
    """Nombre, «Con quién» y «Dada por perdida»: ausente (`...`, o None en `written_off`) no
    lo toca; un texto vacío o None lo borra."""
    _require_investment(conn, investment_id)
    if name is not ...:
        text = _text(name if isinstance(name, str) else None, "nombre")
        conn.execute("UPDATE links SET name = ? WHERE id = ?", (text, investment_id))
    if with_whom is not ...:
        text = _text(with_whom if isinstance(with_whom, str) else None, "con quién")
        conn.execute("UPDATE links SET with_whom = ? WHERE id = ?", (text, investment_id))
    if written_off is not None:
        conn.execute(
            "UPDATE links SET written_off = ? WHERE id = ?", (int(written_off), investment_id)
        )
    _touch(conn, investment_id)


def _check_role(role: str, amount: Decimal, capital: Decimal | None) -> None:
    if role not in INVESTMENT_ROLES:
        raise LinkError(f"tipo desconocido: {role}")
    if amount <= 0:
        raise LinkError("el monto tiene que ser mayor que 0")
    if role != "mixed":
        if capital is not None:
            raise LinkError("solo un crédito mixto lleva una parte de capital")
        return
    if capital is None or not 0 < capital < amount:
        raise LinkError("la parte de capital tiene que ser mayor que 0 y menor que el crédito")


def _capital_cents(role: str, capital: Decimal | None) -> int | None:
    return _to_cents(capital) if role == "mixed" and capital is not None else None


def _insert_member(
    conn: sqlite3.Connection,
    investment_id: int,
    fingerprint: str,
    role: InvestmentRole,
    capital: Decimal | None,
) -> None:
    conn.execute(
        "INSERT INTO link_members (link_id, fingerprint, role, added_at, capital_cents) "
        "VALUES (?, ?, ?, ?, ?)",
        (investment_id, fingerprint, role, _now(), _capital_cents(role, capital)),
    )


def _require_investment(conn: sqlite3.Connection, investment_id: int) -> None:
    row = conn.execute(
        "SELECT 1 FROM links WHERE id = ? AND kind = 'investment'", (investment_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"inversión desconocida: {investment_id}")


# --- Ayudas ---------------------------------------------------------------------------------


def _link_of(conn: sqlite3.Connection, fingerprint: str) -> int | None:
    row = conn.execute(
        "SELECT link_id FROM link_members WHERE fingerprint = ?", (fingerprint,)
    ).fetchone()
    return None if row is None else int(row[0])


def _shared_id(conn: sqlite3.Connection, expense: str) -> int | None:
    row = conn.execute(
        "SELECT link_id FROM link_members WHERE fingerprint = ? AND role = 'expense'", (expense,)
    ).fetchone()
    return None if row is None else int(row[0])


def group_of(conn: sqlite3.Connection, expense: str) -> int:
    """El grupo de este gasto; LinkError si no está compartido."""
    found = _shared_id(conn, expense)
    if found is None:
        raise LinkError("la transacción no está marcada como compartida")
    return found


def _require_group(conn: sqlite3.Connection, link_id: int) -> None:
    row = conn.execute(
        "SELECT 1 FROM links WHERE id = ? AND kind = 'shared'", (link_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"grupo desconocido: {link_id}")


def _touch(conn: sqlite3.Connection, link_id: int) -> None:
    conn.execute("UPDATE links SET updated_at = ? WHERE id = ?", (_now(), link_id))


def _require_exchange(conn: sqlite3.Connection, exchange_id: int) -> None:
    row = conn.execute(
        "SELECT 1 FROM links WHERE id = ? AND kind = 'exchange'", (exchange_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"cambio desconocido: {exchange_id}")


def _to_cents(amount: Decimal) -> int:
    try:
        scaled = amount * 100
        if scaled != scaled.to_integral_value():
            raise LinkError("el monto tiene más de dos decimales")
    except InvalidOperation:
        raise LinkError("monto inválido") from None
    return int(scaled)


def _text(value: str | None, what: str) -> str | None:
    text = " ".join((value or "").split())
    if len(text) > PERSON_MAX:
        raise LinkError(f"«{what}» tiene más de {PERSON_MAX} letras")
    return text or None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")
