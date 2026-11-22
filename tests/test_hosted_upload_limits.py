"""Hosted uploads: the share target is bound to the browser that shared, and a PDF that costs too
much to open (a decompression bomb, too many pages) fails only that file. Synthetic PDFs only."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito.hosted import uploads
from michelito.hosted.onboarding_routes import UploadCaps
from tests import samples
from tests.hosted_helpers import WRITE, Hosted, hosted
from tests.synthetic_pdf import bomb, build
from tests.test_hosted_uploads import (
    ALICE,
    BHD_LOCKED,
    BOB,
    PASSWORD,
    POPULAR,
    count,
    states,
    upload,
    user_db,
)

SHARE_SHEET = {"Sec-Fetch-Site": "none"}  # what the OS share sheet's navigation carries


def share(client: TestClient, name: str = "card.pdf") -> tuple[str, str]:
    answer = client.post(
        "/share-target",
        files={"statements": (name, POPULAR, "application/pdf")},
        headers=SHARE_SHEET,
        follow_redirects=False,
    )
    assert answer.status_code == 303
    return answer.headers["location"].split("=", 1)[1], answer.headers["set-cookie"]


def test_a_share_made_by_another_browser_cannot_be_claimed(tmp_path: Path) -> None:
    """Token fixation: someone shares their own PDF and lures the victim to its link."""
    h: Hosted = hosted(tmp_path)
    attacker = h.client()
    token, cookie = share(attacker, "theirs.pdf")
    lowered = cookie.lower()
    assert "httponly" in lowered and "samesite=lax" in lowered and "path=/" in lowered
    victim = h.sign_in(ALICE)
    claimed = victim.post("/api/uploads/shared", json={"token": token}, headers=WRITE)
    assert claimed.status_code == 404
    assert count(user_db(h, ALICE), "statements") == 0
    # The token is spent: not even the browser that made it can use it now.
    late = h.sign_in(BOB, attacker).post(
        "/api/uploads/shared", json={"token": token}, headers=WRITE
    )
    assert late.status_code == 404


@pytest.mark.parametrize(
    ("headers", "allowed"),
    [
        ({"Sec-Fetch-Site": "none"}, True),  # the OS share sheet (Chrome on Android)
        ({"Sec-Fetch-Site": "none", "Origin": "null"}, True),
        ({"Sec-Fetch-Site": "same-origin", "Origin": "http://127.0.0.1"}, True),
        ({"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"}, False),
        ({"Sec-Fetch-Site": "same-site", "Origin": "https://demo.127.0.0.1"}, False),
        ({"Sec-Fetch-Site": "cross-site"}, False),
        ({}, False),  # neither fetch metadata nor Origin: not a browser that installs apps
        ({"Origin": "null"}, False),
        ({"Origin": "http://127.0.0.1"}, True),
        ({"Origin": "https://evil.example"}, False),
    ],
)
def test_the_share_target_refuses_cross_site_posts(
    tmp_path: Path, headers: dict[str, str], allowed: bool
) -> None:
    h = hosted(tmp_path)
    answer = h.client().post(
        "/share-target",
        files={"statements": ("card.pdf", POPULAR, "application/pdf")},
        headers=headers,
        follow_redirects=False,
    )
    if allowed:
        assert answer.status_code == 303
        assert answer.headers["location"].startswith("/import#share=")
    else:
        assert answer.status_code == 403
        assert "set-cookie" not in answer.headers


def test_peeking_or_discarding_a_share_never_starts_an_upload(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    phone = h.client()
    token, _ = share(phone, "card.pdf")
    alice = h.sign_in(ALICE, phone)
    peek = alice.post("/api/uploads/shared/peek", json={"token": token}, headers=WRITE)
    assert peek.status_code == 200
    assert peek.json() == [{"name": "card.pdf", "size": len(POPULAR)}]
    assert alice.get("/api/uploads/latest").json() is None  # no job without the tap
    assert count(user_db(h, ALICE), "documents") == 0
    other = h.client()
    assert (
        h.sign_in(BOB, other)
        .post("/api/uploads/shared/peek", json={"token": token}, headers=WRITE)
        .status_code
        == 404
    )
    discarded = alice.post("/api/uploads/shared/discard", json={"token": token}, headers=WRITE)
    assert discarded.status_code == 204
    assert (
        alice.post("/api/uploads/shared", json={"token": token}, headers=WRITE).status_code == 404
    )
    assert alice.get("/api/uploads/latest").json() is None


def test_the_share_cookie_is_host_prefixed_over_https(tmp_path: Path) -> None:
    h = hosted(tmp_path, secure_cookie=True)
    _, cookie = share(TestClient(h.app, base_url="https://127.0.0.1"))
    assert cookie.startswith("__Host-share=")
    assert "Secure" in cookie and "Domain" not in cookie


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="RLIMIT_AS is Linux")
def test_a_decompression_bomb_fails_only_that_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    h = hosted(tmp_path, uploads=UploadCaps(worker_memory=300 * 1024 * 1024))
    alice = h.sign_in(ALICE)
    job = upload(alice, ("bomb.pdf", bomb(512 * 1024 * 1024)), ("card.pdf", POPULAR))
    assert states(job) == {"bomb.pdf": "too_complex", "card.pdf": "squared"}
    messages = [r.getMessage() for r in caplog.records]
    assert any("stage=limits" in m and "checks=memory" in m for m in messages)


def test_too_many_pages_are_refused_before_reading_words(tmp_path: Path) -> None:
    alice = hosted(tmp_path).sign_in(ALICE)
    job = upload(alice, ("long.pdf", build((samples.UNKNOWN,) * 51)))
    assert states(job) == {"long.pdf": "too_complex"}


def test_the_worker_gets_the_password_through_a_pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[list[str], dict | None]] = []
    piped: list[bytes] = []
    real = subprocess.Popen

    class Spy(real):  # type: ignore[misc, valid-type]
        def __init__(self, command, **kwargs):  # noqa: ANN001, ANN003
            seen.append((command, kwargs.get("env")))
            super().__init__(command, **kwargs)
            original = self.stdin.write

            def write(data: bytes) -> int:
                piped.append(bytes(data))
                return original(data)

            self.stdin.write = write  # type: ignore[method-assign]

    monkeypatch.setattr(subprocess, "Popen", Spy)
    assert uploads.examine(BHD_LOCKED, PASSWORD).state == uploads.SQUARED
    assert seen
    for command, env in seen:
        assert PASSWORD not in " ".join(command)
        assert PASSWORD not in repr(env)
    assert any(PASSWORD.encode() in data for data in piped)  # only through standard input
