"""A month's dossier to analyze with Claude Code (`michelito analysis YYYY-MM`).

It gathers what the board already computes (Summary, "what happened", "to review", shared
expenses and exchanges) with the full descriptions of the main movements. Privacy: it only reads
the database and the holders; never the keyring (neither the PDF password nor the Gmail token)
nor the paths of the documents in raw/.

`data_hash` fingerprints the data: it is saved with the analysis to tell when the data changed
afterwards. Amounts, categories, descriptions, one-offs, links (shared, reimbursements,
exchanges) and what enters "to review" change it; what is marked as reviewed and the user's
notes do not (they are interface annotations).

The data uses English keys; the Markdown is Spanish text from the catalog (`michelito.i18n`).
Insights saved before the English rename hold the hash of the old Spanish-keyed data:
`Dossier.legacy_hash` recomputes it (see `legacy.dossier_data`) so they stay fresh.

Security (prompt injection): descriptions, merchants, notes, category and account names come
from the banks or the user and Claude Code reads them. In the Markdown they go inside ```text
blocks preceded by the data notice, without backticks or active Markdown marks (see `_cell`); in
the data (and in JSON) they are plain text. All such text is cut to TEXT_MAX_CHARS.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import cached_property
from typing import Any

from michelito import legacy
from michelito.analysis import accounts as account_data
from michelito.analysis import categories, ledger_store, links, rates, review_marks, transfers
from michelito.analysis import one_off_dismissals as dismissals
from michelito.analysis import recurring_marks as marks
from michelito.analysis.rates import rate_for, to_dop
from michelito.analysis.spending import Movement, load_all
from michelito.i18n import t
from michelito.web import links as links_view
from michelito.web import review as review_view
from michelito.web import summary

TOP_EXPENSES = 15
TOP_INCOMES = 10
TOP_THIRD_PARTY = 10
HASH_LENGTH = 16

TEXT_MAX_CHARS = 120
ALL_ACCOUNTS = "all"  # in the dossier header: no --accounts
SAVE_COMMAND = "michelito insight save"
SAVE_FILE = "analysis.md"
# The warning that precedes every block of bank and user text.
DATA_NOTICE = t("dossier.data_notice")
# User notes: interface annotations, left out of the hash (like what is reviewed).
_UNHASHED = {"transactions": "note", "to_review": "reviewed"}

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class Dossier:
    month: str
    data: dict[str, Any]
    markdown: str
    data_hash: str
    renamed: frozenset[str] = frozenset()  # what schema 23 renamed here (`cash_renames`)

    @cached_property
    def legacy_hash(self) -> str:
        """The hash the release before the English rename computed for the same data (what an
        insight saved back then stores)."""
        return _digest(legacy.dossier_data(_hashed(self.data), self.renamed))

    @cached_property
    def older_hashes(self) -> tuple[str, ...]:
        """The hashes earlier releases computed for the same data: before the English rename
        and, if schema 23 renamed the cash names here, schemas 18 to 22 (English keys, old cash
        names). An insight saved back then is still fresh."""
        found = [self.legacy_hash]
        if self.renamed:
            old = legacy.old_cash_names(_hashed(self.data), self.renamed)
            assert isinstance(old, dict)
            found.append(_digest(old))
        return tuple(found)


def build(
    conn: sqlite3.Connection,
    month: str,
    *,
    accounts: Collection[str] | None = None,
    holders: Sequence[str] | transfers.Holders = (),
    flow: Sequence[Movement] | None = None,
) -> Dossier:
    """The month's dossier. ValueError if an account does not exist; LookupError without data.

    `flow`: the movements already loaded (`spending.load_all` with the same holders), so they
    are not read again when several months are checked."""
    flow = load_all(conn, holders) if flow is None else flow
    infos = account_data.account_infos(conn)
    known = {info.key for info in infos}
    unknown = sorted(set(accounts or ()) - known)
    if unknown:
        raise ValueError(t("dossier.unknown_accounts", accounts=", ".join(unknown)))
    selected = summary.selection(infos, accounts) if accounts else None
    by_month = rates.load(conn)
    ctx = links_view.context(
        flow, links.load(conn), infos, by_month, suggest=False, book=ledger_store.load(conn)
    )
    built = summary.build_summary(
        flow, infos, by_month, month, selected, ctx.groups, ctx.exchange_states
    )
    review_ctx = review_view.Context(
        flow=flow,
        accounts=infos,
        rates=by_month,
        marks=marks.load_for(conn, flow),
        unions=marks.load_unions(conn),
        reviewed=review_marks.load(conn),
        dismissed=dismissals.load(conn),
        selected=selected,
        links=ctx.links,
    )
    labels = {info.key: info.label for info in infos}
    mine = [m for m in flow if selected is None or m.account in selected]
    data = {
        "month": month,
        "label": built.option.label,
        "partial": built.option.partial,
        "accounts": [_short(labels[k]) for k in sorted(selected or known, key=lambda k: labels[k])],
        "account_keys": None if selected is None else sorted(selected),
        "coverage": [
            {
                "account": _short(c.label),
                "through": c.through.isoformat() if c.through else None,
                "complete": c.complete,
            }
            for c in built.coverage
        ],
        "totals": _totals(built),
        "categories": [_category(line) for line in built.categories],
        "trend": [_trend(point) for point in built.trend],
        "what_happened": [_contribution(c) for c in built.what_happened],
        "transactions": _movements(mine, month, by_month, labels),
        "to_review": [_review(v) for v in review_view.month_items(review_ctx, month)],
        "shared_and_exchanges": {
            "owed_to_me": _money(built.owed),
            "exchanges_pending": _money(built.exchanges_pending),
        },
    }
    return Dossier(month, data, to_markdown(data), data_hash(data), _renamed(conn))


def _renamed(conn: sqlite3.Connection) -> frozenset[str]:
    """What schema 23 renamed in this database (`migrations_v23`)."""
    return frozenset(str(row[0]) for row in conn.execute("SELECT what FROM cash_renames"))


def data_hash(data: dict[str, Any]) -> str:
    """The data's hash; what is marked as reviewed and the notes do not count."""
    return _digest(_hashed(data))


def _hashed(data: dict[str, Any]) -> dict[str, Any]:
    """The data without the fields left out of the hash (`_UNHASHED`)."""
    return {
        **data,
        **{
            section: [{k: v for k, v in item.items() if k != field} for item in data[section]]
            for section, field in _UNHASHED.items()
        },
    }


def _digest(data: Mapping[str, Any]) -> str:
    text = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()[:HASH_LENGTH]


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(_CENT))


def _totals(s: summary.Summary) -> dict[str, Any]:
    """The Summary totals. "to_investments" (the month's contributions, which do not reduce what
    was left over) is there only if there were any: so the hash of the analyses of months without
    investments does not change."""
    found = {
        "income": _money(s.income),
        "income_through": s.income_through.isoformat() if s.income_through else None,
        "spent": _money(s.total),
        "spent_without_one_offs": _money(s.regular_total),
        "one_offs": _money(s.one_offs),
        "usual_spent": _money(s.habitual),
        "third_party_transfers": _money(s.third_party),
        "net": _money(s.net),
        "savings_rate_pct": None if s.savings_rate is None else round(s.savings_rate * 100, 1),
        "usd": _money(s.usd),
        "dop_per_usd": None if s.rate is None else str(s.rate.value),
    }
    if s.invested:
        found["to_investments"] = _money(s.invested)
    return found


def _category(line: summary.CategoryLine) -> dict[str, Any]:
    return {
        "category": _short(line.category),
        "amount": _money(line.amount),
        "usual": _money(line.habitual),
        "diff": _money(line.diff),
        "same_as_usual": line.same,
        "purchases": line.purchases,
        "usual_purchases": line.habitual_purchases,
        "one_offs": _money(line.one_offs),
    }


def _trend(point: summary.MonthTotal) -> dict[str, Any]:
    return {
        "month": point.month,
        "spent": _money(point.total),
        "income": _money(point.income),
        "in_progress": point.partial,
        "spent_flag": point.spent_flag,
        "income_flag": point.income_flag,
    }


def _contribution(c: Any) -> dict[str, Any]:
    return {
        "side": c.side,
        "merchant": _short(c.merchant),
        "category": _short(c.category),
        "amount": _money(c.amount),
        "usual": _money(c.habitual),
        "diff": _money(c.diff),
        "description": _short(c.description),
    }


def _movements(
    mine: Sequence[Movement], month: str, by_month: dict[str, rates.Rate], labels: dict[str, str]
) -> list[dict[str, Any]]:
    """The movements that weigh the most: expenses, income and third-party transfers."""
    rate = rate_for(by_month, month)
    current = [(m, to_dop(m.amount, m.currency, rate)) for m in mine if m.month == month]

    def top(items: list[tuple[Movement, Decimal | None]], limit: int) -> list[Movement]:
        ranked = sorted(items, key=lambda p: (-(abs(p[1]) if p[1] is not None else 0), p[0].day))
        return [m for m, _ in ranked[:limit]]

    expenses = top([p for p in current if p[0].kind == "expense" and p[0].amount > 0], TOP_EXPENSES)
    incomes = top([p for p in current if p[0].kind == "income"], TOP_INCOMES)
    third = top(
        [p for p in current if p[0].kind == "transfer" and p[0].ref == categories.THIRD_PARTY],
        TOP_THIRD_PARTY,
    )
    chosen = sorted({m.fingerprint: m for m in (*expenses, *incomes, *third)}.values(), key=_order)
    dop = {m.fingerprint: v for m, v in current}
    return [_movement(m, dop[m.fingerprint], labels) for m in chosen]


def _order(move: Movement) -> tuple[str, str]:
    return (move.day.isoformat(), move.fingerprint)


def _movement(move: Movement, dop: Decimal | None, labels: dict[str, str]) -> dict[str, Any]:
    return {
        "date": move.day.isoformat(),
        "description": _short(move.description),
        "merchant": _short(move.merchant),
        "category": _short(move.category),
        "kind": move.kind,
        "account": _short(labels.get(move.account, move.account)),
        "amount": _money(move.amount),
        "currency": move.currency,
        "amount_dop": _money(dop),
        "one_off": move.one_off,
        "link": move.link or None,
        "note": _short(move.note) if move.note else None,
        "fingerprint": move.fingerprint,
    }


def _review(view: review_view.ReviewView) -> dict[str, Any]:
    item = view.item
    return {
        "kind": item.kind,
        "date": item.day.isoformat(),
        "description": _short(item.description),
        "account": _short(view.account_label),
        "amount": _money(item.amount),
        "currency": item.currency,
        "amount_dop": _money(item.amount_dop),
        "reason": _short(item.reason, 2 * TEXT_MAX_CHARS),
        "reviewed": item.reviewed,
        "fingerprint": item.fingerprint,
    }


def _short(text: str, limit: int = TEXT_MAX_CHARS) -> str:
    """Cuts an outside text (bank or user) to `limit` characters, with "…"."""
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


# What could close the data block or read as markup: replaced or escaped.
_REPLACE = str.maketrans({"`": "'", "|": "/", "<": "‹", ">": "›", "[": "(", "]": ")"})
_ESCAPE = re.compile(r"([\\*_#~])")


def _cell(value: Any) -> str:
    """A table cell as plain text: one line, no backticks (it cannot close the ``` block), no
    `|`, `<>` or `[]`, and with `\\ * _ # ~` escaped."""
    text = "—" if value is None else " ".join(str(value).split())
    return _ESCAPE.sub(r"\\\1", text.translate(_REPLACE))


def _table(rows: list[dict[str, Any]], columns: Sequence[str]) -> list[str]:
    """A data table inside a ```text block, after the notice that it is data. `columns`: the data
    keys shown; each title is `dossier.column.<key>` in the catalog."""
    if not rows:
        return [t("dossier.empty")]
    head = "| " + " | ".join(t(f"dossier.column.{key}") for key in columns) + " |"
    rule = "|" + "|".join(" --- " for _ in columns) + "|"
    body = ["| " + " | ".join(_cell(row.get(key)) for key in columns) + " |" for row in rows]
    return [DATA_NOTICE, "```text", head, rule, *body, "```"]


def header(month: str, accounts: Sequence[str] | None) -> str:
    """The dossier's first line: `michelito insight save` reads it if it comes in the analysis."""
    keys = ",".join(accounts) if accounts else ALL_ACCOUNTS
    return f"<!-- michelito dossier: month={month} accounts={keys} -->"


HEADER = re.compile(r"<!--\s*michelito dossier: month=(\S+) accounts=(\S+)\s*-->")


@dataclass(frozen=True)
class Pasted:
    """An analysis that may bring the dossier header (read by `split_header`)."""

    text: str  # without the header
    accounts: list[str] | None  # the header's (None: all, or no header)
    has_header: bool


def _find_header(text: str) -> tuple[re.Match[str], str, list[str] | None] | None:
    """The header in `text` (this release's or the one before the rename): the match, its month
    and its account keys (None: all)."""
    found = HEADER.search(text)
    if found is not None:
        raw = found.group(2)
        return found, found.group(1), None if raw == ALL_ACCOUNTS else raw.split(",")
    old = legacy.DOSSIER_HEADER.search(text)
    if old is None:
        return None
    raw = old.group(2)
    keys = (
        None
        if raw == legacy.DOSSIER_ALL_ACCOUNTS
        else [legacy.translate_key(k) for k in raw.split(",")]
    )
    return old, old.group(1), keys


def split_header(text: str, month: str) -> Pasted:
    """Removes the dossier header if it came in the analysis and reads its accounts. ValueError if
    it is another month's dossier. (Used by `michelito insight save` and the interface's paste.)
    The header written before the English rename is accepted too."""
    found = _find_header(text)
    if found is None:
        return Pasted(text, None, False)
    match, found_month, keys = found
    if found_month != month:
        raise ValueError(t("dossier.other_month", found=found_month, month=month))
    accounts = None if keys is None else sorted(keys)
    return Pasted(text[: match.start()] + text[match.end() :], accounts, True)


# The totals in the order they are written; the label of each is `dossier.total.<key>`.
_TOTAL_LABELS = "dossier.total."


def to_markdown(data: dict[str, Any]) -> str:
    """The dossier in Markdown, to read it (and for Claude Code to analyze it)."""
    month = data["month"]
    totals = data["totals"]
    keys = data["account_keys"]
    save = f"{SAVE_COMMAND} {month}" + (f" --accounts {','.join(keys)}" if keys else "")
    shared = data["shared_and_exchanges"]
    lines = [
        header(month, keys),
        t("dossier.title", label=data["label"]),
        "",
        f"> {DATA_NOTICE} {t('dossier.blocks_note')}",
        "",
        t("dossier.accounts", accounts=_cell(", ".join(data["accounts"]))),
        t("dossier.partial") if data["partial"] else t("dossier.complete"),
        "",
        t("dossier.section.totals"),
        *[f"- {t(_TOTAL_LABELS + key)}: {_cell(value)}" for key, value in totals.items()],
        "",
        t("dossier.section.categories"),
        *_table(
            data["categories"],
            (
                "category",
                "amount",
                "usual",
                "diff",
                "purchases",
                "one_offs",
            ),
        ),
        "",
        t("dossier.section.trend"),
        *_table(
            data["trend"],
            (
                "month",
                "spent",
                "income",
                "in_progress",
                "spent_flag",
                "income_flag",
            ),
        ),
        "",
        t("dossier.section.what_happened"),
        *_table(
            [{**row, "side": t(f"dossier.side.{row['side']}")} for row in data["what_happened"]],
            (
                "side",
                "merchant",
                "amount",
                "usual",
                "diff",
            ),
        ),
        "",
        t("dossier.section.transactions"),
        *_table(
            [{**row, "kind": t(f"dossier.kind.{row['kind']}")} for row in data["transactions"]],
            (
                "date",
                "description",
                "category",
                "kind",
                "account",
                "amount",
                "currency",
                "amount_dop",
                "note",
            ),
        ),
        "",
        t("dossier.section.to_review"),
        *_table(
            [{**row, "kind": t(f"dossier.review_kind.{row['kind']}")} for row in data["to_review"]],
            (
                "kind",
                "date",
                "description",
                "amount",
                "currency",
                "reason",
                "reviewed",
            ),
        ),
        "",
        t("dossier.section.shared"),
        t("dossier.owed_to_me", amount=shared["owed_to_me"]),
        t("dossier.exchanges_pending", amount=shared["exchanges_pending"]),
        "",
        "---",
        t("dossier.save_hint", command=f"{save} --file {SAVE_FILE}"),
        "",
    ]
    return "\n".join(lines)
