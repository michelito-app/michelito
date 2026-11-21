"""What the cash account screen shows beyond the balance and the lines (schema 23): the schedules
with their next date, the occurrences waiting for an answer, the next one due (the Summary's
"Next"), whether the monthly reconcile is due, and the concepts written before (autocomplete).
Built from loaded data; no writes."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from michelito.analysis import (
    cash_activation,
    cash_box_store,
    cash_schedule,
    cash_schedule_store,
    catalog,
    corrections,
)
from michelito.analysis.cash_box import EntryState, ManualEntry, entry_state
from michelito.analysis.cash_schedule import Schedule

CONCEPTS_SHOWN = 50


@dataclass(frozen=True)
class ScheduleView:
    schedule: Schedule
    next_due: date | None
    finished: bool
    category: str
    category_id: int | None


@dataclass(frozen=True)
class OccurrenceView:
    entry: ManualEntry
    state: EntryState
    category: str
    category_id: int | None


@dataclass(frozen=True)
class Upcoming:
    schedule: Schedule
    day: date


@dataclass(frozen=True)
class Concept:
    concept: str
    kind: str  # "income" or "expense"
    currency: str
    category_id: int | None
    last_day: date


@dataclass(frozen=True)
class CashExtras:
    schedules: tuple[ScheduleView, ...]
    occurrences: tuple[OccurrenceView, ...]  # waiting for an answer, oldest first
    upcoming: Upcoming | None
    activated_on: date | None
    reconcile_due: bool
    last_reconciled: date | None


def extras(conn: sqlite3.Connection, entries: Sequence[ManualEntry], today: date) -> CashExtras:
    known = catalog.load(conn)
    fixes = corrections.load(conn, known)
    schedules = cash_schedule_store.load(conn)
    views = []
    for schedule in schedules:
        chosen = None if schedule.category_id is None else known.by_id(schedule.category_id)
        if chosen is None:
            ref = cash_box_store.implied_ref(fixes, known, schedule.entry_kind, schedule.concept)
            name, category_id = known.name_of(ref), _id(known, ref)
        else:
            name, category_id = chosen.name, chosen.id
        views.append(
            ScheduleView(
                schedule,
                cash_schedule.next_due(schedule, today),
                cash_schedule.finished(schedule, today),
                name,
                category_id,
            )
        )
    waiting = []
    for entry in entries:
        state = entry_state(entry, today)
        if state not in ("pending", "lapsed"):
            continue
        ref = fixes.transaction_category(entry.fingerprint) or cash_box_store.implied_ref(
            fixes, known, entry.kind, entry.concept
        )
        waiting.append(OccurrenceView(entry, state, known.name_of(ref), _id(known, ref)))
    waiting.sort(key=lambda item: (item.entry.day, item.entry.id))
    horizon = today + timedelta(days=cash_schedule.UPCOMING_DAYS)
    due = sorted(
        (
            (view.next_due, view.schedule.id, view.schedule)
            for view in views
            if view.next_due is not None and view.next_due <= horizon
        ),
        key=lambda item: (item[0], item[1]),
    )
    activated = cash_activation.activated_on(conn)
    last = last_reconciled(conn)
    return CashExtras(
        schedules=tuple(views),
        occurrences=tuple(waiting),
        upcoming=None if not due else Upcoming(due[0][2], due[0][0]),
        activated_on=activated,
        reconcile_due=reconcile_due(activated, last, today),
        last_reconciled=last,
    )


def _id(known: catalog.Catalog, ref: str) -> int | None:
    return next((c.id for c in known.items if c.ref == ref), None)


def last_reconciled(conn: sqlite3.Connection) -> date | None:
    row = conn.execute("SELECT MAX(day) FROM cash_reconciliations").fetchone()
    return None if row is None or row[0] is None else date.fromisoformat(row[0])


def reconcile_due(activated: date | None, last: date | None, today: date) -> bool:
    """The monthly "Reconcile cash" prompt: once the account was activated in an earlier
    month, until it is reconciled in the current one."""
    if activated is None:
        return False
    first = today.replace(day=1)
    if activated >= first:
        return False
    return last is None or last < first


def concepts(conn: sqlite3.Connection, entries: Sequence[ManualEntry]) -> tuple[Concept, ...]:
    """The concepts written before, most recent first, each with its last category and currency
    (for the autocomplete: picking one brings them). One per concept and kind (compared without
    case or accents)."""
    known = catalog.load(conn)
    fixes = corrections.load(conn, known)
    seen: set[tuple[str, str]] = set()
    found = []
    for entry in sorted(entries, key=lambda e: (e.day, e.id), reverse=True):
        if entry.concept is None or entry.kind == "initial":
            continue
        key = (catalog.fold(entry.concept), entry.kind)
        if key in seen:
            continue
        seen.add(key)
        ref = fixes.transaction_category(entry.fingerprint) or cash_box_store.implied_ref(
            fixes, known, entry.kind, entry.concept
        )
        found.append(Concept(entry.concept, entry.kind, entry.currency, _id(known, ref), entry.day))
        if len(found) >= CONCEPTS_SHOWN:
            break
    return tuple(found)
