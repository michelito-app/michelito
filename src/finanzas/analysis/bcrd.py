"""Promedios mensuales del dólar publicados por el Banco Central (datos públicos)."""

from __future__ import annotations

import http.client
import json
import re
import urllib.request
from datetime import date
from decimal import Decimal, InvalidOperation
from http.cookiejar import CookieJar
from urllib.parse import urlencode

BCRD_PAGE = "https://www.bancentral.gov.do/SectorExterno/HistoricoTasas"
BCRD_URL = "https://www.bancentral.gov.do/Home/GetHistoricalExchangeRatesByAverage"
_FIRST_YEAR = 2018
_MONTHLY_MODE = "1"
_USER_AGENT = "finanzas"
_ISO_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _build_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def fetch(url: str = BCRD_URL, timeout: float = 30, today: date | None = None) -> bytes:
    """Descarga los promedios mensuales; sin la cookie de sesión el BCRD responde vacío."""
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
    except http.client.HTTPException as exc:  # respuesta cortada o mal formada
        raise OSError(str(exc)) from exc
    if not body.strip():
        raise OSError("el BCRD respondió sin datos")
    return body


def parse_monthly_averages(content: bytes) -> dict[str, Decimal]:
    """`{"YYYY-MM": tasa de venta promedio}` a partir de la respuesta JSON del BCRD."""
    try:
        items = json.loads(content)["result"]["items"]
        values = {_month(item["date"]): Decimal(item["sellingValueFormatted"]) for item in items}
    except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
        raise ValueError("Respuesta del BCRD con formato inesperado") from exc
    if not values:
        raise ValueError("el BCRD no devolvió tasas")
    if not all(v.is_finite() and v > 0 for v in values.values()):
        raise ValueError("Respuesta del BCRD con tasas inválidas")
    return values


def _month(iso_date: str) -> str:
    month = iso_date[:7]
    if not _ISO_MONTH.match(month):
        raise ValueError(iso_date)
    return month
