"""Connected Gmail, the module (`hosted.mailbox`): the client file, PKCE, the consent address,
the sealed token and how a read ends. Synthetic tokens and messages only; no network."""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from michelito import db, receipts
from michelito.analysis import receipt_store
from michelito.hosted import mailbox
from michelito.hosted.inbox_store import Sealer
from tests import mailbox_helpers as fake


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "michelito.db")) as opened:
        yield opened


@pytest.fixture
def sealer() -> Sealer:
    return Sealer.of(secrets.token_bytes(32))


def _web(**changes: object) -> str:
    web = dict(fake.CLIENT["web"]) | changes
    return json.dumps({"web": web})


# The client file.


def test_googles_web_client_file_is_read() -> None:
    found = mailbox.parse_client(json.dumps(fake.CLIENT))

    assert found.client_id == "synthetic-client.apps.googleusercontent.com"
    assert found.token_uri == "https://oauth2.googleapis.com/token"
    assert "synthetic-client-secret" not in repr(found)


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        json.dumps({"installed": fake.CLIENT["web"]}),  # a desktop client, not a web one
        json.dumps({"web": "x"}),
        _web(client_secret=""),
        _web(client_id=7),
        _web(auth_uri="http://accounts.google.com/o/oauth2/auth"),
        _web(auth_uri="https://accounts.google.com.attacker.example/auth"),
        _web(token_uri="https://tokens.attacker.example/token"),
    ],
)
def test_a_client_file_of_the_wrong_shape_or_hosts_is_refused(text: str) -> None:
    with pytest.raises(mailbox.ClientError) as raised:
        mailbox.parse_client(text)

    assert "synthetic-client-secret" not in str(raised.value)


def test_without_a_client_file_the_feature_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(mailbox.CLIENT_FILE_ENV, raising=False)

    assert mailbox.load_client() is None


def test_the_client_file_comes_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(mailbox.CLIENT_FILE_ENV, str(fake.client_file(tmp_path)))

    assert mailbox.load_client() == fake.client()


def test_a_named_client_file_that_cannot_be_used_stops_the_start(tmp_path: Path) -> None:
    big = tmp_path / "big.json"
    big.write_text(" " * (mailbox.CLIENT_FILE_MAX + 1), encoding="utf-8")

    with pytest.raises(mailbox.ClientError, match="cannot be read"):
        mailbox.load_client(tmp_path / "missing.json")
    with pytest.raises(mailbox.ClientError, match="too large"):
        mailbox.load_client(big)


# Consent.


def test_the_pkce_challenge_is_rfc_7636s() -> None:
    # The example of RFC 7636, appendix B.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"

    assert mailbox.challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert 43 <= len(mailbox.new_verifier()) <= 128
    assert mailbox.new_state() != mailbox.new_state()


def test_the_consent_address_asks_only_for_read_only_access_with_pkce() -> None:
    verifier = mailbox.new_verifier()

    url = mailbox.authorization_url(fake.client(), "https://app.example/cb", "s1", verifier)

    parts = urlsplit(url)
    params = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.hostname}" == "https://accounts.google.com"
    assert params == {
        "client_id": "synthetic-client.apps.googleusercontent.com",
        "redirect_uri": "https://app.example/cb",
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/gmail.readonly",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
        "state": "s1",
        "code_challenge": mailbox.challenge(verifier),
        "code_challenge_method": "S256",
    }
    assert "synthetic-client-secret" not in url and verifier not in url


def test_the_search_names_only_the_receipt_senders_of_the_last_year() -> None:
    found = mailbox.query()

    assert found.endswith(" newer_than:12m")
    assert all(f"from:{sender}" in found for sender in receipts.SENDERS)
    assert found.count("from:") == len(receipts.SENDERS)


def test_the_state_is_kept_only_as_its_hash() -> None:
    state = mailbox.new_state()

    assert state not in mailbox.state_key(state) and len(mailbox.state_key(state)) == 64


# Storage.


def test_reading_a_status_never_creates_the_table(conn: sqlite3.Connection) -> None:
    assert mailbox.status(conn) is None
    assert mailbox.token(conn, Sealer.of(b"k" * 32)) is None
    mailbox.forget(conn)

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert "mailbox_google" not in tables


def test_the_token_is_stored_sealed(conn: sqlite3.Connection, sealer: Sealer) -> None:
    with conn:
        mailbox.store(conn, sealer, fake.TOKEN, fake.ADDRESS)

    (raw,) = conn.execute("SELECT sealed FROM mailbox_google").fetchone()
    assert fake.TOKEN.encode() not in bytes(raw)
    assert mailbox.token(conn, sealer) == fake.TOKEN
    found = mailbox.status(conn)
    assert found is not None and found.address == fake.ADDRESS and found.problem is None
    assert found.synced_at is None


def test_a_reconnection_replaces_the_token_and_clears_the_problem(
    conn: sqlite3.Connection, sealer: Sealer
) -> None:
    with conn:
        mailbox.store(conn, sealer, "1//old-synthetic", None)
        mailbox.mark(conn, "reconnect", synced=False)
        mailbox.store(conn, sealer, fake.TOKEN, fake.ADDRESS)

    found = mailbox.status(conn)
    assert found is not None and found.problem is None
    assert mailbox.token(conn, sealer) == fake.TOKEN
    assert conn.execute("SELECT COUNT(*) FROM mailbox_google").fetchone()[0] == 1


def test_another_key_does_not_open_the_token(conn: sqlite3.Connection, sealer: Sealer) -> None:
    with conn:
        mailbox.store(conn, sealer, fake.TOKEN, None)

    with pytest.raises(mailbox.SealError):
        mailbox.token(conn, Sealer.of(secrets.token_bytes(32)))


def test_forgetting_deletes_the_token(conn: sqlite3.Connection, sealer: Sealer) -> None:
    with conn:
        mailbox.store(conn, sealer, fake.TOKEN, fake.ADDRESS)
        mailbox.forget(conn)

    assert mailbox.status(conn) is None and mailbox.token(conn, sealer) is None
    assert conn.execute("PRAGMA secure_delete").fetchone()[0] == 1


# Reading.


def _connected(conn: sqlite3.Connection, sealer: Sealer) -> None:
    with conn:
        mailbox.store(conn, sealer, fake.TOKEN, fake.ADDRESS)


def test_a_read_stores_the_receipts_as_the_mailboxs(
    conn: sqlite3.Connection, sealer: Sealer
) -> None:
    _connected(conn, sealer)
    google = fake.FakeGoogle()

    assert mailbox.sync(conn, sealer, fake.client(), google) == "read"

    assert {receipt.source for receipt in receipt_store.load(conn)} == {"gmail"}
    assert len(receipt_store.load(conn)) == 3
    assert mailbox.gmail_receipts(conn) == 2
    assert google.opened[0].queries == [mailbox.query()]
    found = mailbox.status(conn)
    assert found is not None and found.synced_at is not None and found.problem is None


def test_a_read_fills_in_an_address_the_connection_could_not_read(
    conn: sqlite3.Connection, sealer: Sealer
) -> None:
    with conn:
        mailbox.store(conn, sealer, fake.TOKEN, None)

    assert mailbox.sync(conn, sealer, fake.client(), fake.FakeGoogle()) == "read"

    found = mailbox.status(conn)
    assert found is not None and found.address == fake.ADDRESS


def test_a_read_leaves_a_known_address_alone(conn: sqlite3.Connection, sealer: Sealer) -> None:
    _connected(conn, sealer)
    google = fake.FakeGoogle(address_error=RuntimeError("synthetic: must not be asked"))

    assert mailbox.sync(conn, sealer, fake.client(), google) == "read"

    found = mailbox.status(conn)
    assert found is not None and found.address == fake.ADDRESS


def test_an_address_that_still_fails_does_not_fail_the_read(
    conn: sqlite3.Connection, sealer: Sealer
) -> None:
    with conn:
        mailbox.store(conn, sealer, fake.TOKEN, None)
    google = fake.FakeGoogle(address_error=RuntimeError("synthetic"))

    assert mailbox.sync(conn, sealer, fake.client(), google) == "read"

    found = mailbox.status(conn)
    assert found is not None and found.address is None and found.problem is None


def test_a_second_read_downloads_nothing_new(conn: sqlite3.Connection, sealer: Sealer) -> None:
    _connected(conn, sealer)
    google = fake.FakeGoogle()
    mailbox.sync(conn, sealer, fake.client(), google)

    assert mailbox.sync(conn, sealer, fake.client(), google) == "read"

    assert mailbox.gmail_receipts(conn) == 2


def test_without_a_connection_nothing_is_read(conn: sqlite3.Connection, sealer: Sealer) -> None:
    google = fake.FakeGoogle()

    assert mailbox.sync(conn, sealer, fake.client(), google) == "none"
    assert google.opened == []


def test_a_token_google_refuses_asks_to_reconnect(conn: sqlite3.Connection, sealer: Sealer) -> None:
    _connected(conn, sealer)
    google = fake.FakeGoogle(open_error=mailbox.Revoked("synthetic"))

    assert mailbox.sync(conn, sealer, fake.client(), google) == "reconnect"

    found = mailbox.status(conn)
    assert found is not None and found.problem == "reconnect" and found.synced_at is None
    assert mailbox.gmail_receipts(conn) == 0


def test_any_other_failure_is_recorded_by_its_class_only(
    conn: sqlite3.Connection, sealer: Sealer, caplog: pytest.LogCaptureFixture
) -> None:
    _connected(conn, sealer)
    google = fake.FakeGoogle(open_error=ConnectionError(f"secret detail {fake.TOKEN}"))

    assert mailbox.sync(conn, sealer, fake.client(), google) == "failed"

    found = mailbox.status(conn)
    assert found is not None and found.problem == "failed"
    assert "ConnectionError" in caplog.text
    assert "secret detail" not in caplog.text and fake.TOKEN not in caplog.text


def test_a_token_that_does_not_open_asks_to_reconnect(
    conn: sqlite3.Connection, sealer: Sealer
) -> None:
    _connected(conn, sealer)

    found = mailbox.sync(conn, Sealer.of(secrets.token_bytes(32)), fake.client(), fake.FakeGoogle())

    assert found == "reconnect"


def test_a_read_that_outlived_its_connection_marks_nothing(
    conn: sqlite3.Connection, sealer: Sealer
) -> None:
    _connected(conn, sealer)

    class Reconnecting(fake.FakeGoogle):
        def mailbox(self, client, refresh_token):  # noqa: ANN001, ANN201
            with conn:  # the person reconnected meanwhile: a new connection
                mailbox.store(conn, sealer, fake.TOKEN, fake.ADDRESS)
            raise mailbox.Revoked("the old one")

    assert mailbox.sync(conn, sealer, fake.client(), Reconnecting()) == "reconnect"

    found = mailbox.status(conn)
    assert found is not None and found.problem is None


# After the security review.


def test_a_read_takes_at_most_its_limit_and_the_rest_comes_next(
    conn: sqlite3.Connection, sealer: Sealer
) -> None:
    _connected(conn, sealer)
    google = fake.FakeGoogle()

    assert mailbox.sync(conn, sealer, fake.client(), google, limit=1) == "read"
    assert mailbox.gmail_receipts(conn) == 1
    assert mailbox.sync(conn, sealer, fake.client(), google, limit=1) == "read"
    assert mailbox.gmail_receipts(conn) == 2


def test_a_stopped_read_takes_nothing_more(conn: sqlite3.Connection, sealer: Sealer) -> None:
    _connected(conn, sealer)

    found = mailbox.sync(conn, sealer, fake.client(), fake.FakeGoogle(), stop=lambda: True)

    assert found == "read" and mailbox.gmail_receipts(conn) == 0


def _refusing(monkeypatch: pytest.MonkeyPatch, reason: str) -> None:
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials

    def refresh(self: object, request: object) -> None:
        raise RefreshError(f"{reason}: synthetic", {"error": reason})

    monkeypatch.setattr(Credentials, "refresh", refresh)


def test_only_invalid_grant_asks_to_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    from google.auth.exceptions import RefreshError

    _refusing(monkeypatch, "invalid_grant")
    with pytest.raises(mailbox.Revoked):
        mailbox.RealGoogle().mailbox(fake.client(), fake.TOKEN)

    _refusing(monkeypatch, "temporarily_unavailable")
    with pytest.raises(RefreshError) as raised:
        mailbox.RealGoogle().mailbox(fake.client(), fake.TOKEN)
    assert not isinstance(raised.value, mailbox.Revoked)


def test_a_transient_refusal_is_only_a_failed_read(
    conn: sqlite3.Connection, sealer: Sealer, monkeypatch: pytest.MonkeyPatch
) -> None:
    _connected(conn, sealer)
    _refusing(monkeypatch, "temporarily_unavailable")

    assert mailbox.sync(conn, sealer, fake.client(), mailbox.RealGoogle()) == "failed"


def test_googles_endpoints_are_never_followed_elsewhere(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    calls: list[dict[str, object]] = []

    class Answer:
        status_code = 200

        def json(self) -> dict[str, str]:
            return {"refresh_token": fake.TOKEN, "scope": mailbox.SCOPE}

    def post(url: str, **options: object) -> Answer:
        calls.append(options)
        return Answer()

    monkeypatch.setattr(requests, "post", post)
    google = mailbox.RealGoogle()

    google.exchange(fake.client(), "https://app.example/cb", "c", "v")
    google.revoke(fake.TOKEN)

    assert [call["allow_redirects"] for call in calls] == [False, False]


@pytest.mark.parametrize(
    ("token_uri", "accepted"),
    [
        ("https://oauth2.googleapis.com:443/token", True),
        ("https://oauth2.googleapis.com:8443/token", False),
        ("https://oauth2.googleapis.com:notaport/token", False),
    ],
)
def test_googles_addresses_use_the_default_port(token_uri: str, accepted: bool) -> None:
    text = _web(token_uri=token_uri)

    if accepted:
        assert mailbox.parse_client(text).token_uri == token_uri
    else:
        with pytest.raises(mailbox.ClientError):
            mailbox.parse_client(text)


@pytest.mark.parametrize("content", [b"\xff\xfe not utf-8", b"[" * 10_000])
def test_a_malformed_client_file_is_a_clean_error(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "client.json"
    path.write_bytes(content)

    with pytest.raises(mailbox.ClientError):
        mailbox.load_client(path)
