"""Coverage report: what is in the database, what failed and what is missing."""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from michelito.config import COMMIT_FROM, NOTICE_LOOKBACK_DAYS, OVERDUE_DAYS
from michelito.db import FAILED_PART_STATUSES, PRINTOUT_PARSERS

_FAILED = ("invalid", "error")
_DETAIL_LIMIT = 200
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")

Part = tuple[list[str], list[str]]  # lines, alerts


@dataclass(frozen=True)
class Report:
    lines: tuple[str, ...]
    alerts: tuple[str, ...]

    @property
    def text(self) -> str:
        tail = (
            ["", "Alerts:", *(f"  - {a}" for a in self.alerts)]
            if self.alerts
            else ["", "No alerts."]
        )
        return "\n".join([*self.lines, *tail])


def build_report(
    conn: sqlite3.Connection,
    today: date,
    *,
    commit_from: date = COMMIT_FROM,
    overdue_days: int = OVERDUE_DAYS,
) -> Report:
    parts = (
        _documents(conn),
        _coverage(conn, today, commit_from, overdue_days),
        _failures(conn, commit_from),
        _notices(conn, today),
    )
    return Report(
        lines=tuple(line for lines, _ in parts for line in lines),
        alerts=tuple(alert for _, alerts in parts for alert in alerts),
    )


def missing_months(period_ends: list[date], commit_from: date) -> list[str]:
    """Months without a statement between the start of the committed window and the last closing."""
    have = {(d.year, d.month) for d in period_ends}
    start = max(period_ends[0], commit_from)
    cursor, last = (start.year, start.month), (period_ends[-1].year, period_ends[-1].month)
    missing = []
    while cursor <= last:
        if cursor not in have:
            missing.append(f"{cursor[0]}-{cursor[1]:02d}")
        year, month = cursor
        cursor = (year + month // 12, month % 12 + 1)
    return missing


def _documents(conn: sqlite3.Connection) -> Part:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM documents GROUP BY status ORDER BY status"
    ).fetchall()
    lines = (
        ["Documents:", *(f"  {r['status']}: {r['n']}" for r in rows)]
        if rows
        else ["Documents: none yet."]
    )
    return lines, []


def _coverage(conn: sqlite3.Connection, today: date, commit_from: date, overdue_days: int) -> Part:
    marks = ", ".join("?" for _ in PRINTOUT_PARSERS)
    rows = conn.execute(
        "SELECT a.name, s.currency, s.period_end FROM statements s "
        f"JOIN accounts a ON a.id = s.account_id WHERE s.parser NOT IN ({marks}) "
        "ORDER BY a.name, s.currency, s.period_end",
        PRINTOUT_PARSERS,  # a printout is not a closing
    ).fetchall()
    periods: dict[tuple[str, str], list[date]] = defaultdict(list)
    for row in rows:
        periods[(row["name"], row["currency"])].append(date.fromisoformat(row["period_end"]))
    lines, alerts = ["", "Coverage by account:"], []
    for (name, currency), ends in periods.items():
        label = f"{name} {currency}"
        age = (today - ends[-1]).days
        lines.append(
            f"  {label}: {len(ends)} closings, {ends[0]:%Y-%m} to {ends[-1]:%Y-%m}, "
            f"last one {age} days ago"
        )
        missing = missing_months(ends, commit_from)
        if missing:
            lines.append(f"    no statement since {commit_from:%Y-%m}: {', '.join(missing)}")
            alerts.append(f"{label}: {len(missing)} months missing since {commit_from:%Y-%m}")
        if age > overdue_days:
            alerts.append(f"{label}: the last statement is {age} days old")
    if not periods:
        lines.append("  (no validated statements)")
    return lines, alerts


def _failures(conn: sqlite3.Connection, commit_from: date) -> Part:
    rows = conn.execute(
        "SELECT filename, source, status, detail, received_at FROM documents "
        "WHERE status IN ('invalid', 'error', 'unsupported') ORDER BY received_at"
    ).fetchall()
    window = commit_from.isoformat()
    recent = [r for r in rows if r["received_at"] >= window]
    old = [r for r in rows if r["received_at"] < window]
    lines, alerts = ["", f"Documents not parsed since {commit_from:%Y-%m}:"], []
    for row in recent:
        entry = (
            f"{clean(row['filename'])} ({row['source']}, {row['status']}): {_short(row['detail'])}"
        )
        lines.append(f"  {entry}")
        if row["status"] in _FAILED:
            alerts.append(entry)
    parts = _failed_parts(conn, window)
    for row in parts:
        entry = (
            f"{clean(row['filename'])} ({row['source']}, part {clean(row['label'])}, "
            f"{row['status']}): {_short(row['detail'])}"
        )
        lines.append(f"  {entry}")
        alerts.append(entry)
    if not recent and not parts:
        lines.append("  none")
    noted = conn.execute(
        "SELECT d.filename, p.label, p.note FROM document_parts p "
        "JOIN documents d ON d.id = p.document_id "
        "WHERE p.note IS NOT NULL AND d.received_at >= ? ORDER BY d.received_at, p.part",
        (window,),
    ).fetchall()
    if noted:
        lines.append(
            "Statements saved with a note (they balance; the printed count does not match):"
        )
        lines.extend(
            f"  {clean(r['filename'])} (part {clean(r['label'])}): {_short(r['note'])}"
            for r in noted
        )
    if old:
        counts: defaultdict[str, int] = defaultdict(int)
        for row in old:
            counts[row["status"]] += 1
        summary = ", ".join(f"{status} {n}" for status, n in sorted(counts.items()))
        lines.append(f"Older documents not parsed: {summary}")
    return lines, alerts


def _failed_parts(conn: sqlite3.Connection, window: str) -> list[sqlite3.Row]:
    """Parts that failed in a PDF with several statements whose document did get in (if none
    got in, the document itself already shows as failed)."""
    marks = ", ".join("?" for _ in FAILED_PART_STATUSES)
    return conn.execute(
        "SELECT d.filename, d.source, p.label, p.status, p.detail FROM document_parts p "
        "JOIN documents d ON d.id = p.document_id "
        f"WHERE p.status IN ({marks}) AND d.status NOT IN ('invalid', 'error', 'unsupported') "
        "AND d.received_at >= ? ORDER BY d.received_at, p.part",
        (*FAILED_PART_STATUSES, window),
    ).fetchall()


def _notices(conn: sqlite3.Connection, today: date) -> Part:
    since = (today - timedelta(days=NOTICE_LOOKBACK_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT source, subject, received_at FROM gmail_messages "
        "WHERE attachments_saved = 0 AND received_at >= ? ORDER BY received_at",
        (since,),
    ).fetchall()
    if not rows:
        return [], []
    lines = ["", f"Emails without an attachment in the last {NOTICE_LOOKBACK_DAYS} days:"]
    lines.extend(f"  {r['received_at'][:10]} {r['source']}: {clean(r['subject'])}" for r in rows)
    return lines, []


def _short(detail: str | None) -> str:
    text = clean(detail or "")
    return text if len(text) <= _DETAIL_LIMIT else text[: _DETAIL_LIMIT - 1] + "…"


def clean(text: str) -> str:
    """Strip control characters: the subject or the PDF could carry terminal sequences."""
    return _CONTROL.sub("?", text)
