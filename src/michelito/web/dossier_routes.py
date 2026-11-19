"""The "Copy for Claude" data: the month's dossier and the fixed prompt, read-only.

`GET /api/dossier?month=YYYY-MM&accounts=k1,k2` returns the Markdown of `michelito.dossier` as
is (with `DATA_NOTICE`, the ```text blocks and the cuts) from the request's database (in the
demo, the visitor's copy). Only the month and the accounts go in the URL. The interface puts the
prompt (`analysis.claude_prompt`) and the dossier together on the clipboard; nothing is sent
out.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, StringConstraints

from michelito import dossier
from michelito.analysis import claude_prompt
from michelito.i18n import t
from michelito.web.review_routes import Connection, LoadFlow

_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
HASH_HEADER = "X-Michelito-Fingerprint"
HASH_PATTERN = rf"^[0-9a-f]{{{dossier.HASH_LENGTH}}}$"
ACCOUNT_KEY_MAX = 100  # maximum length of a requested account key (real ones are short)
AccountKey = Annotated[str, StringConstraints(min_length=1, max_length=ACCOUNT_KEY_MAX)]
_NO_STORE = {"Cache-Control": "no-store"}


class PromptOut(BaseModel):
    text: str


def account_keys(raw: str | None) -> list[str] | None:
    """The requested keys, deduplicated and sorted; None if none was requested (all). 422 if any
    is longer than `ACCOUNT_KEY_MAX`."""
    keys = sorted({key.strip() for key in (raw or "").split(",") if key.strip()})
    if any(len(key) > ACCOUNT_KEY_MAX for key in keys):
        raise HTTPException(422, t("web.dossier.account_key_too_long", max=ACCOUNT_KEY_MAX))
    return keys or None


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow) -> None:
    @app.get("/api/dossier/prompt")
    def get_prompt() -> PromptOut:
        """The default prompt that goes with the dossier (it opens no database)."""
        return PromptOut(text=claude_prompt.INSTRUCTION)

    @app.get("/api/dossier")
    def get_dossier(
        month: Annotated[str, Query(pattern=_MONTH_PATTERN)],
        accounts: Annotated[str | None, Query(max_length=2000)] = None,
    ) -> Response:
        """The month's dossier in Markdown; 422 if an account does not exist, 404 without data."""
        with connection() as conn:
            try:
                built = dossier.build(
                    conn, month, accounts=account_keys(accounts), flow=load_flow(conn)
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            except LookupError:
                raise HTTPException(404, t("web.no_data")) from None
        return Response(
            built.markdown,
            media_type="text/markdown; charset=utf-8",
            headers={**_NO_STORE, HASH_HEADER: built.data_hash},
        )
