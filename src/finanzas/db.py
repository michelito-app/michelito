"""Esquema SQLite y escritura de estados ya validados.

Los montos se guardan en centavos (enteros) para que las sumas sean exactas.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

from finanzas.analysis import catalog
from finanzas.parsers import banreservas_cuenta, bhd_ahorro, popular_web
from finanzas.parsers.common import Section, Statement, Transaction

SCHEMA_VERSION = 17
DUPLICATE_PERIOD_INDEX = "statements_unique_period"
DUPLICATE_PRINTOUT_INDEX = "statements_unique_printout"
# Parser de las impresiones del Popular: la moneda de la cuenta se indica a mano (ingest).
PRINTOUT_PARSER = popular_web.NAME
# Lo que no es un estado oficial sino una impresión: cubre su rango y cede ante los estados
# (ver analysis.coverage). El mes en curso de Banreservas y el de ahorro de BHD (portal)
# también lo son.
PRINTOUT_PARSERS: tuple[str, ...] = (
    PRINTOUT_PARSER,
    banreservas_cuenta.PARTIAL_NAME,
    bhd_ahorro.PARTIAL_NAME,
)
_PRINTOUT_LIST = ", ".join(f"'{name}'" for name in PRINTOUT_PARSERS)

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    institution TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    last4 TEXT NOT NULL,
    product TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE (account_id, last4)
);
CREATE TABLE IF NOT EXISTS gmail_messages (
    message_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    received_at TEXT NOT NULL,
    attachments_saved INTEGER NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES gmail_messages(message_id),
    source TEXT NOT NULL,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    received_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'parsed', 'invalid', 'error', 'unsupported', 'archived', 'duplicate'
    )),
    parser TEXT,
    detail TEXT,
    processed_at TEXT,
    UNIQUE (message_id, filename)
);
CREATE INDEX IF NOT EXISTS documents_sha256 ON documents(sha256);
-- Un PDF con varios estados seguidos (parsers con `split`, ver ingest): el resultado de cada
-- tramo, en el orden del PDF. `label` es el corte del tramo (AAAA-MM-DD) o, si no se pudo
-- interpretar, "estado N". `note` es una diferencia que no invalida el tramo (la cantidad
-- de filas del resumen no coincide). Se reescribe cada vez que se interpreta el documento.
CREATE TABLE IF NOT EXISTS document_parts (
    document_id INTEGER NOT NULL REFERENCES documents(id),
    part INTEGER NOT NULL CHECK (part >= 1),
    label TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('parsed', 'invalid', 'error', 'duplicate')),
    detail TEXT,
    note TEXT,
    PRIMARY KEY (document_id, part)
);
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    card_id INTEGER REFERENCES cards(id),
    parser TEXT NOT NULL,
    product TEXT NOT NULL,
    currency TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT NOT NULL,
    due_date TEXT,
    previous_balance_cents INTEGER,
    closing_balance_cents INTEGER,
    minimum_payment_cents INTEGER,
    credit_limit_cents INTEGER,
    printed_debits_cents INTEGER,
    printed_credits_cents INTEGER,
    transaction_count INTEGER
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES statements(id),
    sequence INTEGER NOT NULL,
    transacted_on TEXT NOT NULL,
    posted_on TEXT,
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    direction TEXT NOT NULL CHECK (direction IN ('debit', 'credit')),
    currency TEXT NOT NULL,
    reference TEXT,
    mcc TEXT,
    raw_line TEXT NOT NULL,
    UNIQUE (statement_id, sequence)
);
-- Categorías: las del sistema (`builtin_key`, sembradas de analysis/categories.py) y las
-- del usuario. Las correcciones y palabras clave guardan el id: renombrar no las toca.
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind TEXT NOT NULL CHECK (kind IN ('ingreso', 'gasto', 'transferencia')),
    color TEXT CHECK (color IS NULL OR (length(color) = 7 AND color GLOB '#*'
        AND NOT substr(color, 2) GLOB '*[^0-9A-Fa-f]*')),
    hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
    builtin INTEGER NOT NULL DEFAULT 0 CHECK (builtin IN (0, 1)),
    builtin_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    CHECK ((builtin = 1) = (builtin_key IS NOT NULL))
);
-- Palabras clave del usuario, normalizadas como las descripciones (`categories.clean`).
CREATE TABLE IF NOT EXISTS category_keywords (
    category_id INTEGER NOT NULL REFERENCES categories(id),
    keyword TEXT NOT NULL,
    PRIMARY KEY (category_id, keyword)
);
-- Correcciones hechas a mano. Van aparte de `transactions` porque esas filas se
-- recrean al reprocesar un estado; aquí se identifican por comercio o por huella.
CREATE TABLE IF NOT EXISTS merchant_categories (
    merchant TEXT PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transaction_notes (
    fingerprint TEXT PRIMARY KEY,
    category_id INTEGER REFERENCES categories(id),
    one_off INTEGER NOT NULL DEFAULT 0 CHECK (one_off IN (0, 1)),
    updated_at TEXT NOT NULL,
    note TEXT CHECK (note IS NULL OR length(note) <= 500)
);
-- Pesos por dólar, un valor por mes (YYYY-MM). La tabla del BCRD no pisa los manuales.
CREATE TABLE IF NOT EXISTS exchange_rates (
    month TEXT PRIMARY KEY,
    dop_per_usd TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('bcrd', 'manual')),
    updated_at TEXT NOT NULL
);
-- Marcas del usuario sobre cargos recurrentes (por comercio y moneda). `status_on` es la
-- fecha desde la que se cuentan cobros tras cancelar; `installments_on`, la de las cuotas.
CREATE TABLE IF NOT EXISTS recurring_marks (
    merchant TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT CHECK (status IN ('confirmed', 'dismissed', 'cancelled')),
    installments_left INTEGER CHECK (installments_left IS NULL OR installments_left >= 0),
    status_on TEXT,
    installments_on TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (merchant, currency)
);
-- Moneda de una cuenta según quien importa sus impresiones del portal (`importar
-- --moneda`), que imprimen "$" a secas también en dólares. Va por la clave de la cuenta
-- (`accounts.key`, la misma del estado oficial) y aparte de `accounts`: es una indicación
-- para interpretar impresiones, no un dato de la cuenta, y se consulta antes de guardar.
CREATE TABLE IF NOT EXISTS account_currency (
    account_key TEXT PRIMARY KEY,
    currency TEXT NOT NULL CHECK (currency IN ('DOP', 'USD')),
    updated_at TEXT NOT NULL
);
-- Sugerencias de gasto único descartadas a mano ("No es único"), por huella.
CREATE TABLE IF NOT EXISTS one_off_dismissals (
    fingerprint TEXT PRIMARY KEY,
    updated_at TEXT NOT NULL
);
"""

# Vínculos entre movimientos (esquema 9; ver `analysis.links`): un gasto compartido con sus
# reembolsos o un cambio de divisas con sus patas. Van por huella, como las correcciones, así
# sobreviven a `parse --retry`. Cada huella está a lo sumo en un vínculo (`fingerprint UNIQUE`).
# Se crean en la migración, en una transacción. Desde el esquema 12 (`GROUP_COLUMNS`) un grupo
# compartido tiene varios gastos y el reparto va en cada uno: `people`, `my_share_cents`,
# `for_other` y `for_whom` de `links` quedan de legado (no se leen). El esquema 13 suma las
# inversiones (`LINK_KINDS`, `LINK_ROLES` y `INVESTMENT_COLUMNS`) y el 14 la caja fuerte
# (`'cash_box'`, sus roles `'stored'` y `'deposit'`, `CASH_BOX_COLUMNS` y `CASH_SCHEMA`). El 17
# suma las reservas (`'reserve'`, su rol `'reserved'` y `RESERVE_COLUMNS`).
LINK_KINDS = ("shared", "exchange", "investment", "cash_box", "reserve")
LINK_ROLES = (
    "expense",
    "reimbursement",
    "leg",
    "contribution",
    "return",
    "capital",
    "mixed",
    "stored",
    "deposit",
    "reserved",
)
_LINK_KIND_CHECK = "CHECK (kind IN ({}))".format(", ".join(f"'{k}'" for k in LINK_KINDS))
_LINK_ROLE_CHECK = "CHECK (role IN ({}))".format(", ".join(f"'{r}'" for r in LINK_ROLES))
LINK_SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL {_LINK_KIND_CHECK},
    people INTEGER CHECK (people IS NULL OR people >= 2),
    my_share_cents INTEGER CHECK (my_share_cents IS NULL OR my_share_cents >= 0),
    for_other INTEGER NOT NULL DEFAULT 0 CHECK (for_other IN (0, 1)),
    for_whom TEXT CHECK (for_whom IS NULL OR length(for_whom) <= 80),
    written_off INTEGER NOT NULL DEFAULT 0 CHECK (written_off IN (0, 1)),
    agreed_rate TEXT,
    closed INTEGER NOT NULL DEFAULT 0 CHECK (closed IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
    f"""CREATE TABLE IF NOT EXISTS link_members (
    link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL {_LINK_ROLE_CHECK},
    added_at TEXT NOT NULL,
    PRIMARY KEY (link_id, fingerprint)
)""",
    """CREATE TABLE IF NOT EXISTS link_manual (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    day TEXT NOT NULL,
    person TEXT CHECK (person IS NULL OR length(person) <= 80),
    place TEXT CHECK (place IS NULL OR length(place) <= 80),
    created_at TEXT NOT NULL
)""",
)

# Grupos compartidos (esquema 12): columnas nuevas por tabla. El reparto pasa de `links` a cada
# gasto (`link_members` con `role = 'expense'`); el grupo tiene nombre y «Con quién»; un
# reembolso a mano dice su moneda (NULL: la del gasto más antiguo del grupo, como antes).
GROUP_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "links": (
        ("name", "TEXT CHECK (name IS NULL OR length(name) <= 80)"),
        ("with_whom", "TEXT CHECK (with_whom IS NULL OR length(with_whom) <= 80)"),
    ),
    "link_members": (
        ("people", "INTEGER CHECK (people IS NULL OR people >= 2)"),
        ("my_share_cents", "INTEGER CHECK (my_share_cents IS NULL OR my_share_cents >= 0)"),
        ("for_other", "INTEGER NOT NULL DEFAULT 0 CHECK (for_other IN (0, 1))"),
    ),
    "link_manual": (("currency", "TEXT CHECK (currency IS NULL OR currency IN ('DOP', 'USD'))"),),
}

# Inversiones (esquema 13; ver `analysis.investments`): la parte de capital de un crédito mixto,
# en centavos de la moneda del crédito.
INVESTMENT_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "link_members": (
        ("capital_cents", "INTEGER CHECK (capital_cents IS NULL OR capital_cents > 0)"),
    ),
}

# Caja fuerte (esquema 14; ver `analysis.cash_box`). Un vínculo `'cash_box'` por caja, con la
# clave de su cuenta (`accounts.key`, como `account_currency`): sus miembros son los retiros
# guardados (`'stored'`) y los depósitos que salieron de ella (`'deposit'`). Un depósito en otra
# moneda que la que sale de la caja guarda esa moneda y, si se dijo, cuánto salió en ella.
CASH_BOX_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "links": (("account_key", "TEXT CHECK (account_key IS NULL OR length(account_key) <= 80)"),),
    "link_members": (
        ("box_currency", "TEXT CHECK (box_currency IS NULL OR box_currency IN ('DOP', 'USD'))"),
        ("box_amount_cents", "INTEGER CHECK (box_amount_cents IS NULL OR box_amount_cents > 0)"),
    ),
}
# Los movimientos anotados a mano en la caja: saldo inicial (`initial`, no es ingreso), entrada
# (`income`, ingreso) y salida (`expense`, gasto). Su huella es `caja-<id>` (`AUTOINCREMENT`: un
# id borrado no se reusa, así su nota o su vínculo nunca pasan a otro); su categoría, su nota y
# «gasto único» van en `transaction_notes` por esa huella, como los de un estado.
CASH_ENTRY_KINDS = ("initial", "income", "expense")
_CASH_KIND_LIST = ", ".join(f"'{kind}'" for kind in CASH_ENTRY_KINDS)
CASH_SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS cash_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_key TEXT NOT NULL CHECK (length(account_key) <= 80),
    kind TEXT NOT NULL CHECK (kind IN ({_CASH_KIND_LIST})),
    day TEXT NOT NULL CHECK (length(day) = 10),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL CHECK (currency IN ('DOP', 'USD')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
)

# «Para revisar» (esquema 10; ver `analysis.review`): lo marcado "Ya lo revisé", por huella y
# tipo, para que sobreviva a `parse --retry`. Los gastos únicos usan `one_off_dismissals`.
REVIEW_MARK_KINDS = (
    "ingreso_inusual",
    "tercero_grande",
    "duplicado",
    "subio",
    "aporte_posible",
    "cobro_posible",
    "reserva_posible",
)
_REVIEW_KIND_LIST = ", ".join(f"'{kind}'" for kind in REVIEW_MARK_KINDS)
REVIEW_SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS review_marks (
    fingerprint TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ({_REVIEW_KIND_LIST})),
    reviewed_at TEXT NOT NULL,
    PRIMARY KEY (fingerprint, kind)
)""",
)

# Análisis del mes (esquema 11; ver `analysis.insights`): un texto por mes, con la huella de
# los datos analizados y las cuentas (NULL: todas).
INSIGHT_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS insights (
    month TEXT PRIMARY KEY
        CHECK (length(month) = 7 AND month GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'),
    text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 4000),
    data_hash TEXT NOT NULL,
    accounts TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
)

# Bitácora (esquema 15; ver `analysis.changelog`): cada cambio hecho desde el board, con su
# autor, lo que había antes y lo que quedó después (`changes`: las filas tocadas, en JSON), las
# huellas que afectaba en ese momento y un motivo opcional. `undoes`: la entrada que deshace.
# `change_log_rows` indexa las filas tocadas (para saber qué entrada posterior bloquea un
# «Deshacer») y `change_log_fingerprints` las huellas (el historial de una transacción). Las
# reglas por comercio propuestas y descartadas («Para revisar») van en `rule_dismissals`; lo
# visto con `finanzas nuevas --marcar-revisadas`, en `reviewed_fingerprints`. Además, `categories`,
# `links` y `link_manual` pasan a `AUTOINCREMENT` (`AUTOINCREMENT_TABLES`): un id borrado no se
# reusa, así «Deshacer» nunca devuelve una fila a una madre ajena que heredó su id.
LOG_AUTHORS = ("usuario", "claude")
LOG_TARGETS = ("transaccion", "comercio", "categoria", "vinculo", "caja", "recurrente")
LOG_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    author TEXT NOT NULL CHECK (author IN ({authors})),
    kind TEXT NOT NULL CHECK (length(kind) BETWEEN 1 AND 40),
    target_type TEXT NOT NULL CHECK (target_type IN ({targets})),
    target TEXT NOT NULL,
    subject TEXT NOT NULL,
    merchant TEXT,
    before_text TEXT NOT NULL,
    after_text TEXT NOT NULL,
    changes TEXT NOT NULL,
    affected INTEGER NOT NULL CHECK (affected >= 0),
    reason TEXT CHECK (reason IS NULL OR length(reason) <= 500),
    undoes INTEGER REFERENCES change_log(id)
)""".format(
        authors=", ".join(f"'{a}'" for a in LOG_AUTHORS),
        targets=", ".join(f"'{t}'" for t in LOG_TARGETS),
    ),
    "CREATE INDEX IF NOT EXISTS change_log_at ON change_log(at)",
    "CREATE INDEX IF NOT EXISTS change_log_undoes ON change_log(undoes)",
    """CREATE TABLE IF NOT EXISTS change_log_rows (
    entry_id INTEGER NOT NULL REFERENCES change_log(id) ON DELETE CASCADE,
    row_key TEXT NOT NULL,
    PRIMARY KEY (entry_id, row_key)
)""",
    "CREATE INDEX IF NOT EXISTS change_log_rows_key ON change_log_rows(row_key)",
    """CREATE TABLE IF NOT EXISTS change_log_fingerprints (
    entry_id INTEGER NOT NULL REFERENCES change_log(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    PRIMARY KEY (entry_id, fingerprint)
)""",
    "CREATE INDEX IF NOT EXISTS change_log_fingerprints_fp ON change_log_fingerprints(fingerprint)",
    """CREATE TABLE IF NOT EXISTS rule_dismissals (
    merchant TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    dismissed_at TEXT NOT NULL,
    PRIMARY KEY (merchant, category_id)
)""",
    """CREATE TABLE IF NOT EXISTS reviewed_fingerprints (
    fingerprint TEXT PRIMARY KEY,
    reviewed_at TEXT NOT NULL
)""",
)
# Esquema 16 (recurrentes del hogar): la cadencia y el grupo elegidos a mano en una marca
# (`recurring.GROUPS`; el grupo se valida en `recurring_marks`) y las uniones de comercios
# (comercio -> clave de su serie: otro comercio o `proveedor:<id>`). Las marcas no se mueven:
# las de un comercio que hoy va en un proveedor se leen como del proveedor
# (`recurring_marks.for_series`).
RECURRING_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "recurring_marks": (
        ("cadence", "TEXT CHECK (cadence IS NULL OR cadence IN ('mensual', 'anual'))"),
        ("group_key", "TEXT CHECK (group_key IS NULL OR length(group_key) <= 40)"),
    ),
}
RECURRING_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS recurring_unions (
    merchant TEXT PRIMARY KEY CHECK (length(merchant) BETWEEN 1 AND 200),
    target TEXT NOT NULL CHECK (length(target) BETWEEN 1 AND 200),
    updated_at TEXT NOT NULL
)""",
)
# Esquema 17 (presupuesto y reservas; ver `analysis.budget` y `analysis.reserves`). Una reserva
# es un vínculo `'reserve'` (sus gastos, `'reserved'`, por huella como los demás: una huella está
# en un solo vínculo) con su plan en `links`: monto estimado en RD$ (`reserve_cents`), categoría,
# primer vencimiento (`due_month`, AAAA-MM), cada cuántos meses se repite (`every_months`; NULL:
# una sola vez), si junta varios gastos (`multiple`), la sugerencia de la que salió (`source`) y el
# mes desde el que se aparta (`start_month`, el de su creación).
# El tope de cada categoría va en `budget_caps` (sin filas: presupuesto sin activar; `cap_cents`
# NULL: «Sin presupuesto»; `manual`: editado a mano, queda fijo; `basis_cents`: lo habitual
# redondeado ya visto, contra el que se avisa si cambia). Las sugerencias de reservas descartadas
# van por su clave en `reserve_dismissals`.
RESERVE_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "links": (
        ("reserve_cents", "INTEGER CHECK (reserve_cents IS NULL OR reserve_cents > 0)"),
        ("category_id", "INTEGER"),
        (
            "due_month",
            "TEXT CHECK (due_month IS NULL OR (length(due_month) = 7 "
            "AND due_month GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'))",
        ),
        ("every_months", "INTEGER CHECK (every_months IS NULL OR every_months BETWEEN 1 AND 12)"),
        ("multiple", "INTEGER NOT NULL DEFAULT 0 CHECK (multiple IN (0, 1))"),
        ("source", "TEXT CHECK (source IS NULL OR length(source) <= 200)"),
        (
            "start_month",
            "TEXT CHECK (start_month IS NULL OR (length(start_month) = 7 "
            "AND start_month GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'))",
        ),
    ),
}
BUDGET_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS budget_caps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL UNIQUE REFERENCES categories(id) ON DELETE CASCADE,
    cap_cents INTEGER CHECK (cap_cents IS NULL OR cap_cents >= 0),
    manual INTEGER NOT NULL DEFAULT 0 CHECK (manual IN (0, 1)),
    basis_cents INTEGER CHECK (basis_cents IS NULL OR basis_cents >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS reserve_dismissals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE CHECK (length(key) BETWEEN 1 AND 200),
    dismissed_at TEXT NOT NULL
)""",
)

# Van después de `SCHEMA` porque una base vieja necesita antes las columnas nuevas.
# Un estado por cuenta, plástico, moneda y corte. Dos tarjetas del mismo banco con el mismo
# corte son estados distintos; la cuenta de ahorro no tiene plástico. Una impresión no es
# un estado: puede terminar el día de un corte. Dos impresiones son la misma solo si también
# coinciden en contenido (balance final, totales y filas): reimprimir el mismo rango más
# tarde puede traer posteos nuevos del último día.
_STATEMENT_INDEXES = f"""
CREATE UNIQUE INDEX IF NOT EXISTS {DUPLICATE_PERIOD_INDEX}
    ON statements (account_id, COALESCE(card_id, 0), currency, period_end)
    WHERE parser NOT IN ({_PRINTOUT_LIST});
CREATE UNIQUE INDEX IF NOT EXISTS {DUPLICATE_PRINTOUT_INDEX}
    ON statements (
        account_id, currency, COALESCE(period_start, ''), period_end,
        COALESCE(closing_balance_cents, 0), COALESCE(printed_debits_cents, 0),
        COALESCE(printed_credits_cents, 0), COALESCE(transaction_count, 0)
    )
    WHERE parser IN ({_PRINTOUT_LIST});
"""

_INSERT_STATEMENT = """
INSERT INTO statements (
    document_id, account_id, card_id, parser, product, currency, period_start, period_end,
    due_date, previous_balance_cents, closing_balance_cents, minimum_payment_cents,
    credit_limit_cents, printed_debits_cents, printed_credits_cents, transaction_count
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_TRANSACTION = """
INSERT INTO transactions (
    statement_id, sequence, transacted_on, posted_on, description, amount_cents,
    direction, currency, reference, mcc, raw_line
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    if str(path) != ":memory:":
        Path(path).chmod(0o600)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Pone al día una base creada con un esquema anterior (idempotente)."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(statements)")}
    with conn:
        if "period_start" not in columns:
            conn.execute("ALTER TABLE statements ADD COLUMN period_start TEXT")
        if "transaction_count" not in columns:
            conn.execute("ALTER TABLE statements ADD COLUMN transaction_count INTEGER")
        if "note" not in _table_columns(conn, "document_parts"):  # una base de prueba previa
            conn.execute("ALTER TABLE document_parts ADD COLUMN note TEXT")
        # Índices de versiones anteriores: sin excluir impresiones, sin su contenido o sin
        # todos los parsers de impresiones.
        printouts = tuple(f"'{name}'".upper() for name in PRINTOUT_PARSERS)
        _drop_unless(conn, DUPLICATE_PERIOD_INDEX, ("WHERE", *printouts))
        _drop_unless(conn, DUPLICATE_PRINTOUT_INDEX, ("TRANSACTION_COUNT", *printouts))
    conn.executescript(_STATEMENT_INDEXES)
    _migrate_categories(conn)


# Tablas de correcciones con el nombre de la categoría (esquema 7 y antes) -> con su id.
_ID_TABLES = {
    "merchant_categories": """
        CREATE TABLE merchant_categories_v8 (
            merchant TEXT PRIMARY KEY,
            category_id INTEGER NOT NULL REFERENCES categories(id),
            updated_at TEXT NOT NULL
        )""",
    "transaction_notes": """
        CREATE TABLE transaction_notes_v8 (
            fingerprint TEXT PRIMARY KEY,
            category_id INTEGER REFERENCES categories(id),
            one_off INTEGER NOT NULL DEFAULT 0 CHECK (one_off IN (0, 1)),
            updated_at TEXT NOT NULL
        )""",
}


def _migrate_categories(conn: sqlite3.Connection) -> None:
    """Siembra las categorías del sistema, pasa las correcciones de nombre a id y agrega lo del
    esquema 9 (notas y vínculos), del 10 (lo revisado), del 11 (análisis), del 12 (grupos
    compartidos), del 13 (inversiones), del 14 (caja fuerte), del 15 (bitácora), del 16
    (recurrentes del hogar) y del 17 (presupuesto y reservas); deja la versión al día (idempotente).

    Todo en una transacción (también `user_version`): o queda migrada entera o como estaba.
    Un nombre guardado se lee como hoy (`catalog.Catalog.by_name`: el nombre actual, uno viejo
    como "Efectivo y transferencias" o el de nacimiento); uno que ya no existe se conserva como
    categoría de gasto del usuario con ese nombre, para no perder la corrección.
    """
    # Rehacer una tabla con hijos (`links`) borraría en cascada sus miembros: las claves foráneas
    # se apagan antes de la transacción (dentro no se puede) y se revisan antes del COMMIT.
    rebuild = _needs_rebuild(conn)
    if rebuild:
        conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _migrate_in_transaction(conn, rebuild)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        if rebuild:
            conn.execute("PRAGMA foreign_keys = ON")


# Las tablas hijas de `links` que pueden quedar huérfanas si una reconstrucción sale mal.
_LINK_CHILDREN = ("link_members", "link_manual")


def _migrate_in_transaction(conn: sqlite3.Connection, rebuild: bool) -> None:
    catalog.seed_builtins(conn)
    # Antes que todo lo que lee movimientos (`_fill_manual_currency` carga el flujo, que trae los
    # de la caja).
    for statement in CASH_SCHEMA:
        conn.execute(statement)
    made: dict[str, int] = {}
    for table, create in _ID_TABLES.items():
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "category" in columns:
            _rebuild_with_ids(conn, table, create, made)
    _migrate_links(conn)
    _migrate_groups(conn)
    for statement in (*REVIEW_SCHEMA, *INSIGHT_SCHEMA):
        conn.execute(statement)
    _migrate_investments(conn)
    _add_columns(conn, CASH_BOX_COLUMNS)
    for statement in LOG_SCHEMA:
        conn.execute(statement)
    _add_columns(conn, RECURRING_COLUMNS)
    for statement in RECURRING_SCHEMA:
        conn.execute(statement)
    _add_columns(conn, RESERVE_COLUMNS)
    for statement in BUDGET_SCHEMA:
        conn.execute(statement)
    rebuilt = _migrate_autoincrement(conn)
    # Solo tras rehacer tablas, y solo las rehechas (y las hijas de `links`): una huérfana ajena
    # (de otra tabla, de antes) no debe impedir abrir la base.
    if rebuild:
        for child in dict.fromkeys((*_LINK_CHILDREN, *rebuilt)):
            if conn.execute(f"PRAGMA foreign_key_check({child})").fetchone() is not None:
                raise sqlite3.IntegrityError("la migración dejó filas sin su fila madre")
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


# Esquemas 13, 14 y 17: los CHECK que se amplían (SQLite no los cambia con ALTER: la tabla se
# rehace con las mismas columnas y filas). Tabla -> (patrón del CHECK viejo, CHECK nuevo, marca de
# que ya está al día: el último valor agregado).
_WIDENED_CHECKS: dict[str, tuple[str, str, str]] = {
    "links": (r"CHECK\s*\(\s*kind\s+IN\s*\([^)]*\)\s*\)", _LINK_KIND_CHECK, "'reserve'"),
    "link_members": (r"CHECK\s*\(\s*role\s+IN\s*\([^)]*\)\s*\)", _LINK_ROLE_CHECK, "'reserved'"),
    "review_marks": (
        r"CHECK\s*\(\s*kind\s+IN\s*\([^)]*\)\s*\)",
        f"CHECK (kind IN ({_REVIEW_KIND_LIST}))",
        "'reserva_posible'",
    ),
}


def _table_sql(conn: sqlite3.Connection, table: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return None if row is None else str(row[0])


def _needs_rebuild(conn: sqlite3.Connection) -> bool:
    """Alguna tabla tiene un CHECK de antes (esquema 13 o anterior) que no admite las inversiones
    o la caja fuerte, o reusa ids borrados (esquema 14 o anterior)."""
    for table, (_, _, marker) in _WIDENED_CHECKS.items():
        sql = _table_sql(conn, table)
        if sql is not None and marker not in sql:
            return True
    return any(_needs_autoincrement(conn, table) for table in AUTOINCREMENT_TABLES)


# Esquema 15: las madres a las que vuelve «Deshacer», en el orden en que se rehacen.
AUTOINCREMENT_TABLES = ("categories", "links", "link_manual")
_ID_PATTERN = r"\bid\s+INTEGER\s+PRIMARY\s+KEY\b(?!\s+AUTOINCREMENT)"


def _needs_autoincrement(conn: sqlite3.Connection, table: str) -> bool:
    sql = _table_sql(conn, table)
    return sql is not None and "AUTOINCREMENT" not in sql.upper()


def _migrate_autoincrement(conn: sqlite3.Connection) -> list[str]:
    """Esquema 15: rehace las tablas de `AUTOINCREMENT_TABLES` con `AUTOINCREMENT` (mismas
    columnas, filas, ids e índices; `sqlite_sequence` arranca en el id más alto). Devuelve las
    rehechas."""
    rebuilt = []
    for table in AUTOINCREMENT_TABLES:
        if _needs_autoincrement(conn, table):
            sql = str(_table_sql(conn, table))
            _rebuild_check(conn, table, sql, _ID_PATTERN, "id INTEGER PRIMARY KEY AUTOINCREMENT")
            rebuilt.append(table)
    return rebuilt


def _migrate_investments(conn: sqlite3.Connection) -> None:
    """Esquemas 13 y 14: amplía los CHECK de `links`, `link_members` y `review_marks` (rehaciendo
    cada tabla con sus filas y sus índices, la madre antes que la hija) y agrega
    `capital_cents`."""
    for table, (pattern, check, marker) in _WIDENED_CHECKS.items():
        sql = _table_sql(conn, table)
        if sql is not None and marker not in sql:
            _rebuild_check(conn, table, sql, pattern, check)
    _add_columns(conn, INVESTMENT_COLUMNS)


def _add_columns(conn: sqlite3.Connection, tables: dict[str, tuple[tuple[str, str], ...]]) -> None:
    for table, columns in tables.items():
        present = _table_columns(conn, table)
        for name, definition in columns:
            if name not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _rebuild_check(
    conn: sqlite3.Connection, table: str, sql: str, pattern: str, check: str
) -> None:
    widened, count = re.subn(pattern, check, sql, count=1, flags=re.IGNORECASE)
    if count != 1:
        raise sqlite3.OperationalError(f"no se encontró el CHECK a ampliar en {table}")
    indexes = [
        row[0]
        for row in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? "
            "AND sql IS NOT NULL",
            (table,),
        )
    ]
    staging = f"{table}_rebuild"
    created = re.sub(
        rf"^CREATE TABLE (IF NOT EXISTS )?\"?{table}\"?",
        f"CREATE TABLE {staging}",
        widened,
        count=1,
        flags=re.IGNORECASE,
    )
    columns = ", ".join(sorted(_table_columns(conn, table)))
    # Con AUTOINCREMENT, la secuencia de la tabla vieja (que puede pasar del id más alto si se
    # borraron filas) se pierde con el DROP: se guarda y se restaura, así un id borrado no se
    # reusa.
    saved = _sequence(conn, table)
    conn.execute(created)
    conn.execute(f"INSERT INTO {staging} ({columns}) SELECT {columns} FROM {table}")
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {staging} RENAME TO {table}")
    if saved is not None:
        _restore_sequence(conn, table, saved)
    for index in indexes:
        conn.execute(index)


def _sequence(conn: sqlite3.Connection, table: str) -> int | None:
    if _table_sql(conn, "sqlite_sequence") is None:
        return None
    row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
    return None if row is None else int(row[0])


def _restore_sequence(conn: sqlite3.Connection, table: str, saved: int) -> None:
    """Deja la secuencia de `table` en max(la de ahora, `saved`)."""
    current = _sequence(conn, table)
    if current is None:
        conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table, saved))
    elif current < saved:
        conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (saved, table))


def _migrate_links(conn: sqlite3.Connection) -> None:
    """Esquema 9: la nota libre de cada transacción y las tablas de vínculos."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(transaction_notes)")}
    if "note" not in columns:
        conn.execute(
            "ALTER TABLE transaction_notes ADD COLUMN note TEXT "
            "CHECK (note IS NULL OR length(note) <= 500)"
        )
    for statement in LINK_SCHEMA:
        conn.execute(statement)


def _migrate_groups(conn: sqlite3.Connection) -> None:
    """Esquema 12: un vínculo compartido pasa a ser un grupo de gastos. Agrega las columnas y,
    la primera vez, copia el reparto de cada vínculo a su único gasto y «para quién» a «Con
    quién»: ninguna cifra cambia. Quita el índice de un solo gasto por vínculo."""
    first_time = "people" not in _table_columns(conn, "link_members")
    for table, columns in GROUP_COLUMNS.items():
        present = _table_columns(conn, table)
        for name, definition in columns:
            if name not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    if first_time:
        conn.execute(
            "UPDATE link_members SET "
            "people = (SELECT l.people FROM links l WHERE l.id = link_members.link_id), "
            "my_share_cents = (SELECT l.my_share_cents FROM links l "
            "WHERE l.id = link_members.link_id), "
            "for_other = (SELECT l.for_other FROM links l WHERE l.id = link_members.link_id) "
            "WHERE role = 'expense'"
        )
        conn.execute("UPDATE links SET with_whom = for_whom WHERE kind = 'shared'")
    conn.execute("DROP INDEX IF EXISTS link_one_expense")
    _fill_manual_currency(conn)


def _fill_manual_currency(conn: sqlite3.Connection) -> None:
    """Los reembolsos a mano del esquema 11 no dicen su moneda: era la del único gasto del
    vínculo. Se guarda esa (la del primer gasto agregado), así no cambia si luego se suma un gasto
    en otra moneda; si el gasto ya no aparece, RD$."""
    groups = [
        row[0]
        for row in conn.execute("SELECT DISTINCT link_id FROM link_manual WHERE currency IS NULL")
    ]
    if not groups:
        return
    from finanzas.analysis import spending  # noqa: PLC0415 (lee la base ya con las columnas)

    currency_of = {m.fingerprint: m.currency for m in spending.load_all(conn)}
    for link_id in groups:
        first = conn.execute(
            "SELECT fingerprint FROM link_members WHERE link_id = ? AND role = 'expense' "
            "ORDER BY added_at, rowid LIMIT 1",
            (link_id,),
        ).fetchone()
        currency = None if first is None else currency_of.get(first[0])
        conn.execute(
            "UPDATE link_manual SET currency = ? WHERE link_id = ? AND currency IS NULL",
            (currency or "DOP", link_id),
        )


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _rebuild_with_ids(
    conn: sqlite3.Connection, table: str, create: str, made: dict[str, int]
) -> None:
    conn.execute(create)
    key = "merchant" if table == "merchant_categories" else "fingerprint"
    extra = "" if table == "merchant_categories" else ", one_off"
    rows = conn.execute(f"SELECT {key}, category{extra}, updated_at FROM {table}").fetchall()
    for row in rows:
        category = row["category"]
        category_id = None if category is None else _category_id(conn, category, made)
        values = (row[key], category_id, *([row["one_off"]] if extra else []), row["updated_at"])
        marks = ", ".join("?" * len(values))
        conn.execute(f"INSERT INTO {table}_v8 VALUES ({marks})", values)
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {table}_v8 RENAME TO {table}")


_NO_NAME = "Sin nombre"


def _category_id(conn: sqlite3.Connection, name: str, made: dict[str, int]) -> int:
    """Id del nombre guardado; nunca falla (la migración no puede quedar a medias).

    Uno desconocido se guarda con un nombre válido y único: vacío -> "Sin nombre", cortado a
    `catalog.NAME_MAX` y con " (2)", " (3)"… si ya existe. `made` recuerda los creados, así
    el mismo nombre viejo da siempre la misma categoría.
    """
    if name in made:
        return made[name]
    found = catalog.load(conn).by_name(name) if name.strip() else None
    if found is not None:
        return found.id
    base = " ".join(name.split()) or _NO_NAME
    taken = {catalog.fold(row[0]) for row in conn.execute("SELECT name FROM categories")}
    candidate, number = base[: catalog.NAME_MAX], 2
    while catalog.fold(candidate) in taken:
        suffix = f" ({number})"
        candidate = base[: catalog.NAME_MAX - len(suffix)].rstrip() + suffix
        number += 1
    cursor = conn.execute(
        "INSERT INTO categories (name, kind, color, hidden, builtin, builtin_key, created_at) "
        "VALUES (?, 'gasto', NULL, 0, 0, NULL, datetime('now'))",
        (candidate,),
    )
    made[name] = int(cursor.lastrowid or 0)
    return made[name]


def _drop_unless(conn: sqlite3.Connection, name: str, markers: tuple[str, ...]) -> None:
    found = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)
    ).fetchone()
    if found is not None and not all(m in found["sql"].upper() for m in markers):
        conn.execute(f"DROP INDEX {name}")


def cents(value: Decimal | None) -> int | None:
    if value is None:
        return None
    scaled = value * 100
    if scaled != scaled.to_integral_value():
        raise ValueError(f"monto con más de dos decimales: {value}")
    return int(scaled)


def account_key(statement: Statement) -> str:
    """Una tarjeta cambia de plástico pero sigue siendo la misma cuenta; una de ahorro no."""
    if statement.kind == "credit_card":
        return f"{statement.institution}:credit_card"
    return f"{statement.institution}:{statement.kind}:{statement.identifier}"


def account_currency(conn: sqlite3.Connection, key: str) -> str | None:
    """Moneda indicada para las impresiones de la cuenta, si alguien la indicó."""
    row = conn.execute(
        "SELECT currency FROM account_currency WHERE account_key = ?", (key,)
    ).fetchone()
    return None if row is None else str(row[0])


def account_currencies(conn: sqlite3.Connection) -> dict[str, str]:
    """Todas las monedas indicadas, por clave de cuenta."""
    rows = conn.execute("SELECT account_key, currency FROM account_currency")
    return {str(row[0]): str(row[1]) for row in rows}


def set_account_currency(conn: sqlite3.Connection, key: str, currency: str, now: str) -> None:
    conn.execute(
        "INSERT INTO account_currency (account_key, currency, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(account_key) DO UPDATE SET "
        "currency = excluded.currency, updated_at = excluded.updated_at",
        (key, currency, now),
    )


def store_statement(conn: sqlite3.Connection, document_id: int, statement: Statement) -> int:
    """Guarda el estado (una fila por moneda) y sus transacciones; devuelve cuántas guardó."""
    account_id = _account_id(conn, statement)
    card_id = _card_id(conn, account_id, statement)
    stored = 0
    for section in statement.sections:
        statement_id = _insert_section(conn, document_id, account_id, card_id, statement, section)
        conn.executemany(
            _INSERT_TRANSACTION,
            [_transaction_row(statement_id, i, t) for i, t in enumerate(section.transactions)],
        )
        stored += len(section.transactions)
    return stored


def _account_id(conn: sqlite3.Connection, statement: Statement) -> int:
    key = account_key(statement)
    name = f"{statement.institution.upper()} {statement.product}"
    if statement.kind != "credit_card":
        name = f"{name} {statement.identifier}"
    conn.execute(
        "INSERT INTO accounts (key, institution, kind, name) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(key) DO NOTHING",
        (key, statement.institution, statement.kind, name),
    )
    return conn.execute("SELECT id FROM accounts WHERE key = ?", (key,)).fetchone()[0]


def _card_id(conn: sqlite3.Connection, account_id: int, statement: Statement) -> int | None:
    if statement.kind != "credit_card":
        return None
    seen = statement.period_end.isoformat()
    conn.execute(
        "INSERT INTO cards (account_id, last4, product, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(account_id, last4) DO UPDATE SET "
        "first_seen = min(first_seen, excluded.first_seen), "
        "last_seen = max(last_seen, excluded.last_seen)",
        (account_id, statement.identifier, statement.product, seen, seen),
    )
    row = conn.execute(
        "SELECT id FROM cards WHERE account_id = ? AND last4 = ?",
        (account_id, statement.identifier),
    ).fetchone()
    return row[0]


def _insert_section(
    conn: sqlite3.Connection,
    document_id: int,
    account_id: int,
    card_id: int | None,
    statement: Statement,
    section: Section,
) -> int:
    cursor = conn.execute(
        _INSERT_STATEMENT,
        (
            document_id,
            account_id,
            card_id,
            statement.parser,
            statement.product,
            section.currency,
            statement.period_start.isoformat() if statement.period_start else None,
            statement.period_end.isoformat(),
            statement.due_date.isoformat() if statement.due_date else None,
            cents(section.previous_balance),
            cents(section.closing_balance),
            cents(section.minimum_payment),
            cents(section.credit_limit),
            cents(section.printed_debits),
            cents(section.printed_credits),
            len(section.transactions),
        ),
    )
    return int(cursor.lastrowid or 0)


def _transaction_row(statement_id: int, sequence: int, transaction: Transaction) -> tuple:
    return (
        statement_id,
        sequence,
        transaction.transacted_on.isoformat(),
        transaction.posted_on.isoformat() if transaction.posted_on else None,
        transaction.description,
        cents(transaction.amount),
        transaction.direction,
        transaction.currency,
        transaction.reference,
        transaction.mcc,
        transaction.raw_line,
    )


FAILED_PART_STATUSES = ("invalid", "error")


def replace_document_parts(
    conn: sqlite3.Connection,
    document_id: int,
    parts: Iterable[tuple[int, str, str, str | None, str | None]],
) -> None:
    """Reescribe los tramos del documento: (número, etiqueta, estado, detalle, nota)."""
    conn.execute("DELETE FROM document_parts WHERE document_id = ?", (document_id,))
    conn.executemany(
        "INSERT INTO document_parts (document_id, part, label, status, detail, note) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(document_id, *part) for part in parts],
    )


def failed_parts(conn: sqlite3.Connection, document_id: int) -> int:
    """Cuántos tramos del documento quedaron sin guardar por no cuadrar o no leerse."""
    marks = ", ".join("?" for _ in FAILED_PART_STATUSES)
    row = conn.execute(
        f"SELECT COUNT(*) FROM document_parts WHERE document_id = ? AND status IN ({marks})",
        (document_id, *FAILED_PART_STATUSES),
    ).fetchone()
    return int(row[0])


def stored_for_document(conn: sqlite3.Connection, document_id: int, statement: Statement) -> bool:
    """¿Ya se guardó este estado (cuenta, moneda y corte) desde este mismo documento?"""
    marks = ", ".join("?" for _ in statement.sections)
    row = conn.execute(
        "SELECT COUNT(*) FROM statements s JOIN accounts a ON a.id = s.account_id "
        f"WHERE s.document_id = ? AND a.key = ? AND s.period_end = ? AND s.currency IN ({marks})",
        (
            document_id,
            account_key(statement),
            statement.period_end.isoformat(),
            *(section.currency for section in statement.sections),
        ),
    ).fetchone()
    return int(row[0]) > 0


def has_statements(conn: sqlite3.Connection, document_id: int) -> bool:
    """¿El documento ya tiene algún estado guardado?"""
    row = conn.execute(
        "SELECT 1 FROM statements WHERE document_id = ? LIMIT 1", (document_id,)
    ).fetchone()
    return row is not None
