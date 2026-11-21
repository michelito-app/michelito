"""Identifiers from before the English rename (when the app was called "finanzas").

This is the only module that may name them. Databases, data folders and keyrings created by
earlier releases still carry these names and values, so the code needs them in these
situations:

- locating an existing install: the old data folder, database file, holders and senders files
  and keyring service, used only as a read fallback when the new one does not exist (see
  `config`, `sources` and `vault`);
- migrating stored values once (`migrations_v18`: every old -> new map below);
- keeping old names reserved so new data never collides with what is already on disk;
- reading what earlier releases handed out: the dossier header in a pasted analysis, and the
  dossier hash saved with an insight (`dossier_data` rebuilds the old data to recompute it);
- migrating the demo's feedback store once (`FEEDBACK_*`, used by `demo.feedback_store`).

Nothing here is used to write new data under an old name.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

# Install layout and keyring.
DATA_DIR = "~/finanzas-data"
DATABASE_FILE = "finanzas.db"
KEYRING_SERVICE = "finanzas"
# Files the owner keeps in the data folder: the account holders and the Gmail senders. The old
# senders file used Spanish keys: `[[fuente]]` tables with these keys, old -> new.
HOLDERS_FILE = "titulares.txt"
SOURCES_FILE = "fuentes.toml"
SOURCES_TABLE = "fuente"
SOURCE_KEYS: Mapping[str, str] = {
    "nombre": "name",
    "consulta": "query",
    "extensiones": "extensions",
    "interpretar": "parse",
}

# Raw-archive folder and document source of manual imports (kept reserved as source names).
IMPORT_FOLDER = "importados"
IMPORT_SOURCE = "importado"

# Stored enum values, old -> new.
CATEGORY_KINDS: Mapping[str, str] = {
    "ingreso": "income",
    "gasto": "expense",
    "transferencia": "transfer",
}
REVIEW_KINDS: Mapping[str, str] = {
    "unico": "one_off",
    "ingreso_inusual": "unusual_income",
    "tercero_grande": "large_third_party",
    "duplicado": "duplicate",
    "subio": "price_up",
    "aporte_posible": "possible_contribution",
    "cobro_posible": "possible_return",
    "regla_posible": "possible_rule",
    "reserva_posible": "possible_reserve",
}
CADENCES: Mapping[str, str] = {"mensual": "monthly", "anual": "yearly"}
RECURRING_GROUPS: Mapping[str, str] = {
    "vivienda": "housing",
    "prestamos": "loans",
    "servicios": "utilities",
    "seguros": "insurance",
    "suscripciones": "subscriptions",
    "cargos": "fees",
    "otros": "other",
}
LOG_AUTHORS: Mapping[str, str] = {"usuario": "user"}
LOG_TARGET_TYPES: Mapping[str, str] = {
    "transaccion": "transaction",
    "comercio": "merchant",
    "categoria": "category",
    "vinculo": "link",
    "caja": "cash_box",
    "recurrente": "recurring",
}
LOG_KINDS: Mapping[str, str] = {
    "categoria": "category",
    "categoria_lote": "category_batch",
    "regla": "merchant_rule",
    "nota": "note",
    "gasto_unico": "one_off",
    "palabras_clave": "keywords",
    "categoria_tipo": "category_kind",
    "categoria_borrada": "category_deleted",
    "compartido": "shared",
    "cambio": "exchange",
    "revisado": "reviewed",
    "caja_fuerte": "cash_box",
    "caja_movimiento": "cash_entry",
    "inversion": "investment",
    "recurrente": "recurring",
    "recurrente_union": "recurring_union",
    "presupuesto": "budget",
    "presupuesto_aviso": "budget_warning",
    "reserva": "reserve",
    "reserva_gasto": "reserve_expense",
    "reserva_descarte": "reserve_dismissal",
}
# `change_log.target` values that are a fixed word rather than a key.
LOG_TARGETS: Mapping[str, str] = {"presupuesto": "budget"}
DOCUMENT_SOURCES: Mapping[str, str] = {IMPORT_SOURCE: "imported", "generado": "generated"}
MESSAGE_SENDERS: Mapping[str, str] = {"importación manual": "manual import"}
PARSER_NAMES: Mapping[str, str] = {
    "banreservas_cuenta": "banreservas_account",
    "banreservas_parcial": "banreservas_partial",
    "bhd_ahorro": "bhd_savings",
    "bhd_ahorro_parcial": "bhd_savings_partial",
    "bhd_tc": "bhd_card",
    "popular_cuenta": "popular_account",
    "popular_historico": "popular_history",
    "popular_tc": "popular_card",
}

# Keys built from a prefix, old -> new: the cash-entry fingerprint (`caja-<id>`), the cash box
# account, a provider series (`proveedor:<id>`) and reserve suggestions (`recurrente:<series>:
# <currency>`, `pico:<category>:<MM>`; `irregular:` did not change).
CASH_FINGERPRINT_PREFIX = "caja-"
CASH_BOX_KEY = "manual:caja-fuerte"
PROVIDER_PREFIX = "proveedor:"
RESERVE_KEY_PREFIXES: Mapping[str, str] = {"recurrente:": "recurring:", "pico:": "peak:"}

_NEW_CASH_PREFIX = "cash-"
_NEW_CASH_BOX_KEY = "manual:cash-box"
_NEW_PROVIDER_PREFIX = "provider:"
_CASH_FINGERPRINT = re.compile(rf"^{re.escape(CASH_FINGERPRINT_PREFIX)}(\d+)$")
# A provider series inside a longer text: at the start or after a space or comma (the log's
# recurring targets are "<series> · <currency>" or a comma-separated list of series).
_PROVIDER_IN_TEXT = re.compile(rf"(^|[ ,]){re.escape(PROVIDER_PREFIX)}")


def sources_data(data: Mapping[str, object]) -> dict[str, object]:
    """An old `fuentes.toml` (already parsed) with the current table and key names, for
    `sources.parse_sources`. Unknown tables and keys are kept as they are, so the validation
    still reports them."""

    def entry(value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        return {SOURCE_KEYS.get(key, key): item for key, item in value.items()}

    translated: dict[str, object] = {}
    for table, value in data.items():
        if table == SOURCES_TABLE:
            translated["source"] = (
                [entry(item) for item in value] if isinstance(value, list) else value
            )
        else:
            translated[table] = value
    return translated


def translate_key(value: str) -> str:
    """The new form of a stored key: a fingerprint, an account key, a series key or a reserve
    suggestion key. Anything else comes back unchanged (so it is safe to apply twice)."""
    cash = _CASH_FINGERPRINT.match(value)
    if cash is not None:
        return f"{_NEW_CASH_PREFIX}{cash.group(1)}"
    if value == CASH_BOX_KEY:
        return _NEW_CASH_BOX_KEY
    if value.startswith(PROVIDER_PREFIX):
        return _NEW_PROVIDER_PREFIX + value.removeprefix(PROVIDER_PREFIX)
    for old, new in RESERVE_KEY_PREFIXES.items():
        if value.startswith(old):
            return new + translate_key(value.removeprefix(old))
    return value


def translate_series_text(value: str) -> str:
    """Provider series named inside a longer text (a recurring log entry's target)."""
    return _PROVIDER_IN_TEXT.sub(rf"\g<1>{_NEW_PROVIDER_PREFIX}", value)


def old_key(value: str) -> str:
    """The pre-rename form of a cash fingerprint or the cash box account key (the inverse of
    `translate_key` for the keys a dossier shows); anything else comes back unchanged."""
    if value.startswith(_NEW_CASH_PREFIX) and value.removeprefix(_NEW_CASH_PREFIX).isdigit():
        return CASH_FINGERPRINT_PREFIX + value.removeprefix(_NEW_CASH_PREFIX)
    if value == _NEW_CASH_BOX_KEY:
        return CASH_BOX_KEY
    return value


# The side of a "what happened" line (`anomalies.Side`), old -> new.
WHAT_HAPPENED_SIDES: Mapping[str, str] = {"gasto": "expense", "ingreso": "income"}

# The month's dossier (`michelito.dossier`). Its header, and the value that meant every account.
DOSSIER_HEADER = re.compile(r"<!--\s*dossier finanzas: mes=(\S+) cuentas=(\S+)\s*-->")
DOSSIER_ALL_ACCOUNTS = "todas"
# Its data keys, old -> new (one map for every section: each old key had a single meaning).
DOSSIER_KEYS: Mapping[str, str] = {
    "mes": "month",
    "etiqueta": "label",
    "parcial": "partial",
    "cuentas": "accounts",
    "claves_de_cuentas": "account_keys",
    "cobertura": "coverage",
    "cuenta": "account",
    "hasta": "through",
    "completo": "complete",
    "totales": "totals",
    "ingresos": "income",
    "ingresos_hasta": "income_through",
    "gastos": "spent",
    "gastos_sin_unicos": "spent_without_one_offs",
    "gastos_unicos": "one_offs",
    "gastos_habituales": "usual_spent",
    "transferencias_a_terceros": "third_party_transfers",
    "te_quedo": "net",
    "porcentaje_ahorrado": "savings_rate_pct",
    "en_dolares_usd": "usd",
    "tasa_rd_por_usd": "dop_per_usd",
    "a_inversiones": "to_investments",
    "ingresos_cripto": "crypto_income",
    "categorias": "categories",
    "categoria": "category",
    "monto": "amount",
    "habitual": "usual",
    "diferencia": "diff",
    "igual_que_siempre": "same_as_usual",
    "compras": "purchases",
    "compras_habituales": "usual_purchases",
    "tendencia": "trend",
    "en_curso": "in_progress",
    "gasto_atipico": "spent_flag",
    "ingreso_atipico": "income_flag",
    "que_paso": "what_happened",
    "lado": "side",
    "comercio": "merchant",
    "descripcion": "description",
    "movimientos": "transactions",
    "fecha": "date",
    "tipo": "kind",
    "moneda": "currency",
    "monto_rd": "amount_dop",
    "gasto_unico": "one_off",
    "vinculo": "link",
    "nota": "note",
    "huella": "fingerprint",
    "para_revisar": "to_review",
    "razon": "reason",
    "revisado": "reviewed",
    "compartidos_y_cambios": "shared_and_exchanges",
    "te_deben": "owed_to_me",
    "cambios_pendientes": "exchanges_pending",
}
_OLD_DOSSIER_KEYS = {new: old for old, new in DOSSIER_KEYS.items()}
# The values a dossier stores that changed, new -> old, by (new) data key. A movement's kind is
# a category kind and a "to review" kind a review kind; the two sets do not overlap.
# Schema 23 renamed what said «Caja fuerte» (the cash account, its transfer category and the
# descriptions of entries without a concept): an insight saved before still hashes the old text.
# By what was renamed (`cash_renames`, written by `migrations_v23` only when it renamed it): the
# dossier keys whose values change, new -> old.
CASH_RENAMES: Mapping[str, tuple[tuple[str, ...], Mapping[str, str]]] = {
    "account": (("accounts", "account"), {"Efectivo": "Caja fuerte"}),
    "category": (("category",), {"Pasado a efectivo": "Caja fuerte"}),
    "descriptions": (
        ("description",),
        {
            "Saldo inicial del efectivo": "Saldo inicial de la caja fuerte",
            "Entrada en efectivo": "Entrada a la caja fuerte",
            "Salida en efectivo": "Salida de la caja fuerte",
        },
    ),
}
_OLD_DOSSIER_VALUES: Mapping[str, Mapping[str, str]] = {
    "kind": {new: old for old, new in (*CATEGORY_KINDS.items(), *REVIEW_KINDS.items())},
    "side": {new: old for old, new in WHAT_HAPPENED_SIDES.items()},
}


def old_cash_names(data: object, renamed: Iterable[str]) -> object:
    """The dossier data with the names schema 23 renamed put back (only those in `renamed`)."""
    wanted: dict[str, dict[str, str]] = {}
    for what in renamed:
        keys, names = CASH_RENAMES[what]
        for key in keys:
            wanted.setdefault(key, {}).update(names)
    if not wanted:
        return data
    return _renamed(data, None, wanted)


def _renamed(value: object, key: str | None, wanted: Mapping[str, Mapping[str, str]]) -> object:
    if isinstance(value, Mapping):
        return {k: _renamed(v, k, wanted) for k, v in value.items()}
    if isinstance(value, list):
        return [_renamed(item, key, wanted) for item in value]
    if isinstance(value, str) and key is not None:
        return wanted.get(key, {}).get(value, value)
    return value


def dossier_data(data: Mapping[str, object], renamed: Iterable[str] = ()) -> dict[str, object]:
    """A dossier's data as the release before the English rename wrote it: Spanish keys, the old
    kind and side values, cash fingerprints `caja-<id>` and the cash box key `manual:caja-fuerte`
    (and, with `renamed`, the names schema 23 renamed in this database). Used only to recompute
    the hash an insight saved back then stores."""
    source = old_cash_names(data, renamed)
    assert isinstance(source, Mapping)
    return {_OLD_DOSSIER_KEYS[key]: _old_value(key, value) for key, value in source.items()}


def _old_value(key: str, value: object) -> object:
    if isinstance(value, Mapping):
        return dossier_data(value)
    if isinstance(value, list):
        if key == "account_keys":
            return sorted(old_key(str(item)) for item in value)
        return [_old_value(key, item) for item in value]
    if isinstance(value, str):
        if key == "fingerprint":
            return old_key(value)
        return _OLD_DOSSIER_VALUES.get(key, {}).get(value, value)
    return value


# The demo's feedback store (`demo.feedback_store`): file, tables and columns, old -> new.
FEEDBACK_FILE = "opiniones.db"
FEEDBACK_TABLE = "opiniones"
FEEDBACK_COLUMNS: Mapping[str, str] = {
    "id": "id",
    "creada": "created_at",
    "texto": "text",
    "correo": "email",
    "pagina": "page",
    "ancho": "width",
    "version": "version",
    "ref": "ref",
}
USAGE_TABLE = "uso"
USAGE_COLUMNS: Mapping[str, str] = {"dia": "day", "tipo": "kind", "clave": "key", "conteo": "count"}
# Usage kinds, and the keys of each kind (screens, copy outcomes, events), old -> new.
USAGE_KINDS: Mapping[str, str] = {"visita": "visit", "copia": "copy", "evento": "event"}
USAGE_KEYS: Mapping[str, Mapping[str, str]] = {
    "visit": {
        "resumen": "summary",
        "presupuesto": "budget",
        "transacciones": "transactions",
        "pendientes": "pending",
        "compartidos": "shared",
        "inversiones": "investments",
        "recurrentes": "recurring",
        "reportes": "reports",
        "cuentas": "accounts",
        "categorias": "categories",
        "bitacora": "log",
        "importar": "import",
        "otra": "other",
    },
    "copy": {"creada": "created"},
    "event": {
        "activar_presupuesto": "budget_activated",
        "crear_reserva": "reserve_created",
        "estado_ejemplo": "sample_statement",
        "seleccion_multiple": "multi_select",
        "deshacer": "undo",
        "copiar_claude": "copy_for_claude",
    },
}


def usage_row(kind: str, key: str) -> tuple[str, str]:
    """The new kind and key of a usage count (a value with no translation stays as it was)."""
    new_kind = USAGE_KINDS.get(kind, kind)
    return new_kind, USAGE_KEYS.get(new_kind, {}).get(key, key)
