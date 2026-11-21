"""Route of the month's spending pace (see `web.pace`)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Annotated

from fastapi import FastAPI, Query
from pydantic import BaseModel

from michelito.analysis import accounts as account_data
from michelito.analysis import rates
from michelito.web import pace as pace_view
from michelito.web.review_routes import Connection, LoadFlow, ParseAccounts
from michelito.web.schemas import to_cents

# Years from 1000: a month before year 1 has no previous month to compare with.
_MONTH_PATTERN = r"^[1-9]\d{3}-(0[1-9]|1[0-2])$"


class OneOffOut(BaseModel):
    fingerprint: str
    day: str  # ISO
    merchant: str
    amount_cents: int


class PaceOut(BaseModel):
    month: str
    previous_month: str
    through_day: int  # days of the month counted (today's day in the current month)
    days_in_month: int
    current_cents: list[int]  # cumulative spending without one-offs, day 1 first
    previous_cents: list[int]  # the same for last month, every day
    total_to_date_cents: int  # with one-offs and provisional ones
    previous_same_day_cents: int  # last month without one-offs, up to the same day
    previous_same_day_total_cents: int  # last month with one-offs, up to the same day
    one_offs: list[OneOffOut]
    finished: bool  # the month is over: compared with the whole of last month
    today: str  # ISO: the server's today (what "up to today" means)

    @classmethod
    def of(cls, p: pace_view.Pace, today: date) -> PaceOut:
        return cls(
            month=p.month,
            previous_month=p.previous_month,
            through_day=p.through_day,
            days_in_month=p.days_in_month,
            current_cents=[to_cents(v) for v in p.current],
            previous_cents=[to_cents(v) for v in p.previous],
            total_to_date_cents=to_cents(p.total_to_date),
            previous_same_day_cents=to_cents(p.previous_same_day),
            previous_same_day_total_cents=to_cents(p.previous_same_day_total),
            one_offs=[
                OneOffOut(
                    fingerprint=o.fingerprint,
                    day=o.day.isoformat(),
                    merchant=o.merchant,
                    amount_cents=to_cents(o.amount),
                )
                for o in p.one_offs
            ],
            finished=p.finished,
            today=today.isoformat(),
        )


def register(
    app: FastAPI,
    connection: Connection,
    load_flow: LoadFlow,
    parse_accounts: ParseAccounts,
    today: Callable[[], date],
) -> None:
    @app.get("/api/summary/pace")
    def get_pace(
        month: Annotated[str, Query(pattern=_MONTH_PATTERN)],
        accounts: Annotated[str | None, Query(max_length=2000)] = None,
    ) -> PaceOut:
        """Cumulative spending per day of `month` against the previous month, up to today."""
        now = today()
        with connection() as conn:
            movements = load_flow(conn)
            infos = account_data.account_infos(conn)
            selected = parse_accounts(accounts, infos)
            by_month = rates.load(conn)
        built = pace_view.build_pace(movements, infos, by_month, month, now, selected)
        return PaceOut.of(built, now)
