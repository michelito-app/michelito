import http.client
import json
from datetime import date
from decimal import Decimal

import pytest

from finanzas.analysis import bcrd


def _item(day: str, selling: str) -> dict[str, object]:
    return {
        "purchaseValue": 62.0,
        "purchaseValueFormatted": "62.9000",
        "sellingValueFormatted": selling,
        "date": f"{day}T00:00:00Z",
        "statisticDataGroupName": "inventado",
        "id": 0,
    }


def _payload(*items: dict[str, object]) -> bytes:
    return json.dumps({"result": {"totalCount": len(items), "items": list(items)}}).encode()


def test_parse_monthly_averages() -> None:
    content = _payload(_item("2026-09-01", "63.4000"), _item("2026-08-01", "63.1000"))
    assert bcrd.parse_monthly_averages(content) == {
        "2026-08": Decimal("63.1000"),
        "2026-09": Decimal("63.4000"),
    }


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"no es json",
        b'{"result": {}}',
        b'{"result": {"items": [{"date": "2026-09-01T00:00:00Z"}]}}',
        _payload(_item("2026-09-01", "abc")),
        _payload(_item("septiembre", "63.4000")),
        _payload(),
    ],
)
def test_parse_rejects_malformed(content: bytes) -> None:
    with pytest.raises(ValueError, match="BCRD"):
        bcrd.parse_monthly_averages(content)


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _FakeOpener:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requests: list = []

    def open(self, request, timeout):  # noqa: ANN001, ANN201
        self.requests.append(request)
        return _FakeResponse(self.body if request.data is not None else b"<html>")


def test_fetch_primes_cookie_then_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = _FakeOpener(b'{"result": {"items": []}}')
    monkeypatch.setattr(bcrd, "_build_opener", lambda: opener)
    assert bcrd.fetch(today=date(2026, 11, 14)) == opener.body
    page, post = opener.requests
    assert page.full_url == bcrd.BCRD_PAGE and page.data is None
    assert post.full_url == bcrd.BCRD_URL
    form = post.data.decode()
    assert "fromDate=2018-01-01" in form and "toDate=2026-11-01" in form
    assert "statisticMode=1" in form
    assert post.get_header("User-agent") == "finanzas"
    assert post.get_header("Referer") == bcrd.BCRD_PAGE


def test_fetch_empty_body_is_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bcrd, "_build_opener", lambda: _FakeOpener(b""))
    with pytest.raises(OSError):
        bcrd.fetch()


def test_parse_empty_items_says_no_rates() -> None:
    with pytest.raises(ValueError, match="no devolvió tasas"):
        bcrd.parse_monthly_averages(_payload())


@pytest.mark.parametrize("failing", ["page", "post"])
def test_fetch_wraps_http_errors_as_oserror(failing: str, monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken(_FakeOpener):
        def open(self, request, timeout):  # noqa: ANN001, ANN201
            if (request.data is None) == (failing == "page"):
                raise http.client.IncompleteRead(b"")
            return super().open(request, timeout)

    monkeypatch.setattr(bcrd, "_build_opener", lambda: Broken(b"{}"))
    with pytest.raises(OSError):
        bcrd.fetch()
