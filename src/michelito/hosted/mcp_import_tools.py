"""The AI connector's import tools (phase 2): their schemas and argument checks (pure).

Each one saves a proposal for Review (`web.imports`) and changes nothing until the person
approves it:

- `import_statement`: a whole statement of an existing account, with its printed totals; it is
  refused unless it squares like a PDF does (the answer says what did not, to read it again);
- `import_provisional_charges`: loose charges of an existing account (a CSV, a screenshot),
  pending their statement;
- `import_cash_entries`: cash entries (paper receipts, cash payments or income).

`runner` turns checked arguments into the call `mcp_routes` makes; names and descriptions are
for the model, in English.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from michelito.hosted.mcp_tools import ToolInputError
from michelito.web.imports import ROWS_MAX, RowIn

STATEMENT = "import_statement"
PROVISIONAL = "import_provisional_charges"
CASH = "import_cash_entries"
NAMES = (STATEMENT, PROVISIONAL, CASH)

_TITLE: dict[str, Any] = {
    "type": "string",
    "minLength": 1,
    "maxLength": 120,
    "description": "In Spanish.",
}
_EXPLANATION: dict[str, Any] = {"type": "string", "maxLength": 2000, "description": "In Spanish."}
_ACCOUNT: dict[str, Any] = {
    "type": "string",
    "maxLength": 100,
    "description": "A key from list_accounts.",
}
_DAY: dict[str, Any] = {
    "type": "string",
    "pattern": r"^\d{4}-\d{2}-\d{2}$",
    "description": "YYYY-MM-DD",
}
_CENTS: dict[str, Any] = {"type": "integer", "description": "Cents (RD$ 1,200.50 is 120050)."}
_CURRENCY: dict[str, Any] = {"type": "string", "enum": ["DOP", "USD"]}

_ROW: dict[str, Any] = {
    "type": "object",
    "properties": {
        "day": _DAY,
        "description": {"type": "string", "minLength": 1, "maxLength": 200},
        "amount_cents": {**_CENTS, "minimum": 1},
        "currency": _CURRENCY,
    },
    "required": ["day", "description", "amount_cents", "currency"],
    "additionalProperties": False,
}
_CASH_ROW: dict[str, Any] = {
    "type": "object",
    "properties": {
        **_ROW["properties"],
        "direction": {"type": "string", "enum": ["out", "in"], "description": "out: spent."},
        "category_id": {"type": "integer", "description": "Optional, from list_categories."},
    },
    "required": ["day", "description", "amount_cents", "currency", "direction"],
    "additionalProperties": False,
}
_TRANSACTION: dict[str, Any] = {
    "type": "object",
    "properties": {
        "day": _DAY,
        "posted_day": _DAY,
        "description": {"type": "string", "minLength": 1, "maxLength": 200},
        "amount_cents": {**_CENTS, "minimum": 1, "description": "Always positive."},
        "direction": {
            "type": "string",
            "enum": ["debit", "credit"],
            "description": "debit: a charge or withdrawal; credit: a payment or deposit.",
        },
        "reference": {"type": "string", "maxLength": 40},
        "balance_cents": {**_CENTS, "description": "The printed balance after it, if any."},
    },
    "required": ["day", "description", "amount_cents", "direction"],
    "additionalProperties": False,
}
_SECTION: dict[str, Any] = {
    "type": "object",
    "properties": {
        "currency": _CURRENCY,
        "previous_balance_cents": _CENTS,
        "closing_balance_cents": _CENTS,
        "minimum_payment_cents": _CENTS,
        "credit_limit_cents": _CENTS,
        "printed_debits_cents": {**_CENTS, "description": "The total of charges it prints."},
        "printed_credits_cents": {**_CENTS, "description": "The total of payments it prints."},
        "transactions": {"type": "array", "maxItems": 1000, "items": _TRANSACTION},
    },
    "required": ["currency", "transactions"],
    "additionalProperties": False,
}

SCHEMAS: dict[str, dict[str, Any]] = {
    STATEMENT: {
        "type": "object",
        "properties": {
            "title": _TITLE,
            "explanation": _EXPLANATION,
            "account": _ACCOUNT,
            "period_start": _DAY,
            "period_end": {**_DAY, "description": "The cut-off date."},
            "due_date": _DAY,
            "card_last4": {"type": "string", "pattern": r"^\d{4}$"},
            "sections": {"type": "array", "minItems": 1, "maxItems": 2, "items": _SECTION},
        },
        "required": ["title", "account", "period_end", "sections"],
        "additionalProperties": False,
    },
    PROVISIONAL: {
        "type": "object",
        "properties": {
            "title": _TITLE,
            "explanation": _EXPLANATION,
            "account": _ACCOUNT,
            "charges": {"type": "array", "minItems": 1, "maxItems": ROWS_MAX, "items": _ROW},
        },
        "required": ["title", "account", "charges"],
        "additionalProperties": False,
    },
    CASH: {
        "type": "object",
        "properties": {
            "title": _TITLE,
            "explanation": _EXPLANATION,
            "entries": {"type": "array", "minItems": 1, "maxItems": ROWS_MAX, "items": _CASH_ROW},
        },
        "required": ["title", "entries"],
        "additionalProperties": False,
    },
}

DESCRIPTIONS = {
    STATEMENT: (
        "Propose a whole bank statement that Michelito could not read (a PDF or screenshot the "
        "person shares), for one of their accounts. Give every movement and the totals the "
        "statement prints (charges, payments, previous and closing balance) per currency: it is "
        "refused unless the movements add up to them exactly, and the answer says what did not, "
        "so read it again. Nothing is stored until the person approves it in Review."
    ),
    PROVISIONAL: (
        "Propose loose charges of one account (from a CSV, a screenshot or a list) that have no "
        "statement yet. Approved, each one is 'pending statement' and is confirmed when the "
        "statement arrives. Only charges (money out). Rows that look like transactions already "
        "stored are flagged as possible duplicates."
    ),
    CASH: (
        "Propose cash entries (paper receipts, cash payments, cash received) for the person's "
        "Efectivo account, optionally with a category id. Approved, each one is an entry of the "
        "cash account (undoable in the change log)."
    ),
}


def descriptors() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "title": name.replace("_", " ").capitalize(),
            "description": DESCRIPTIONS[name],
            "inputSchema": SCHEMAS[name],
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": False,
                "openWorldHint": False,
            },
        }
        for name in NAMES
    ]


def _object(arguments: Any, name: str) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ToolInputError("arguments must be an object")
    allowed = set(SCHEMAS[name]["properties"])
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise ToolInputError(f"unknown argument {unknown[0]}")
    for required in SCHEMAS[name]["required"]:
        if required not in arguments:
            raise ToolInputError(f"missing argument {required}")
    if not isinstance(arguments["title"], str) or not arguments["title"].strip():
        raise ToolInputError("title must be a short text")
    if not isinstance(arguments.get("explanation", ""), str):
        raise ToolInputError("explanation must be a text")
    return arguments


def _row(raw: Any, where: str, cash: bool) -> RowIn:
    schema = _CASH_ROW if cash else _ROW
    if not isinstance(raw, dict) or set(raw) - set(schema["properties"]):
        raise ToolInputError(f"{where} has unknown fields")
    for required in schema["required"]:
        if required not in raw:
            raise ToolInputError(f"{where} needs {required}")
    try:
        day = date.fromisoformat(str(raw["day"]))
    except ValueError:
        raise ToolInputError(f"{where}.day must be YYYY-MM-DD") from None
    amount, description = raw["amount_cents"], raw["description"]
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ToolInputError(f"{where}.amount_cents must be an integer")
    if not isinstance(description, str):
        raise ToolInputError(f"{where}.description must be a text")
    category = raw.get("category_id")
    if category is not None and (isinstance(category, bool) or not isinstance(category, int)):
        raise ToolInputError(f"{where}.category_id must be an integer")
    direction = raw.get("direction", "out")
    if direction not in ("out", "in"):
        raise ToolInputError(f"{where}.direction must be out or in")
    return RowIn(day, description, amount, str(raw["currency"]), direction, category)


def rows_of(arguments: Any, name: str) -> tuple[dict[str, Any], list[RowIn]]:
    """The checked arguments of a loose-rows tool and its rows."""
    found = _object(arguments, name)
    cash = name == CASH
    raw = found["entries" if cash else "charges"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= ROWS_MAX:
        raise ToolInputError(f"between 1 and {ROWS_MAX} rows")
    return found, [_row(r, f"row {i}", cash) for i, r in enumerate(raw)]


def statement_of(arguments: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """The checked arguments of `import_statement` and the statement payload (without the
    title, explanation and account), checked in depth by `web.imports`."""
    found = _object(arguments, STATEMENT)
    if not isinstance(found["account"], str):
        raise ToolInputError("account must be a key from list_accounts")
    payload = {k: v for k, v in found.items() if k not in ("title", "explanation", "account")}
    return found, payload
