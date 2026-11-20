"""Hosted mode against abuse: IPv6 rotation, parallel guesses, draining the daily mail cap and
targeted lockout. Synthetic addresses only (documentation ranges and `example.com`)."""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from pathlib import Path

import pytest

from michelito.demo import network
from michelito.hosted import auth as auth_module
from michelito.hosted.auth import AuthError
from tests.hosted_helpers import WRITE, hosted

ALICE = "alice@example.com"
UA = "Mozilla/5.0 (X11; Linux x86_64) Firefox/132.0"


def _v6(n: int, slash56: int = 1) -> tuple[tuple[str, int], ...]:
    """A different /64 each time, inside the /56 number `slash56` of 2001:db8::/48."""
    return network.quota_keys(f"2001:db8:0:{slash56:02x}{n:02x}::1")


def _v4(n: int) -> tuple[tuple[str, int], ...]:
    return network.quota_keys(f"198.51.100.{n}")


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


def _drain(h, email: str, sources: range) -> None:  # noqa: ANN001
    """Anonymous requests for `email` from many sources, spaced past the short limits."""
    for n in sources:
        h.clock.advance(16 * 60)
        with contextlib.suppress(AuthError):
            h.service.request_code(email, _v4(n))


def _fresh_code(h) -> str:  # noqa: ANN001
    """A new login code for Alice (already signed in once)."""
    h.clock.advance(61)
    h.service.request_code(ALICE, _v4(1))
    return h.last_code(ALICE)


# Per-network limits.


def test_rotating_ipv6_addresses_does_not_multiply_the_quota(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    ok = 0
    for n in range(30):  # 30 different /64 in one /56: the /56 allows 2 × 10
        try:
            h.service.request_code(f"p{n}@example.com", _v6(n))
            ok += 1
        except AuthError as error:
            assert error.kind == "rate"
    assert ok == 20
    for n in range(30):  # another /56 of the same /48: the /48 allows 4 × 10 in total
        with contextlib.suppress(AuthError):
            h.service.request_code(f"q{n}@example.com", _v6(n, slash56=2))
            ok += 1
    assert ok == 40
    with pytest.raises(AuthError):
        h.service.request_code("r@example.com", _v6(0, slash56=3))


def test_checks_count_in_every_ipv6_bucket(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    refused = 0
    for n in range(80):
        try:
            h.service.verify(f"p{n}@example.com", "123456", UA, _v6(n))
        except AuthError as error:
            refused += error.kind == "rate"
    assert refused == 80 - 60  # the /56 allows 2 × 30 checks


# Attempts per code.


def test_parallel_wrong_guesses_cannot_exceed_five_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    code = _fresh_code(h)
    compared = []
    real = auth_module.hmac.compare_digest

    def counting(a: str, b: str) -> bool:
        compared.append(1)
        return real(a, b)

    monkeypatch.setattr(auth_module.hmac, "compare_digest", counting)
    start = threading.Barrier(30)

    def guess(n: int) -> None:
        start.wait()
        with contextlib.suppress(AuthError):
            h.service.verify(ALICE, _wrong(code), UA, _v4(100 + n))

    threads = [threading.Thread(target=guess, args=(n,)) for n in range(30)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(compared) == 5
    with sqlite3.connect(h.data / "accounts.db") as conn:
        assert conn.execute("SELECT max(attempts) FROM login_codes").fetchone()[0] == 5
    with pytest.raises(AuthError):
        h.service.verify(ALICE, code, UA, _v4(1))


def test_five_attempts_in_total_across_sources_and_the_link_still_works(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    code = _fresh_code(h)
    link = h.last_link(ALICE)
    for n in range(5):  # five different networks, one guess each
        with pytest.raises(AuthError):
            h.service.verify(ALICE, _wrong(code), UA, _v4(100 + n))
    with pytest.raises(AuthError):
        h.service.verify(ALICE, code, UA, _v4(1))
    token, email = h.service.verify_link(link, UA, _v4(1))
    assert token and email == ALICE


def test_only_the_newest_code_of_an_email_is_checked(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    older = _fresh_code(h)
    newer = _fresh_code(h)
    with pytest.raises(AuthError):
        h.service.verify(ALICE, older, UA, _v4(1))
    assert h.service.verify(ALICE, newer, UA, _v4(1))


def test_wrong_attempts_are_always_written_to_the_database(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.service.invite(ALICE)
    with pytest.raises(AuthError):
        h.service.verify(ALICE, "000000", UA, _v4(1))
    with sqlite3.connect(h.data / "accounts.db") as conn:
        assert conn.execute("SELECT attempts FROM login_codes").fetchone()[0] == 1


# Asking for codes and sending them.


def test_three_code_requests_per_email_from_every_source(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    known = h.sign_in(ALICE)
    for n in range(3):
        h.service.request_code(ALICE, _v4(10 + n))
    with pytest.raises(AuthError) as error:
        h.service.request_code(ALICE, _v4(20))  # a fourth network: still the email's quota
    assert error.value.kind == "rate"
    known.post("/api/auth/sign-out", headers=WRITE)  # only the known device left
    assert known.post("/api/auth/code", json={"email": ALICE}, headers=WRITE).status_code == 202


def test_many_sources_hit_only_the_email_ceiling_not_the_global_cap(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    before = len(h.mailer.sent)
    _drain(h, ALICE, range(1, 41))  # 40 different IPv4 addresses
    assert len(h.mailer.sent) - before == 15  # emails_per_email_ceiling (anonymous)
    assert h.app.state.dispatcher.available()


def test_one_source_cannot_drain_the_daily_mail_cap(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    for n in range(30):
        h.service.invite(f"p{n}@example.com")
    before = len(h.mailer.sent)
    for n in range(30):
        h.clock.advance(2 * 60)  # past the per-network 15-minute window over time
        h.service.request_code(f"p{n}@example.com", _v4(7))
    assert len(h.mailer.sent) - before == 20  # emails_per_ip_day


def test_no_second_email_while_a_fresh_code_is_in_the_inbox(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    before = len(h.mailer.sent)
    h.service.request_code(ALICE, _v4(1))
    h.service.request_code(ALICE, _v4(2))
    assert len(h.mailer.sent) - before == 1
    h.clock.advance(61)
    h.service.request_code(ALICE, _v4(3))
    assert len(h.mailer.sent) - before == 2


# Known devices.


def test_a_known_device_skips_the_anonymous_per_email_send_limits(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    known = h.sign_in(ALICE)
    device = known.cookies.get("device") or ""
    assert device and "alice" not in device and "@" not in device  # random, names nobody
    raw = (h.data / "accounts.db").read_bytes()
    assert device.encode() not in raw  # only its hash is stored
    known.post("/api/auth/sign-out", headers=WRITE)  # no session left, only the device
    _drain(h, ALICE, range(1, 41))
    h.clock.advance(61)
    stranger = h.client()
    sent = len(h.mailer.sent)
    assert stranger.post("/api/auth/code", json={"email": ALICE}, headers=WRITE).is_success
    assert len(h.mailer.sent) == sent  # the anonymous ceiling holds for strangers…
    answer = known.post("/api/auth/code", json={"email": ALICE}, headers=WRITE)
    assert answer.status_code == 202
    assert len(h.mailer.sent) == sent + 1  # …but not for the browser that signed in before
    forged = h.client()
    forged.cookies.set("device", device[:-4] + "0000")
    h.clock.advance(61)
    forged.post("/api/auth/code", json={"email": ALICE}, headers=WRITE)
    assert len(h.mailer.sent) == sent + 1
    assert not h.service.knows_device(device, "bob@example.com")  # Alice's proves nothing for Bob


def test_the_absolute_ceiling_binds_known_devices_too(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    before = len(h.mailer.sent)
    for n in range(40):  # trusted, from many sources (past the per-network daily limit)
        h.clock.advance(61)
        h.service.request_code(ALICE, _v4(n + 1), trusted=True)
    assert len(h.mailer.sent) - before == 30  # emails_per_email_absolute


def test_known_devices_die_with_sign_out_everywhere_expiry_and_suspension(
    tmp_path: Path,
) -> None:
    h = hosted(tmp_path)
    first = h.sign_in(ALICE)
    device = first.cookies.get("device")
    assert h.service.knows_device(device, ALICE)
    assert first.post("/api/auth/sign-out-everywhere", headers=WRITE).status_code == 204
    assert not h.service.knows_device(device, ALICE)

    h.clock.advance(61)
    second = h.sign_in(ALICE, h.client())
    device = second.cookies.get("device")
    h.clock.advance(89 * 24 * 3600)
    assert h.service.knows_device(device, ALICE)
    h.clock.advance(1 * 24 * 3600 + 1)  # 90 days at most
    assert not h.service.knows_device(device, ALICE)

    h.clock.advance(61)
    third = h.sign_in(ALICE, h.client())
    device = third.cookies.get("device")
    with sqlite3.connect(h.data / "accounts.db") as conn:
        conn.execute("UPDATE accounts SET status = 'disabled'")
    assert not h.service.knows_device(device, ALICE)


# The per-email hourly check block.


def test_one_source_alone_never_blocks_an_email(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    for _ in range(25):  # within one source's allowance of 30 checks
        with pytest.raises(AuthError) as error:
            h.service.verify(ALICE, "000000", UA, _v4(66))
        assert error.value.kind == "code"
    with pytest.raises(AuthError) as error:
        h.service.verify(ALICE, "000000", UA, _v4(1))
    assert error.value.kind == "code"  # not "rate": the owner elsewhere is not blocked


def test_checks_from_several_sources_block_strangers_for_an_hour(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    known = h.sign_in(ALICE)
    known.post("/api/auth/sign-out", headers=WRITE)  # only the known device left
    # The sign-in's own check (1 source) + 3 sources × 6: 19 checks from 4 sources.
    for n in range(3):
        for _ in range(6):
            with pytest.raises(AuthError):
                h.service.verify(ALICE, "000000", UA, _v4(100 + n))
    with pytest.raises(AuthError) as error:
        h.service.verify(ALICE, "000000", UA, _v4(104))  # the 5th distinct source
    assert error.value.kind == "code"
    with pytest.raises(AuthError) as error:
        h.service.verify(ALICE, "000000", UA, _v4(1))
    assert error.value.kind == "rate"
    # A known device of the account is not blocked by it (but its code has 5 attempts too).
    known.post("/api/auth/code", json={"email": ALICE}, headers=WRITE)
    code = h.last_code(ALICE)
    answer = known.post("/api/auth/verify", json={"email": ALICE, "code": code}, headers=WRITE)
    assert answer.status_code == 204
    # Unknown emails are limited alike (nothing to learn from the 429).
    for n in range(5):
        for _ in range(5):
            with contextlib.suppress(AuthError):
                h.service.verify("nobody@example.com", "000000", UA, _v4(150 + n))
    with pytest.raises(AuthError) as error:
        h.service.verify("nobody@example.com", "000000", UA, _v4(1))
    assert error.value.kind == "rate"
    h.clock.advance(3601)  # an hour later the email can be checked again
    with pytest.raises(AuthError) as error:
        h.service.verify(ALICE, "000000", UA, _v4(201))
    assert error.value.kind == "code"


def test_a_known_device_still_has_only_five_attempts_per_code(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    known = h.sign_in(ALICE)
    known.post("/api/auth/sign-out", headers=WRITE)
    h.clock.advance(61)
    known.post("/api/auth/code", json={"email": ALICE}, headers=WRITE)
    code = h.last_code(ALICE)
    for _ in range(5):
        body = {"email": ALICE, "code": _wrong(code)}
        assert known.post("/api/auth/verify", json=body, headers=WRITE).status_code == 400
    body = {"email": ALICE, "code": code}
    assert known.post("/api/auth/verify", json=body, headers=WRITE).status_code == 400
