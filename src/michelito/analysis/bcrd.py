"""Monthly dollar averages published by the Central Bank (public data)."""

from __future__ import annotations

import http.client
import json
import re
import urllib.request
from datetime import date
from decimal import Decimal, InvalidOperation
from http.cookiejar import CookieJar
from urllib.parse import urlencode

BCRD_PAGE = "https://www.bancentral.gov.do/SectorExterno/HistoricoTasas"  # spanish-data
BCRD_URL = "https://www.bancentral.gov.do/Home/GetHistoricalExchangeRatesByAverage"
_FIRST_YEAR = 2018
_MONTHLY_MODE = "1"
_USER_AGENT = "michelito"
_ISO_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _build_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def fetch(url: str = BCRD_URL, timeout: float = 30, today: date | None = None) -> bytes:
    """Downloads the monthly averages; without the session cookie the BCRD answers empty."""
    today = today or date.today()
    opener = _build_opener()
    headers = {"User-Agent": _USER_AGENT}
    form = urlencode(
        {
            "fromDate": f"{_FIRST_YEAR}-01-01T00:00:00.000Z",
            "toDate": f"{today:%Y-%m}-01T00:00:00.000Z",
            "statisticMode": _MONTHLY_MODE,
            "purchaseColumnOrder": "",
            "sellingColumnOrder": "",
            "dateColumnOrder": "desc",
        }
    ).encode()
    request = urllib.request.Request(
        url,
        data=form,
        headers={
            **headers,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BCRD_PAGE,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        opener.open(urllib.request.Request(BCRD_PAGE, headers=headers), timeout=timeout).read()
        with opener.open(request, timeout=timeout) as response:
            body: bytes = response.read()
    except http.client.HTTPException as exc:  # truncated or malformed response
        raise OSError(str(exc)) from exc
    if not body.strip():
        raise OSError("the BCRD answered with no data")
    return body


def parse_monthly_averages(content: bytes) -> dict[str, Decimal]:
    """`{"YYYY-MM": average selling rate}` from the BCRD JSON response."""
    try:
        items = json.loads(content)["result"]["items"]
        values = {_month(item["date"]): Decimal(item["sellingValueFormatted"]) for item in items}
    except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
        raise ValueError("BCRD answer with an unexpected format") from exc
    if not values:
        raise ValueError("the BCRD returned no rates")
    if not all(v.is_finite() and v > 0 for v in values.values()):
        raise ValueError("BCRD answer with invalid rates")
    return values


def _month(iso_date: str) -> str:
    month = iso_date[:7]
    if not _ISO_MONTH.match(month):
        raise ValueError(iso_date)
    return month
