"""Change-log routes: `GET /api/log` (paged, with filters), `PATCH /api/log/{id}` (the
reason), `POST /api/log/{id}/undo` and a transaction's history.

The logic lives in `analysis.changelog` (database) and `analysis.changelog_rules` (pure); this
module builds the response with each entry's undo state and its editing session.
"""

from __future__ import annotations

import sqlite3
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from michelito.analysis import catalog, changelog, changelog_ledger, changelog_rules, live_match
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web.log_schemas import EntryOut, HistoryOut, LogOut, ReasonBody, RuleHintOut, Toggle

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
PAGE = 50


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def matches(
    entry: changelog.Entry, kinds: set[str] | None, author: str | None, q: str | None
) -> bool:
    """The view's filters: kinds, author and text (merchant, before, after, reason)."""
    if kinds is not None and entry.kind not in kinds:
        return False
    if author is not None and entry.author != author:
        return False
    if not q or not q.strip():
        return True
    text = " ".join(
        (entry.subject, entry.before_text, entry.after_text, entry.reason or "", entry.target)
    )
    return _fold(q.strip()) in _fold(text)


def rule_suggestions(
    conn: sqlite3.Connection, flow: Sequence[Movement] = ()
) -> list[changelog_rules.RuleSuggestion]:
    """The merchant rules proposed today (for categories that can be chosen). `flow`: today's
    movements, to know the merchant of each transaction in a batch."""
    entries = [
        *changelog.load(conn, kind=changelog_rules.CATEGORY_KIND),
        *changelog.load(conn, kind=changelog_rules.BATCH_KIND),
    ]
    merchants = {m.fingerprint: m.merchant for m in flow}
    edits = changelog.category_edits(entries, changelog.undone(conn), merchants)
    found = changelog_rules.rule_suggestions(
        edits, changelog.merchant_rules(conn), changelog.rule_dismissals(conn)
    )
    known = catalog.load(conn)
    usable = {c.id for c in known.selectable()}
    return [s for s in found if s.category_id in usable]


def names(conn: sqlite3.Connection) -> changelog_ledger.Names:
    """Today's contacts and groups (for Shared's sentences and links)."""
    present = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'contacts'"
    ).fetchone()
    if present is None:
        return changelog_ledger.Names()
    contacts = {int(r[0]): str(r[1]) for r in conn.execute("SELECT id, name FROM contacts")}
    me = conn.execute("SELECT id FROM contacts WHERE is_me = 1").fetchone()
    groups = {int(r[0]): str(r[1]) for r in conn.execute("SELECT id, name FROM ledger_groups")}
    return changelog_ledger.Names(contacts, groups, None if me is None else int(me[0]))


def originals(entries: Sequence[changelog.Entry]) -> list[changelog.Entry]:
    """The entries the list shows: original changes (an "Undo" record stays under its original)."""
    return [e for e in entries if e.undoes is None]


def _rooted(
    state: changelog.UndoState, chains: changelog.Toggles, done: frozenset[int]
) -> changelog.UndoState:
    """The later change that blocks, as the list shows it: its original (never an audit record)
    and what to do with it first: undo it, or redo it if that original is undone now (what is in
    effect is its undo)."""
    if state.blocked_by is None:
        return state
    root = chains.root(state.blocked_by)
    redo = root in done
    if state.reason:
        key = "analysis.changelog.blocked_by_redo" if redo else "analysis.changelog.blocked_by"
        message = t(key, reason=state.reason, id=root)
    else:
        key = (
            "analysis.changelog.redo_later_first" if redo else "analysis.changelog.undo_later_first"
        )
        message = t(key, id=root)
    return changelog.UndoState(state.allowed, state.undone, root, message, state.reason)


def entry_views(
    conn: sqlite3.Connection,
    entries: Sequence[changelog.Entry],
    sessions_of: dict[int, changelog_rules.Session] | None = None,
    flow: Sequence[Movement] = (),
) -> list[EntryOut]:
    """The original entries with their state: undone or not, whether "Undo" (or "Redo") can be
    done now (tried with the days of `flow`, today's flow), how many times it toggled, and their
    transaction's month (or group, or person) for the link."""
    done = changelog.undone(conn)
    chains = changelog.toggles(conn)
    known = names(conn)
    present: Mapping[str, str] = {m.fingerprint: m.month for m in flow}
    days = {m.fingerprint: m.day for m in flow}
    views = []
    for entry in originals(entries):
        undone = entry.id in done
        state = (
            changelog.redo_state(conn, entry, done, chains, days)
            if undone
            else changelog.undo_state(conn, entry, done, days)
        )
        records = chains.records(entry.id)
        last = changelog.get(conn, records[-1]).at.isoformat() if records else None
        views.append(
            EntryOut.of(
                entry,
                _rooted(state, chains, done),
                None if sessions_of is None else sessions_of.get(entry.id),
                present,
                Toggle(undone=undone, count=len(records), last_at=last),
                known,
            )
        )
    return views


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow) -> None:
    @app.get("/api/log")
    def get_log(
        kind: Annotated[str | None, Query(max_length=400)] = None,
        author: Annotated[str | None, Query(pattern="^(user|claude)$")] = None,
        q: Annotated[str | None, Query(max_length=200)] = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = PAGE,
    ) -> LogOut:
        """The entries, newest first, with their session (computed over the whole log: the
        filters don't cut it). `kind`: comma-separated kinds."""
        kinds = {k.strip() for k in kind.split(",") if k.strip()} if kind else None
        with connection() as conn:
            entries = originals(changelog.load(conn))
            groups = changelog_rules.sessions([(e.id, e.at) for e in entries])
            sessions_of = {i: s for s in groups for i in s.ids}
            wanted = [e for e in entries if matches(e, kinds, author, q)]
            page = wanted[offset : offset + limit]
            items = entry_views(conn, page, sessions_of, load_flow(conn))
        return LogOut(
            items=items,
            total=len(wanted),
            offset=offset,
            kinds=sorted({e.kind for e in entries}),
        )

    @app.patch("/api/log/{entry_id}")
    def patch_log(entry_id: int, body: ReasonBody) -> EntryOut:
        """The reason (<= 500; empty deletes it). Editing it is not a change: it isn't logged."""
        with connection() as conn:
            try:
                with conn:
                    changelog.set_reason(conn, entry_id, body.reason)
            except LookupError:
                raise HTTPException(404, t("web.log.unknown_entry")) from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            return entry_views(conn, [changelog.get(conn, entry_id)], None, load_flow(conn))[0]

    def toggle(entry_id: int, redo: bool) -> EntryOut:
        with connection() as conn:
            days = {m.fingerprint: m.day for m in load_flow(conn)}
            try:
                with conn:
                    act = changelog.redo if redo else changelog.undo_original
                    made = act(conn, entry_id, days)
            except LookupError:
                raise HTTPException(404, t("web.log.unknown_entry")) from None
            except changelog.UndoBlocked as exc:
                raise HTTPException(409, str(exc)) from None
            if _touches_provisional(changelog.get(conn, made)):
                # A Discard or void undone may make a provisional visible again whose statement
                # already arrived: reconciling now confirms it instead of counting it twice.
                with conn:
                    live_match.reconcile(conn, changelog.now().isoformat())
            return entry_views(conn, [changelog.get(conn, entry_id)], None, load_flow(conn))[0]

    @app.post("/api/log/{entry_id}/undo")
    def post_undo(entry_id: int) -> EntryOut:
        """Undo an original change; return it with its new state (undone, "Redo"). The audit
        record is kept under it. 409 if it can no longer be undone (the message says which
        later change to undo first) or if `entry_id` is an audit record."""
        return toggle(entry_id, redo=False)

    @app.post("/api/log/{entry_id}/redo")
    def post_redo(entry_id: int) -> EntryOut:
        """Redo an undone original (apply the change again, recorded like an undo); 409 when a
        later change would be overwritten."""
        return toggle(entry_id, redo=True)

    @app.get("/api/transactions/{fingerprint}/history")
    def get_history(fingerprint: str) -> HistoryOut:
        """The entries touching the transaction and, if its merchant already got the same
        category by hand on others, that hint ("the other 2 times you put it in ...")."""
        with connection() as conn:
            flow = load_flow(conn)
            target = next((m for m in flow if m.fingerprint == fingerprint), None)
            if target is None:
                raise HTTPException(404, t("web.unknown_transaction"))
            items = entry_views(conn, changelog.load(conn, fingerprint), None, flow)
            hint = _hint(conn, target, flow)
        return HistoryOut(items=items, rule_hint=hint)

    def _hint(
        conn: sqlite3.Connection, target: Movement, flow: Sequence[Movement]
    ) -> RuleHintOut | None:
        known = catalog.load(conn)
        for found in rule_suggestions(conn, flow):
            category = known.by_id(found.category_id)
            if (
                found.merchant != target.merchant
                or target.fingerprint in found.fingerprints
                or category is None
                or category.ref == target.ref
            ):
                continue
            return RuleHintOut(
                merchant=found.merchant,
                category_id=category.id,
                category=category.name,
                count=found.count,
            )
        return None


def _touches_provisional(entry: changelog.Entry) -> bool:
    return any(change.table == "provisional_decisions" for change in entry.changes)
