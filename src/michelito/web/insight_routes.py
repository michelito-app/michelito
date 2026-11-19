"""Routes of the saved insights (see `analysis.insights` and `michelito.dossier`)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi import Path as PathParam
from fastapi.responses import Response
from pydantic import BaseModel, Field

from michelito import dossier
from michelito.analysis import accounts as account_data
from michelito.analysis import insights, transfers
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web.dossier_routes import HASH_PATTERN, AccountKey
from michelito.web.review_routes import Connection, LoadFlow
from michelito.web.summary import month_label

Month = Annotated[str, PathParam(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
Holders = Callable[[], transfers.Holders]


class InsightOut(BaseModel):
    month: str
    label: str
    text: str  # Markdown
    accounts: list[str] | None  # accounts analysed; None: all
    created_at: str
    updated_at: str
    stale: bool  # the data changed since this insight


class InsightBody(BaseModel):
    text: str
    # "Copy for Claude": the pasted answer is a new insight (it replaces the saved one), with the
    # accounts of the copied dossier (None: all; when missing, those of its header) and that
    # dossier's fingerprint (`X-Michelito-Fingerprint`; without it, today's). Without `fresh`, as
    # always.
    fresh: bool = False
    accounts: list[AccountKey] | None = Field(default=None, max_length=200)
    fingerprint: str | None = Field(default=None, pattern=HASH_PATTERN)


def _pasted(body: InsightBody, month: str) -> tuple[str, list[str] | None]:
    """The text without the dossier header, and the accounts analysed. ValueError if the header
    is for another month or its accounts are not those of `accounts`."""
    pasted = dossier.split_header(body.text, month)
    if "accounts" not in body.model_fields_set:
        return pasted.text, pasted.accounts
    given = sorted(set(body.accounts)) if body.accounts else None
    if pasted.has_header and given != pasted.accounts:
        raise ValueError(t("web.insight.accounts_mismatch"))
    return pasted.text, given


def _check_accounts(conn: sqlite3.Connection, keys: list[str] | None) -> None:
    """ValueError if an account does not exist (with a fingerprint the dossier is not built)."""
    known = {info.key for info in account_data.account_infos(conn)}
    unknown = sorted(set(keys or ()) - known)
    if unknown:
        raise ValueError(t("dossier.unknown_accounts", accounts=", ".join(unknown)))


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow, holders: Holders) -> None:
    def fresh(conn: sqlite3.Connection, flow: Sequence[Movement], found: insights.Insight) -> bool:
        """Whether the data did not change since the insight (see `insights.is_fresh`)."""
        accounts = list(found.accounts) if found.accounts else None
        try:
            built = dossier.build(conn, found.month, accounts=accounts, flow=flow)
        except (ValueError, LookupError):
            return False  # the month has no data anymore or an account stopped existing
        return insights.is_fresh(conn, found, built.data_hash, lambda: built.legacy_hash)

    def out(
        conn: sqlite3.Connection, flow: Sequence[Movement], found: insights.Insight
    ) -> InsightOut:
        return InsightOut(
            month=found.month,
            label=month_label(found.month),
            text=found.text,
            accounts=None if found.accounts is None else list(found.accounts),
            created_at=found.created_at,
            updated_at=found.updated_at,
            stale=not fresh(conn, flow, found),
        )

    @app.get("/api/insights")
    def get_insights() -> list[InsightOut]:
        """From the most recent month to the oldest."""
        with connection() as conn:
            flow = load_flow(conn)
            return [out(conn, flow, found) for found in insights.list_all(conn)]

    @app.get("/api/insights/{month}")
    def get_insight(month: Month) -> InsightOut:
        with connection() as conn:
            found = insights.get(conn, month)
            if found is None:
                raise HTTPException(404, t("web.insight.not_found"))
            return out(conn, load_flow(conn), found)

    @app.put("/api/insights/{month}")
    def put_insight(month: Month, body: InsightBody) -> InsightOut:
        """Edits the text (the fingerprint stays the insight's) or creates one with the fingerprint
        of today's data (every account). With `fresh`, saves it (or replaces it) as a new insight
        of `accounts` with `fingerprint` (the copied dossier's) or, without it, today's."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with connection() as conn:
            flow = load_flow(conn)
            try:
                with conn:
                    if body.fresh:
                        raw, keys = _pasted(body, month)
                        text = insights.clean_text(raw)
                        if body.fingerprint is not None:
                            _check_accounts(conn, keys)
                            data_hash = body.fingerprint
                        else:
                            built = dossier.build(conn, month, accounts=keys, flow=flow)
                            data_hash = built.data_hash
                        insights.save(conn, month, text, data_hash, keys, now)
                    elif insights.get(conn, month) is not None:
                        insights.edit_text(conn, month, body.text, now)
                    else:
                        insights.clean_text(body.text)
                        built = dossier.build(conn, month, holders=holders(), flow=flow)
                        insights.save(conn, month, body.text, built.data_hash, None, now)
            except LookupError:
                raise HTTPException(404, t("web.no_data")) from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            found = insights.get(conn, month)
            assert found is not None
            return out(conn, flow, found)

    @app.delete("/api/insights/{month}", status_code=204)
    def delete_insight(month: Month) -> Response:
        with connection() as conn, conn:
            removed = insights.delete(conn, month)
        if not removed:
            raise HTTPException(404, t("web.insight.not_found"))
        return Response(status_code=204)
