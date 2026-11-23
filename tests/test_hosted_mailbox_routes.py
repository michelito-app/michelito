"""Connected Gmail, the routes (`hosted.mailbox_routes`), the hourly read and the public privacy
page. Google is a fake (`tests.mailbox_helpers`); every token, address and email is made up."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import receipt_store
from michelito.hosted import mailbox, mailbox_routes, privacy
from tests import mailbox_helpers as fake
from tests.hosted_helpers import WRITE, Hosted, hosted

ALICE = "alice@example.com"
BRUNO = "bruno@example.com"
STATUS = "/api/mailbox"
START = "/api/mailbox/google/start"
SYNC = "/api/mailbox/sync"
CALLBACK = mailbox.CALLBACK_PATH


def _hosted(tmp_path: Path, google: fake.FakeGoogle | None = None, **overrides: object) -> Hosted:
    return hosted(
        tmp_path,
        google_client=fake.client_file(tmp_path),
        google=google or fake.FakeGoogle(),
        mailbox_background=False,
        **overrides,
    )


@pytest.fixture
def google() -> fake.FakeGoogle:
    return fake.FakeGoogle()


@pytest.fixture
def h(tmp_path: Path, google: fake.FakeGoogle) -> Hosted:
    return _hosted(tmp_path, google)


def _connect(h: Hosted, email: str) -> sqlite3.Connection:
    account = h.service.store.account_by_email(email)
    assert account is not None
    workspace = h.service.workspace_of(account)
    return db.connect(workspace.database, workspace.key)


def _start(client: TestClient) -> dict[str, str]:
    answer = client.post(START, headers=WRITE)
    assert answer.status_code == 200, answer.text
    url = answer.json()["url"]
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def _back(client: TestClient, **params: str) -> str:
    """Google's redirect back: where the app sends the browser next."""
    answer = client.get(CALLBACK, params=params, follow_redirects=False)
    assert answer.status_code == 303, answer.text
    return answer.headers["location"]


def _outcome(location: str) -> str:
    parts = urlsplit(location)
    assert parts.path == "/settings" and parts.fragment == "mailbox"
    return parse_qs(parts.query)["gmail"][0]


def _connected(h: Hosted, email: str = ALICE) -> TestClient:
    client = h.sign_in(email)
    state = _start(client)["state"]
    assert _outcome(_back(client, code="synthetic-code", state=state)) == "connected"
    return client


# Connecting.


def test_without_a_google_client_the_feature_is_not_offered(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    alice = h.sign_in(ALICE)

    found = alice.get(STATUS).json()

    assert found["available"] is False and found["connected"] is False
    assert alice.post(START, headers=WRITE).status_code == 404
    assert alice.post(SYNC, headers=WRITE).status_code == 404
    assert alice.delete(STATUS, headers=WRITE).json()["available"] is False
    assert _outcome(_back(alice, code="c", state="s")) == "failed"


def test_connecting_stores_the_token_sealed_and_reads_the_last_year(
    h: Hosted, google: fake.FakeGoogle
) -> None:
    alice = h.sign_in(ALICE)
    assert alice.get(STATUS).json()["connected"] is False
    params = _start(alice)

    location = _back(alice, code="synthetic-code", state=params["state"])

    assert _outcome(location) == "connected"
    ((code, verifier, uri),) = google.exchanged
    assert code == "synthetic-code" and uri == "https://app.example" + CALLBACK
    assert mailbox.challenge(verifier) == params["code_challenge"]
    assert params["redirect_uri"] == uri
    found = alice.get(STATUS).json()
    assert found["available"] and found["connected"]
    assert found["address"] == fake.ADDRESS and found["problem"] is None
    assert found["synced_at"] is not None and found["receipts"] == 2
    assert found["syncing"] is False
    assert fake.TOKEN not in alice.get(STATUS).text
    with closing(_connect(h, ALICE)) as conn:
        (raw,) = conn.execute("SELECT sealed FROM mailbox_google").fetchone()
        assert fake.TOKEN.encode() not in bytes(raw)
        assert {r.source for r in receipt_store.load(conn)} == {"gmail"}
    database = next((h.data / "users").glob("*/michelito.db"))
    assert fake.TOKEN.encode() not in database.read_bytes()


def test_the_address_is_optional(tmp_path: Path) -> None:
    google = fake.FakeGoogle(address_error=ConnectionError("synthetic"))
    h = _hosted(tmp_path, google)

    alice = _connected(h)

    found = alice.get(STATUS).json()
    assert found["connected"] and found["address"] is None and found["receipts"] == 2


def test_a_state_is_used_once(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    state = _start(alice)["state"]
    assert _outcome(_back(alice, code="c", state=state)) == "connected"

    assert _outcome(_back(alice, code="c", state=state)) == "failed"


def test_an_expired_state_is_refused(h: Hosted, google: fake.FakeGoogle) -> None:
    alice = h.sign_in(ALICE)
    state = _start(alice)["state"]
    h.clock.advance(mailbox_routes.STATE_SECONDS + 1)

    assert _outcome(_back(alice, code="c", state=state)) == "expired"
    assert google.exchanged == [] and alice.get(STATUS).json()["connected"] is False


def test_an_unknown_state_is_refused(h: Hosted, google: fake.FakeGoogle) -> None:
    alice = h.sign_in(ALICE)
    _start(alice)

    assert _outcome(_back(alice, code="c", state="made-up-state")) == "failed"
    assert _outcome(_back(alice, code="c")) == "failed"
    assert google.exchanged == []


def test_another_accounts_state_is_refused(h: Hosted, google: fake.FakeGoogle) -> None:
    alice = h.sign_in(ALICE)
    bruno = h.sign_in(BRUNO)
    state = _start(alice)["state"]

    assert _outcome(_back(bruno, code="c", state=state)) == "failed"
    assert google.exchanged == []
    assert bruno.get(STATUS).json()["connected"] is False
    assert alice.get(STATUS).json()["connected"] is False


def test_another_sessions_state_is_refused(h: Hosted, google: fake.FakeGoogle) -> None:
    phone = h.sign_in(ALICE)
    laptop = h.sign_in(ALICE, client=h.client())
    state = _start(phone)["state"]

    assert _outcome(_back(laptop, code="c", state=state)) == "failed"
    assert google.exchanged == [] and phone.get(STATUS).json()["connected"] is False


def test_without_a_session_the_callback_only_redirects(h: Hosted, google: fake.FakeGoogle) -> None:
    alice = h.sign_in(ALICE)
    state = _start(alice)["state"]

    assert _outcome(_back(h.client(), code="c", state=state)) == "failed"
    assert google.exchanged == []


def test_only_a_few_consents_wait_per_account(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    states = [_start(alice)["state"] for _ in range(mailbox_routes.PENDING_PER_ACCOUNT + 1)]

    assert _outcome(_back(alice, code="c", state=states[0])) == "failed"
    assert _outcome(_back(alice, code="c", state=states[-1])) == "connected"


def test_declining_stores_nothing(h: Hosted, google: fake.FakeGoogle) -> None:
    alice = h.sign_in(ALICE)
    state = _start(alice)["state"]

    assert _outcome(_back(alice, error="access_denied", state=state)) == "denied"
    assert google.exchanged == [] and alice.get(STATUS).json()["connected"] is False


def test_unticking_the_permission_is_refused_and_revoked(tmp_path: Path) -> None:
    google = fake.FakeGoogle(scopes=frozenset({"openid"}))
    h = _hosted(tmp_path, google)
    alice = h.sign_in(ALICE)
    state = _start(alice)["state"]

    assert _outcome(_back(alice, code="c", state=state)) == "scope"
    assert google.revoked == [fake.TOKEN]
    assert alice.get(STATUS).json()["connected"] is False


def test_a_refused_code_fails_without_saying_why(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    google = fake.FakeGoogle(refuse_code=True)
    h = _hosted(tmp_path, google)
    alice = h.sign_in(ALICE)
    state = _start(alice)["state"]

    with caplog.at_level(logging.INFO):
        assert _outcome(_back(alice, code="synthetic-code", state=state)) == "failed"

    assert alice.get(STATUS).json()["connected"] is False
    ours = " ".join(r.getMessage() for r in caplog.records if r.name.startswith("michelito"))
    assert "Revoked" in ours
    assert "synthetic-code" not in ours and "synthetic refusal" not in ours


def test_the_start_needs_the_write_header(h: Hosted) -> None:
    alice = h.sign_in(ALICE)

    assert alice.post(START).status_code == 403


# Disconnecting and reading again.


def test_disconnecting_revokes_and_forgets(h: Hosted, google: fake.FakeGoogle) -> None:
    alice = _connected(h)

    answer = alice.delete(STATUS, headers=WRITE)

    assert answer.status_code == 200
    found = answer.json()
    assert found["revoked"] is True and found["connected"] is False
    assert google.revoked == [fake.TOKEN]
    assert found["receipts"] == 2  # what was read stays, like any other data
    with closing(_connect(h, ALICE)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mailbox_google").fetchone()[0] == 0


def test_disconnecting_says_when_google_did_not_confirm(tmp_path: Path) -> None:
    google = fake.FakeGoogle(revoke_works=False)
    h = _hosted(tmp_path, google)
    alice = _connected(h)

    found = alice.delete(STATUS, headers=WRITE).json()

    assert found["revoked"] is False and found["connected"] is False


def test_reading_now_waits_a_minute_between_reads(h: Hosted, google: fake.FakeGoogle) -> None:
    alice = _connected(h)  # the first read just finished

    assert alice.post(SYNC, headers=WRITE).status_code == 429
    h.clock.advance(mailbox_routes.SYNC_PAUSE + 1)
    assert alice.post(SYNC, headers=WRITE).status_code == 202
    assert len(google.opened) == 3  # the address, the first read and this one
    assert alice.post(SYNC, headers=WRITE).status_code == 429


def test_reading_now_is_refused_while_a_read_runs(h: Hosted) -> None:
    alice = _connected(h)
    h.clock.advance(mailbox_routes.SYNC_PAUSE + 1)
    account = h.service.store.account_by_email(ALICE)
    lock = h.app.state.mailbox.lock(account.id)

    with lock:
        assert alice.get(STATUS).json()["syncing"] is True
        assert alice.post(SYNC, headers=WRITE).status_code == 429


def test_reading_now_needs_a_connection(h: Hosted) -> None:
    alice = h.sign_in(ALICE)

    assert alice.post(SYNC, headers=WRITE).status_code == 409


def test_a_refused_token_shows_reconnect(h: Hosted, google: fake.FakeGoogle) -> None:
    alice = _connected(h)
    google.open_error = mailbox.Revoked("synthetic")
    h.clock.advance(mailbox_routes.SYNC_PAUSE + 1)

    assert alice.post(SYNC, headers=WRITE).status_code == 202

    assert alice.get(STATUS).json()["problem"] == "reconnect"
    # Connecting again clears it.
    google.open_error = None
    state = _start(alice)["state"]
    assert _outcome(_back(alice, code="c", state=state)) == "connected"
    assert alice.get(STATUS).json()["problem"] is None


def test_each_account_sees_only_its_own_connection(h: Hosted) -> None:
    alice = _connected(h)
    bruno = h.sign_in(BRUNO)

    assert bruno.get(STATUS).json()["connected"] is False
    assert fake.ADDRESS not in bruno.get(STATUS).text
    assert bruno.delete(STATUS, headers=WRITE).json()["revoked"] is False
    assert alice.get(STATUS).json()["connected"] is True


# The hourly read.


def test_the_sweep_reads_only_connected_mailboxes(h: Hosted, google: fake.FakeGoogle) -> None:
    _connected(h)
    h.sign_in(BRUNO)
    before = len(google.opened)

    assert mailbox_routes.sweep(h.app.state.mailbox) == (1, 0)

    assert len(google.opened) == before + 1
    with closing(_connect(h, BRUNO)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert "mailbox_google" not in tables  # reading never creates it


def test_one_failing_account_does_not_stop_the_sweep(
    h: Hosted, google: fake.FakeGoogle, caplog: pytest.LogCaptureFixture
) -> None:
    _connected(h, ALICE)
    _connected(h, BRUNO)
    calls: list[int] = []
    real = google.mailbox

    def first_fails(client, refresh_token):  # noqa: ANN001, ANN202
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError(f"synthetic {fake.ADDRESS}")
        return real(client, refresh_token)

    google.mailbox = first_fails  # type: ignore[method-assign]

    assert mailbox_routes.sweep(h.app.state.mailbox) == (1, 1)
    assert "ConnectionError" in caplog.text and fake.ADDRESS not in caplog.text


def test_the_sweep_skips_an_account_whose_read_is_running(h: Hosted) -> None:
    _connected(h)
    account = h.service.store.account_by_email(ALICE)

    with h.app.state.mailbox.lock(account.id):
        assert mailbox_routes.sweep(h.app.state.mailbox) == (0, 0)


def test_the_sweeper_runs_only_with_a_client(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    without = hosted(tmp_path / "a", sweep=True)
    with_client = _hosted(tmp_path / "b", sweep=True)
    try:
        assert not hasattr(without.app.state, "mailbox_sweeper")
        assert isinstance(with_client.app.state.mailbox_sweeper, mailbox_routes.Sweeper)
    finally:
        without.app.state.sweeper.stop()
        with_client.app.state.sweeper.stop()
        with_client.app.state.mailbox_sweeper.stop()


def test_active_accounts_lists_only_active_ones(h: Hosted) -> None:
    h.sign_in(ALICE)
    h.sign_in(BRUNO)

    assert [a.email for a in h.service.store.active_accounts()] == [ALICE, BRUNO]


# The privacy page.

LIMITED_USE = (
    "Michelito's use and transfer of information received from Google APIs adheres to the "
    f'<a href="{privacy.POLICY_URL}" rel="noopener">Google API Services User Data Policy</a>, '
    "including the Limited Use requirements."
)


def test_the_privacy_page_is_public_html(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(privacy.CONTACT_ENV, raising=False)
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<p>the interface</p>", encoding="utf-8")
    h = hosted(tmp_path, static_dir=static)
    anonymous = h.client()

    page = anonymous.get("/privacy")
    css = anonymous.get("/privacy.css")

    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "the interface" not in page.text
    assert LIMITED_USE in page.text
    assert "gmail.readonly" in page.text and "2026-11-23" in page.text
    assert '<html lang="es">' in page.text and 'lang="en"' in page.text
    assert "<style" not in page.text and "<script" not in page.text and "style=" not in page.text
    assert 'href="/privacy.css"' in page.text
    assert "mailto:" not in page.text
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    assert anonymous.get("/settings").text == "<p>the interface</p>"


def test_the_privacy_page_says_the_account_can_be_deleted_from_settings(tmp_path: Path) -> None:
    page = hosted(tmp_path).client().get("/privacy")

    assert page.status_code == 200
    assert "desde Ajustes" in page.text  # spanish-ui
    assert "from Settings" in page.text
    assert "Para borrar tu cuenta, escríbenos." not in page.text  # spanish-ui


def test_the_privacy_page_shows_the_contact_address_escaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(privacy.CONTACT_ENV, "privacy.desk@example.com")
    h = hosted(tmp_path)

    page = h.client().get("/privacy").text

    assert 'href="mailto:privacy.desk@example.com"' in page


@pytest.mark.parametrize(
    "value",
    ['"><script>alert(1)</script>@example.com', "x@example.com<img src=x>", "not an address"],
)
def test_a_contact_that_is_not_an_address_is_never_shown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(privacy.CONTACT_ENV, value)
    h = hosted(tmp_path)

    page = h.client().get("/privacy").text

    assert "<script" not in page and "<img" not in page and "mailto:" not in page
    assert value not in page


def test_every_text_of_the_page_is_escaped() -> None:
    hostile = {key: "<b>&</b>" for key in privacy.ENGLISH}

    found = privacy._article(hostile, "en", None)

    assert "<b>" not in found and "&lt;b&gt;&amp;&lt;/b&gt;" in found


def test_both_languages_have_the_same_texts() -> None:
    from michelito import i18n

    spanish = {key for key in i18n.MESSAGES if key.startswith("privacy.")}

    assert spanish - {"privacy.other_language"} == set(privacy.ENGLISH)


# After the security review.


def test_deleting_the_account_revokes_its_gmail_grant(h: Hosted, google: fake.FakeGoogle) -> None:
    alice = _connected(h)

    assert alice.delete("/api/account", headers=WRITE).status_code == 204

    assert google.revoked == [fake.TOKEN]
    assert h.service.store.account_by_email(ALICE) is None


def test_a_revoke_that_fails_never_stops_the_deletion(
    h: Hosted, google: fake.FakeGoogle, caplog: pytest.LogCaptureFixture
) -> None:
    alice = _connected(h)

    def broken(token: str) -> bool:
        raise ConnectionError(f"synthetic {token}")

    google.revoke = broken  # type: ignore[method-assign]

    assert alice.delete("/api/account", headers=WRITE).status_code == 204
    assert h.service.store.account_by_email(ALICE) is None
    assert fake.TOKEN not in caplog.text


def test_deleting_an_account_without_gmail_revokes_nothing(
    h: Hosted, google: fake.FakeGoogle
) -> None:
    alice = h.sign_in(ALICE)

    assert alice.delete("/api/account", headers=WRITE).status_code == 204
    assert google.revoked == []


def test_reconnecting_another_mailbox_revokes_the_old_one(
    h: Hosted, google: fake.FakeGoogle
) -> None:
    alice = _connected(h)
    google.token = "1//second-synthetic-token"
    google.messages = ()
    _Other.address_of(google, "other.mailbox@example.com")

    state = _start(alice)["state"]
    assert _outcome(_back(alice, code="c", state=state)) == "connected"

    assert google.revoked == [fake.TOKEN]
    assert alice.get(STATUS).json()["address"] == "other.mailbox@example.com"


def test_reconnecting_the_same_mailbox_keeps_googles_grant(
    h: Hosted, google: fake.FakeGoogle
) -> None:
    alice = _connected(h)
    google.token = "1//second-synthetic-token"

    state = _start(alice)["state"]
    assert _outcome(_back(alice, code="c", state=state)) == "connected"

    assert google.revoked == []


class _Other:
    @staticmethod
    def address_of(google: fake.FakeGoogle, address: str) -> None:
        real = google.mailbox

        def opened(client, refresh_token):  # noqa: ANN001, ANN202
            found = real(client, refresh_token)
            found.mail_address = address
            return found

        google.mailbox = opened  # type: ignore[method-assign]


def test_a_token_that_cannot_be_stored_is_revoked(
    h: Hosted, google: fake.FakeGoogle, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = h.sign_in(ALICE)
    state = _start(alice)["state"]

    def broken(*args: object) -> None:
        raise sqlite3.OperationalError("synthetic")

    monkeypatch.setattr(mailbox, "store", broken)

    assert _outcome(_back(alice, code="c", state=state)) == "failed"
    assert google.revoked == [fake.TOKEN]
    assert alice.get(STATUS).json()["connected"] is False


def test_disconnecting_works_with_the_feature_off(h: Hosted, google: fake.FakeGoogle) -> None:
    alice = _connected(h)
    h.app.state.mailbox.client = None

    found = alice.delete(STATUS, headers=WRITE).json()

    assert found["available"] is False and found["revoked"] is True
    assert google.revoked == [fake.TOKEN]
    with closing(_connect(h, ALICE)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mailbox_google").fetchone()[0] == 0


def test_disconnecting_stops_a_running_read(
    h: Hosted, google: fake.FakeGoogle, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = _connected(h)
    hooks = h.app.state.mailbox
    account = h.service.store.account_by_email(ALICE)
    monkeypatch.setattr(mailbox_routes, "DISCONNECT_WAIT", 0.05)

    with hooks.lock(account.id):  # a read that does not finish in time
        found = alice.delete(STATUS, headers=WRITE).json()
        assert hooks.cancelled(account.id)  # it is told to stop

    assert found["connected"] is False and google.revoked == [fake.TOKEN]


def test_the_sweep_leaves_a_refused_token_to_the_person(h: Hosted, google: fake.FakeGoogle) -> None:
    _connected(h)
    with closing(_connect(h, ALICE)) as conn, conn:
        mailbox.mark(conn, "reconnect", synced=False)
    before = len(google.opened)

    assert mailbox_routes.sweep(h.app.state.mailbox) == (0, 0)
    assert len(google.opened) == before


def test_googles_callback_passes_a_closed_gate(tmp_path: Path) -> None:
    h = _hosted(tmp_path)
    alice = h.sign_in(ALICE, gate=True)

    assert alice.get(STATUS).status_code == 403  # the rest stays behind the gate
    assert _outcome(_back(alice, code="c", state="made-up")) == "failed"
