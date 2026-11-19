"""The IP behind the copies quota: trusted proxies and per-network keys (`demo.network`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from michelito.demo import network
from michelito.demo.app import create_demo_app
from tests.demo_helpers import HOST, TODAY, WRITE, _restore_providers, settings  # noqa: F401

PROXY = network.networks(["10.0.0.0/8", "::1"])


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [] if forwarded is None else [(b"x-forwarded-for", forwarded.encode())]
    return Request({"type": "http", "client": (peer, 1), "headers": headers})


def test_forwarded_headers_are_ignored_without_trusted_proxy() -> None:
    assert network.client_ip(_request("client-ip", "other"), ()) == "client-ip"
    assert network.client_ip(_request("10.0.0.5", "2001:db8::1"), ()) == "10.0.0.5"


def test_trusted_proxy_gives_the_last_untrusted_hop() -> None:
    # The client made up the first hop; the trusted proxy appended the last one.
    forwarded = "2001:db8::bad, 2001:db8:1::7, 10.0.0.9"
    assert network.client_ip(_request("10.0.0.5", forwarded), PROXY) == "2001:db8:1::7"
    assert network.client_ip(_request("10.0.0.5"), PROXY) == "10.0.0.5"
    assert network.client_ip(_request("2001:db8::99", "2001:db8::1"), PROXY) == "2001:db8::99"


@pytest.mark.parametrize(
    ("address", "key"),
    [
        ("2001:db8:1:2:aaaa::1", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:ffff::9", "2001:db8:1:2::/64"),
        ("::ffff:10.1.2.3", "10.1.2.3"),
        ("10.1.2.3", "10.1.2.3"),
        ("not-an-ip", network.UNKNOWN),
        (None, network.UNKNOWN),
    ],
)
def test_quota_key(address: str | None, key: str) -> None:
    assert network.quota_key(address) == key


def test_one_household_shares_its_ipv6_quota(tmp_path: Path) -> None:
    demo = settings(tmp_path, per_ip=2)
    app = create_demo_app(type(demo)(**{**demo.__dict__, "proxies": ("::1",)}), today=lambda: TODAY)
    codes = []
    for suffix in ("1", "2", "3"):
        api = TestClient(app, base_url=f"http://{HOST}", client=("::1", 1))
        headers = {**WRITE, "X-Forwarded-For": f"2001:db8:5:6::{suffix}"}
        codes.append(api.post("/api/demo/session", headers=headers).status_code)
    assert codes == [201, 201, 429]


def test_new_copies_per_minute_are_capped(tmp_path: Path) -> None:
    app = create_demo_app(settings(tmp_path, per_ip=100, per_minute_new=2), today=lambda: TODAY)
    codes = [
        TestClient(app, base_url=f"http://{HOST}")
        .post("/api/demo/session", headers=WRITE)
        .status_code
        for _ in range(3)
    ]
    assert codes == [201, 201, 503]
