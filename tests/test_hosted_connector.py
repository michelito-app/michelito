"""The AI connector's OAuth server (`hosted.connector`): registration, consent, codes with PKCE,
token rotation and the end of a connection. Every address is made up."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from michelito.hosted import connector as oauth
from michelito.hosted.connector import Connector, ConnectorError, Policy, s256
from michelito.hosted.store import Store
from tests.hosted_helpers import Clock

CALLBACK = oauth.CLAUDE_CALLBACKS[0]
RESOURCE = "https://app.example/api/mcp"
VERIFIER = "v" * 50


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "accounts.db")


@pytest.fixture
def connector(store: Store, clock: Clock) -> Connector:
    return Connector(store, Policy(resource=RESOURCE), clock)


def _account(store: Store, email: str = "alice@example.com") -> int:
    with store.connect() as conn, conn:
        cursor = conn.execute(
            "INSERT INTO accounts (email, created_at, status, folder) VALUES (?, 0, 'active', ?)",
            (email, f"{abs(hash(email)):032x}"[:32]),
        )
    return int(cursor.lastrowid or 0)


def _query(client_id: str, **extra: str) -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": CALLBACK,
        "code_challenge": s256(VERIFIER),
        "code_challenge_method": "S256",
        "state": "st-1",
        "resource": RESOURCE,
        **extra,
    }


def _code(connector: Connector, account_id: int) -> tuple[str, str]:
    client = connector.register_client("Claude", [CALLBACK])
    request_id = connector.start(client, _query(client.client_id))
    redirect = connector.decide(request_id, account_id, approve=True)
    assert redirect is not None
    params = parse_qs(urlsplit(redirect).query)
    assert params["state"] == ["st-1"]
    return client.client_id, params["code"][0]


def test_only_claudes_callback_can_be_registered(connector: Connector) -> None:
    with pytest.raises(ConnectorError) as error:
        connector.register_client("Evil", ["https://evil.example/cb"])
    assert error.value.code == "invalid_redirect_uri"

    client = connector.register_client("Claude​ <b>", [CALLBACK])

    assert client.client_id.startswith("mcpk_")
    assert client.name == "Claude <b>"
    assert connector.client(client.client_id) == client


def test_an_authorization_needs_s256_pkce_and_the_right_resource(connector: Connector) -> None:
    client = connector.register_client("Claude", [CALLBACK])
    cases = {
        "invalid_request": {"code_challenge_method": "plain"},
        "invalid_target": {"resource": "https://other.example/mcp"},
        "invalid_scope": {"scope": "admin"},
        "unsupported_response_type": {"response_type": "token"},
    }
    for code, extra in cases.items():
        with pytest.raises(ConnectorError) as error:
            connector.start(client, _query(client.client_id, **extra))
        assert error.value.code == code


def test_the_redirect_uri_must_be_the_clients_own(connector: Connector) -> None:
    client = connector.register_client("Claude", [CALLBACK])

    with pytest.raises(ConnectorError) as error:
        connector.check_client(client.client_id, oauth.CLAUDE_CALLBACKS[1])

    assert error.value.code == "invalid_redirect_uri"


def test_a_refusal_sends_access_denied_back(connector: Connector, store: Store) -> None:
    client = connector.register_client("Claude", [CALLBACK])
    request_id = connector.start(client, _query(client.client_id))

    assert connector.pending(request_id) == oauth.Pending("Claude", "claude.ai")
    redirect = connector.decide(request_id, _account(store), approve=False)

    assert redirect is not None and "error=access_denied" in redirect
    assert connector.pending(request_id) is None  # used up


def test_a_code_needs_its_verifier_and_works_once(connector: Connector, store: Store) -> None:
    account_id = _account(store)
    client_id, code = _code(connector, account_id)

    with pytest.raises(ConnectorError):
        connector.exchange_code(client_id, code, CALLBACK, "w" * 50)
    # A wrong verifier used the code up: the right one no longer works either.
    with pytest.raises(ConnectorError):
        connector.exchange_code(client_id, code, CALLBACK, VERIFIER)

    client_id, code = _code(connector, account_id)
    tokens = connector.exchange_code(client_id, code, CALLBACK, VERIFIER)

    caller = connector.caller(tokens.access_token)
    assert caller is not None and caller.account.id == account_id
    assert caller.client_name == "Claude"


def test_a_code_expires(connector: Connector, store: Store, clock: Clock) -> None:
    client_id, code = _code(connector, _account(store))
    clock.advance(oauth.CODE_SECONDS + 1)

    with pytest.raises(ConnectorError) as error:
        connector.exchange_code(client_id, code, CALLBACK, VERIFIER)

    assert error.value.code == "invalid_grant"


def test_refreshing_rotates_both_tokens(connector: Connector, store: Store, clock: Clock) -> None:
    client_id, code = _code(connector, _account(store))
    first = connector.exchange_code(client_id, code, CALLBACK, VERIFIER)

    second = connector.refresh(client_id, first.refresh_token)

    assert connector.caller(first.access_token) is None
    assert connector.caller(second.access_token) is not None
    with pytest.raises(ConnectorError) as error:
        connector.refresh(client_id, first.refresh_token)
    assert error.value.code == "invalid_grant"
    clock.advance(oauth.ACCESS_SECONDS + 1)
    assert connector.caller(second.access_token) is None  # expired: the client refreshes


def test_an_idle_connection_ends(connector: Connector, store: Store, clock: Clock) -> None:
    account_id = _account(store)
    client_id, code = _code(connector, account_id)
    tokens = connector.exchange_code(client_id, code, CALLBACK, VERIFIER)
    clock.advance(oauth.IDLE_SECONDS + 1)

    with pytest.raises(ConnectorError):
        connector.refresh(client_id, tokens.refresh_token)
    assert connector.connections(account_id) == []


def test_revoking_and_signing_out_everywhere_end_connections(
    connector: Connector, store: Store
) -> None:
    account_id = _account(store)
    for _ in range(2):
        client_id, code = _code(connector, account_id)
        connector.exchange_code(client_id, code, CALLBACK, VERIFIER)
    first, second = connector.connections(account_id)

    assert connector.revoke(_account(store, "bruno@example.com"), first.id) is False
    assert connector.revoke(account_id, first.id) is True
    assert [g.id for g in connector.connections(account_id)] == [second.id]

    store.delete_sessions_of(account_id)

    assert connector.connections(account_id) == []


def test_a_disabled_account_has_no_caller(connector: Connector, store: Store) -> None:
    account_id = _account(store)
    client_id, code = _code(connector, account_id)
    tokens = connector.exchange_code(client_id, code, CALLBACK, VERIFIER)
    with store.connect() as conn, conn:
        conn.execute("UPDATE accounts SET status = 'disabled' WHERE id = ?", (account_id,))

    assert connector.caller(tokens.access_token) is None


def test_prune_forgets_unused_clients_but_keeps_connected_ones(
    connector: Connector, store: Store, clock: Clock
) -> None:
    unused = connector.register_client("Claude", [CALLBACK])
    client_id, code = _code(connector, _account(store))
    connector.exchange_code(client_id, code, CALLBACK, VERIFIER)
    clock.advance(oauth.CLIENT_UNUSED_SECONDS + 1)

    connector.prune()

    assert connector.client(unused.client_id) is None
    assert connector.client(client_id) is not None


def test_a_client_can_only_keep_a_few_requests_waiting(connector: Connector) -> None:
    client = connector.register_client("Claude", [CALLBACK])
    for _ in range(oauth.REQUESTS_PER_CLIENT):
        connector.start(client, _query(client.client_id))

    with pytest.raises(ConnectorError) as error:
        connector.start(client, _query(client.client_id))

    assert error.value.code == "temporarily_unavailable"
