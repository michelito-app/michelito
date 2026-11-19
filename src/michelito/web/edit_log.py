"""Edits of a transaction with their change-log entry (`analysis.changelog`).

`PATCH /api/transactions/{fingerprint}` can change the note, "one-off" and the category (this
one only or the whole merchant) at once: each becomes its own entry, all inside the caller's
SQLite transaction. Also here: the short text of each side ("Cash -> Delivery").
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from michelito.analysis import catalog, changelog
from michelito.analysis.changelog_rules import CATEGORY_KIND
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import transactions

NOTHING = "—"
_SHORT = 80


def subject(move: Movement) -> str:
    """How the log names the transaction: its merchant or, failing that, its description."""
    return move.merchant or move.description


def short(text: str | None) -> str:
    clean = " ".join((text or "").split())
    if not clean:
        return NOTHING
    return clean if len(clean) <= _SHORT else clean[: _SHORT - 1] + "…"


def yes_no(value: bool) -> str:
    return t("web.log.yes") if value else t("web.log.no")


def link_subject(conn: sqlite3.Connection, link_id: int) -> str:
    """A link's name in the log: its name, its "with whom" or its number."""
    row = conn.execute(
        "SELECT kind, name, with_whom FROM links WHERE id = ?", (link_id,)
    ).fetchone()
    if row is None:
        return t("web.log.link_number", label=t("web.log.link"), id=link_id)
    labels = {
        "shared": t("web.log.group"),
        "exchange": t("web.log.exchange"),
        "investment": t("web.log.investment"),
        "reserve": t("web.log.reserve"),
    }
    label = labels.get(row["kind"], t("web.log.link"))
    return row["name"] or row["with_whom"] or t("web.log.link_number", label=label, id=link_id)


def _rule_name(conn: sqlite3.Connection, known: catalog.Catalog, merchant: str) -> str:
    row = conn.execute(
        "SELECT category_id FROM merchant_categories WHERE merchant = ?", (merchant,)
    ).fetchone()
    found = None if row is None else known.by_id(int(row[0]))
    return t("web.log.no_rule") if found is None else found.name


def edit_transaction(
    conn: sqlite3.Connection,
    target: Movement,
    known: catalog.Catalog,
    chosen: int | None,
    one_off: bool | None,
    scope: transactions.Scope,
    note: str | None,
    flow: Sequence[Movement],
) -> None:
    """Note, one-off and category, each with its own entry (no real change, no entry)."""
    fp, name = target.fingerprint, subject(target)
    if note is not None:
        with changelog.track(
            conn,
            "note",
            "transaction",
            fp,
            name,
            before=short(target.note),
            after=short(note),
            merchant=target.merchant,
            fingerprints=[fp],
        ):
            transactions.apply_edit(conn, target, None, None, scope, note)
    if one_off is not None:
        with changelog.track(
            conn,
            "one_off",
            "transaction",
            fp,
            name,
            before=yes_no(target.one_off),
            after=yes_no(one_off),
            merchant=target.merchant,
            fingerprints=[fp],
        ):
            transactions.apply_edit(conn, target, None, one_off, scope)
    if chosen is None:
        return
    found = known.by_id(chosen)
    after = found.name if found is not None else str(chosen)
    if scope == "merchant":
        with changelog.track(
            conn,
            "merchant_rule",
            "merchant",
            target.merchant,
            target.merchant,
            before=_rule_name(conn, known, target.merchant),
            after=after,
            merchant=target.merchant,
            fingerprints=[m.fingerprint for m in flow if m.merchant == target.merchant],
        ):
            transactions.apply_edit(conn, target, chosen, None, scope)
        return
    with changelog.track(
        conn,
        CATEGORY_KIND,
        "transaction",
        fp,
        name,
        before=target.category,
        after=after,
        merchant=target.merchant,
        fingerprints=[fp],
    ):
        transactions.apply_edit(conn, target, chosen, None, scope)
