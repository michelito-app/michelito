"""Reading and writing cash schedules and answering their occurrences (schema 23; the dates are
in `cash_schedule`).

Nothing here commits: the caller opens the transaction (and the change log entry, for what the
user does). `materialize` is also called by the system on every load (`cash_activation.refresh`),
outside the change log: an occurrence appearing on its date is not something the user did.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from michelito.analysis import cash_box_store, catalog
from michelito.analysis.accounts import CASH_BOX_KEY
from michelito.analysis.cash_box import (
    ENTRY_CATEGORY_KIND,
    CashBoxError,
    check_concept,
    check_entry,
)
from michelito.analysis.cash_schedule import (
    Frequency,
    Schedule,
    ScheduleKind,
    check,
    entry_kind,
    materializable,
)
from michelito.i18n import t

Answer = Literal["confirm", "amount", "skip"]


@dataclass(frozen=True)
class ScheduleDraft:
    """What the user writes for a schedule (validated by `save`)."""

    kind: ScheduleKind
    concept: str
    amount: Decimal
    currency: str
    category_id: int | None
    frequency: Frequency
    start: date
    end: date | None = None
    max_count: int | None = None


def load(conn: sqlite3.Connection) -> tuple[Schedule, ...]:
    rows = conn.execute("SELECT * FROM cash_schedules ORDER BY id")
    return tuple(_schedule(row) for row in rows)


def get(conn: sqlite3.Connection, schedule_id: int) -> Schedule:
    row = conn.execute("SELECT * FROM cash_schedules WHERE id = ?", (schedule_id,)).fetchone()
    if row is None:
        raise LookupError(t("analysis.cash_schedule.unknown", id=schedule_id))
    return _schedule(row)


def _schedule(row: sqlite3.Row) -> Schedule:
    return Schedule(
        id=row["id"],
        kind=row["kind"],
        concept=row["concept"],
        amount=Decimal(row["amount_cents"]) / 100,
        currency=row["currency"],
        category_id=row["category_id"],
        frequency=row["frequency"],
        start=date.fromisoformat(row["start_day"]),
        end=None if row["end_day"] is None else date.fromisoformat(row["end_day"]),
        max_count=row["max_count"],
        paused=bool(row["paused"]),
        resume_day=None if row["resume_day"] is None else date.fromisoformat(row["resume_day"]),
        account_key=row["account_key"],
    )


def _checked(conn: sqlite3.Connection, draft: ScheduleDraft, today: date) -> tuple[str, int | None]:
    check(draft.kind, draft.frequency, draft.start, draft.end, draft.max_count, today)
    kind = entry_kind(draft.kind)
    check_entry(kind, draft.amount, draft.currency)
    concept = check_concept(draft.concept)
    category_id = None
    if draft.category_id is not None:
        found = catalog.load(conn).by_id(draft.category_id)
        if found is None or found.kind != ENTRY_CATEGORY_KIND[kind]:
            key = "income" if kind == "income" else "expense"
            raise CashBoxError(t(f"analysis.cash_box_store.category_must_be_{key}"))
        category_id = found.id
    return concept, category_id


def add(
    conn: sqlite3.Connection,
    draft: ScheduleDraft,
    today: date,
    account_key: str = CASH_BOX_KEY,
) -> int:
    """A new schedule (the box is created if missing). Returns its id; nothing is materialized
    here (the caller calls `materialize`)."""
    concept, category_id = _checked(conn, draft, today)
    cash_box_store.ensure_box(conn, account_key)
    now = _now()
    cursor = conn.execute(
        "INSERT INTO cash_schedules (account_key, kind, concept, amount_cents, currency, "
        "category_id, frequency, start_day, end_day, max_count, paused, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
        (
            account_key,
            draft.kind,
            concept,
            _cents(draft.amount),
            draft.currency,
            category_id,
            draft.frequency,
            draft.start.isoformat(),
            _day(draft.end),
            draft.max_count,
            now,
            now,
        ),
    )
    return int(cursor.lastrowid or 0)


def update(conn: sqlite3.Connection, schedule_id: int, draft: ScheduleDraft, today: date) -> None:
    """Changes everything but the kind. The occurrences already materialized keep their amount;
    the new one applies from the next one."""
    current = get(conn, schedule_id)
    if draft.kind != current.kind:
        raise CashBoxError(t("analysis.cash_schedule.kind_fixed"))
    concept, category_id = _checked(conn, draft, today)
    # An edit never creates past dates: occurrences start again from today, or from the day
    # after the last one there is (or was skipped), whichever is later.
    floor = max(day for day in (current.resume_day, today, _after_last(conn, schedule_id)) if day)
    conn.execute(
        "UPDATE cash_schedules SET concept = ?, amount_cents = ?, currency = ?, category_id = ?, "
        "frequency = ?, start_day = ?, end_day = ?, max_count = ?, resume_day = ?, updated_at = ? "
        "WHERE id = ?",
        (
            concept,
            _cents(draft.amount),
            draft.currency,
            category_id,
            draft.frequency,
            draft.start.isoformat(),
            _day(draft.end),
            draft.max_count,
            floor.isoformat(),
            _now(),
            schedule_id,
        ),
    )


def _after_last(conn: sqlite3.Connection, schedule_id: int) -> date | None:
    """The day after the schedule's last occurrence (written or skipped); None without any."""
    row = conn.execute(
        "SELECT MAX(day) FROM (SELECT occurrence_day AS day FROM cash_entries WHERE schedule_id = ?"
        " UNION ALL SELECT day FROM cash_skips WHERE schedule_id = ?)",
        (schedule_id, schedule_id),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return date.fromisoformat(row[0]) + timedelta(days=1)


def set_paused(conn: sqlite3.Connection, schedule_id: int, paused: bool, today: date) -> None:
    """Pause (no occurrence while paused) or resume (from `today` on: the dates missed while
    paused are not created)."""
    current = get(conn, schedule_id)
    if current.paused == paused:
        return
    resume = current.resume_day if paused else today
    conn.execute(
        "UPDATE cash_schedules SET paused = ?, resume_day = ?, updated_at = ? WHERE id = ?",
        (int(paused), _day(resume), _now(), schedule_id),
    )


def delete(conn: sqlite3.Connection, schedule_id: int) -> None:
    """Deletes the schedule and its skips; its past occurrences stay as they are, detached from
    it (one still waiting can still be answered; nothing new is created)."""
    get(conn, schedule_id)
    conn.execute("UPDATE cash_entries SET schedule_id = NULL WHERE schedule_id = ?", (schedule_id,))
    conn.execute("DELETE FROM cash_skips WHERE schedule_id = ?", (schedule_id,))
    conn.execute("DELETE FROM cash_schedules WHERE id = ?", (schedule_id,))


def skipped(conn: sqlite3.Connection) -> frozenset[tuple[int, date]]:
    return frozenset(
        (int(row[0]), date.fromisoformat(row[1]))
        for row in conn.execute("SELECT schedule_id, day FROM cash_skips")
    )


def materialize(
    conn: sqlite3.Connection, today: date, schedules: Sequence[Schedule] | None = None
) -> list[int]:
    """Creates the pending occurrence of every due date up to `today` that has none (and was
    not skipped). Idempotent: a second call creates nothing (and the unique index stops two at
    once). Returns the ids created."""
    drop_orphans(conn)
    found = load(conn) if schedules is None else schedules
    if not found:
        return []
    done = {
        (int(row[0]), date.fromisoformat(row[1]))
        for row in conn.execute(
            "SELECT schedule_id, occurrence_day FROM cash_entries WHERE schedule_id IS NOT NULL"
        )
    }
    skips = skipped(conn)
    due = [
        (schedule, day)
        for schedule in found
        for day in materializable(schedule, today)
        if (schedule.id, day) not in done and (schedule.id, day) not in skips
    ]
    if not due:  # the usual case on a load: read only, no write lock
        return []
    known = catalog.load(conn)
    made = []
    for schedule, day in due:
        category = schedule.category_id
        chosen = None if category is None else known.by_id(category)
        if chosen is None or chosen.kind != ENTRY_CATEGORY_KIND[schedule.entry_kind]:
            # Deleted, or its kind changed since: the concept's usual category.
            category = None
        made.append(
            cash_box_store.add_entry(
                conn,
                schedule.entry_kind,
                day,
                schedule.amount,
                schedule.currency,
                category=category,
                account_key=schedule.account_key,
                today=today,
                concept=schedule.concept,
                schedule_id=schedule.id,
                status="pending",
            )
        )
    return made


def drop_orphans(conn: sqlite3.Connection) -> list[int]:
    """Removes the occurrences still waiting for an answer whose schedule is gone without being
    deleted (its creation was undone): they never happened. Answered ones stay. Returns their
    ids."""
    orphans = [
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM cash_entries WHERE status = 'pending' AND schedule_id IS NOT NULL "
            "AND schedule_id NOT IN (SELECT id FROM cash_schedules)"
        )
    ]
    for entry_id in orphans:
        cash_box_store.delete_entry(conn, entry_id, remember=False)
    return orphans


def answer(
    conn: sqlite3.Connection,
    entry_id: int,
    action: Answer,
    amount: Decimal | None = None,
    today: date | None = None,
) -> None:
    """The user's answer on an occurrence: "Paid" / "Received" (`confirm`), another amount
    (`amount`, confirmed too) or "Not paid" / "It did not come" (`skip`: the occurrence is
    removed and remembered, so it is not created again)."""
    found = cash_box_store.entry(conn, entry_id)
    if found.occurrence_day is None:
        raise CashBoxError(t("analysis.cash_schedule.not_occurrence"))
    if action == "skip":
        cash_box_store.delete_entry(conn, entry_id)
        return
    if action == "amount":
        if amount is None:
            raise CashBoxError(t("analysis.cash_box.amount_positive"))
        cash_box_store.update_entry(
            conn, entry_id, found.day, amount, found.currency, today=today or found.day
        )
    cash_box_store.set_status(conn, entry_id, "confirmed")


def _day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _cents(amount: Decimal) -> int:
    return int(amount * 100)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")
