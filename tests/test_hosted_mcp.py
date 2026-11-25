"""The AI connector end to end (`hosted.connector_routes`, `hosted.mcp_routes`): an MCP client
signs in like Claude does, reads the account with masked identifiers, proposes category changes
and the person approves them in Review. Every address and statement is made up."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.hosted.connector import CLAUDE_CALLBACKS, s256
from tests.hosted_helpers import WRITE, Hosted, hosted
from tests.test_spending import seed

ALICE = "alice@example.com"
URL = "https://app.example"
MCP = "/api/mcp"
VERIFIER = "x" * 64


@pytest.fixture
def h(tmp_path: Path) -> Hosted:
    return hosted(tmp_path)


@pytest.fixture
def alice(h: Hosted) -> TestClient:
    client = h.sign_in(ALICE)
    account = h.service.store.account_by_email(ALICE)
    workspace = h.service.workspace_of(account)
    with closing(db.connect(workspace.database, workspace.key)) as conn:
        seed(conn)
    return client


def _connect(h: Hosted, alice: TestClient) -> tuple[str, str]:
    """Sign in like Claude; the client id and the access token."""
    plain = h.client()
    registered = plain.post(
        "/oauth/register", json={"client_name": "Claude", "redirect_uris": [CLAUDE_CALLBACKS[0]]}
    )
    assert registered.status_code == 201, registered.text
    client_id = registered.json()["client_id"]
    started = plain.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": CLAUDE_CALLBACKS[0],
            "code_challenge": s256(VERIFIER),
            "code_challenge_method": "S256",
            "state": "abc",
            "scope": "michelito offline_access",
            "resource": URL + MCP,
        },
        follow_redirects=False,
    )
    assert started.status_code == 302
    consent = urlsplit(started.headers["location"])
    assert f"{consent.scheme}://{consent.netloc}{consent.path}" == URL + "/connect"
    request_id = parse_qs(consent.query)["request"][0]
    shown = alice.get(f"/api/connector/requests/{request_id}")
    assert shown.json() == {"client_name": "Claude", "redirect_host": "claude.ai"}
    decided = alice.post(
        f"/api/connector/requests/{request_id}", json={"approve": True}, headers=WRITE
    )
    back = parse_qs(urlsplit(decided.json()["redirect"]).query)
    assert back["state"] == ["abc"]
    tokens = plain.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": back["code"][0],
            "redirect_uri": CLAUDE_CALLBACKS[0],
            "client_id": client_id,
            "code_verifier": VERIFIER,
        },
    )
    assert tokens.status_code == 200, tokens.text
    assert tokens.headers["cache-control"] == "no-store"
    return client_id, tokens.json()["access_token"]


def _rpc(h: Hosted, token: str, method: str, params: Any = None, **headers: str) -> Any:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        message["params"] = params
    answer = h.client().post(
        MCP, json=message, headers={"Authorization": f"Bearer {token}", **headers}
    )
    assert answer.status_code == 200, answer.text
    return answer.json()


def _tool(h: Hosted, token: str, name: str, **arguments: Any) -> Any:
    result = _rpc(h, token, "tools/call", {"name": name, "arguments": arguments})["result"]
    assert not result.get("isError"), result
    text = result["content"][0]["text"]
    return json.loads(text)


# Discovery and sign-in.


def test_without_a_token_the_endpoint_points_to_its_metadata(h: Hosted) -> None:
    answer = h.client().post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})

    assert answer.status_code == 401
    assert answer.headers["www-authenticate"] == (
        f'Bearer resource_metadata="{URL}/.well-known/oauth-protected-resource"'
    )
    resource = h.client().get("/.well-known/oauth-protected-resource").json()
    assert resource["resource"] == URL + MCP
    assert resource["authorization_servers"] == [URL]
    server = h.client().get("/.well-known/oauth-authorization-server").json()
    assert server["issuer"] == URL
    assert server["code_challenge_methods_supported"] == ["S256"]
    assert server["token_endpoint_auth_methods_supported"] == ["none"]
    assert server["registration_endpoint"] == URL + "/oauth/register"


def test_another_redirect_uri_cannot_register_or_be_redirected_to(h: Hosted) -> None:
    plain = h.client()
    refused = plain.post("/oauth/register", json={"redirect_uris": ["https://evil.example/cb"]})
    answer = plain.get(
        "/oauth/authorize",
        params={"client_id": "mcpk_unknown", "redirect_uri": "https://evil.example/cb"},
        follow_redirects=False,
    )

    assert refused.status_code == 400 and refused.json() == {"error": "invalid_redirect_uri"}
    assert answer.status_code == 400  # never redirected


def test_the_consent_needs_the_persons_session(h: Hosted, alice: TestClient) -> None:
    assert h.client().get("/api/connector/requests/mcpq_x").status_code == 401
    assert alice.get("/api/connector/requests/mcpq_x").status_code == 404


def test_the_token_opens_only_the_mcp_endpoint_and_the_cookie_never_does(
    h: Hosted, alice: TestClient
) -> None:
    _, token = _connect(h, alice)

    assert (
        h.client().get("/api/summary", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )
    assert alice.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
    other = h.client().post(
        MCP,
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Authorization": f"Bearer {token}", "Origin": "https://evil.example"},
    )
    assert other.status_code == 403


# The protocol.


def test_initialize_lists_and_pings(h: Hosted, alice: TestClient) -> None:
    _, token = _connect(h, alice)

    started = _rpc(h, token, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    tools = _rpc(h, token, "tools/list")["result"]["tools"]

    assert started["result"]["protocolVersion"] == "2025-06-18"
    assert "tools" in started["result"]["capabilities"]
    names = {t["name"] for t in tools}
    assert {"list_transactions", "list_categories", "propose_category_changes"} <= names
    assert _rpc(h, token, "ping")["result"] == {}
    notified = h.client().post(
        MCP,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert notified.status_code == 202


def test_reading_masks_identifiers(h: Hosted, alice: TestClient) -> None:
    account = h.service.store.account_by_email(ALICE)
    workspace = h.service.workspace_of(account)
    with closing(db.connect(workspace.database, workspace.key)) as conn, conn:
        conn.execute("UPDATE accounts SET key = 'bhd:savings:111111111' WHERE kind = 'savings'")
    _, token = _connect(h, alice)

    accounts = _tool(h, token, "list_accounts")["data"]

    keys = [a["key"] for a in accounts]
    savings = next(k for k in keys if ":savings:" in k)
    assert savings == "bhd:savings:••1111"
    months = _tool(h, token, "list_months", accounts=[savings])["data"]
    assert months  # the masked key works as a filter


def test_wrong_arguments_are_a_tool_error(h: Hosted, alice: TestClient) -> None:
    _, token = _connect(h, alice)

    result = _rpc(
        h, token, "tools/call", {"name": "list_transactions", "arguments": {"month": "nope"}}
    )["result"]

    assert result["isError"] is True
    assert "month" in result["content"][0]["text"]


# Proposals.


def _a_change(h: Hosted, token: str) -> tuple[str, int, int]:
    """A transaction's fingerprint, its category id and another expense category's id."""
    rows = _tool(h, token, "list_transactions", kind="expense")["data"]["items"]
    row = next(r for r in rows if r["link"] == "")
    categories = _tool(h, token, "list_categories")["data"]
    other = next(
        c["id"]
        for c in categories
        if c["kind"] == "expense" and c["id"] != row["category_id"] and not c.get("hidden")
    )
    return row["fingerprint"], row["category_id"], other


def test_a_proposal_changes_nothing_until_it_is_approved(h: Hosted, alice: TestClient) -> None:
    _, token = _connect(h, alice)
    fingerprint, before, target = _a_change(h, token)

    sent = _tool(
        h,
        token,
        "propose_category_changes",
        title="Recategorize",
        explanation="By merchant",
        changes=[{"fingerprint": fingerprint, "category_id": target, "scope": "transaction"}],
    )

    assert sent["link"].startswith(URL + "/review?proposal=")
    assert alice.get(f"/api/transactions/{fingerprint}").json()["category_id"] == before
    (proposal,) = alice.get("/api/proposals").json()
    assert proposal["status"] == "open" and proposal["source"] == "Claude"
    (item,) = proposal["items"]
    applied = alice.post(
        f"/api/proposals/{proposal['id']}/apply", json={"item_ids": [item["id"]]}, headers=WRITE
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["items"][0]["status"] == "applied"
    assert alice.get(f"/api/transactions/{fingerprint}").json()["category_id"] == target
    log = alice.get("/api/log").json()["items"]
    assert log[0]["author"] == "claude"
    again = alice.post(
        f"/api/proposals/{proposal['id']}/apply", json={"item_ids": []}, headers=WRITE
    )
    assert again.status_code == 409


def test_a_proposal_with_an_unknown_transaction_is_refused(h: Hosted, alice: TestClient) -> None:
    _, token = _connect(h, alice)
    _, _, target = _a_change(h, token)

    result = _rpc(
        h,
        token,
        "tools/call",
        {
            "name": "propose_category_changes",
            "arguments": {
                "title": "x",
                "changes": [{"fingerprint": "nope", "category_id": target, "scope": "merchant"}],
            },
        },
    )["result"]

    assert result["isError"] is True
    assert alice.get("/api/proposals").json() == []


def test_a_revoked_connection_stops_at_once(h: Hosted, alice: TestClient) -> None:
    _, token = _connect(h, alice)
    (connection,) = alice.get("/api/connector/connections").json()

    gone = alice.delete(f"/api/connector/connections/{connection['id']}", headers=WRITE)

    assert gone.status_code == 204
    answer = h.client().post(
        MCP,
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert answer.status_code == 401
    assert 'error="invalid_token"' in answer.headers["www-authenticate"]


# Imports (phase 2).


def test_the_import_tools_are_listed(h: Hosted, alice: TestClient) -> None:
    _, token = _connect(h, alice)

    names = {t["name"] for t in _rpc(h, token, "tools/list")["result"]["tools"]}

    assert {"import_statement", "import_provisional_charges", "import_cash_entries"} <= names


def test_cash_entries_from_the_ai_wait_in_review(h: Hosted, alice: TestClient) -> None:
    _, token = _connect(h, alice)

    sent = _tool(
        h,
        token,
        "import_cash_entries",
        title="Receipts",
        entries=[
            {
                "day": "2026-01-20",
                "description": "MADE UP KIOSK",
                "amount_cents": 15000,
                "currency": "DOP",
                "direction": "out",
            }
        ],
    )

    assert sent["rows"] == 1 and sent["link"].startswith(URL + "/review?proposal=")
    (proposal,) = alice.get("/api/proposals").json()
    assert proposal["kind"] == "cash" and proposal["rows"][0]["description"] == "MADE UP KIOSK"


def test_a_statement_that_does_not_square_tells_the_ai_why(h: Hosted, alice: TestClient) -> None:
    _, token = _connect(h, alice)
    account = next(
        a["key"] for a in _tool(h, token, "list_accounts")["data"] if ":savings:" in a["key"]
    )

    result = _rpc(
        h,
        token,
        "tools/call",
        {
            "name": "import_statement",
            "arguments": {
                "title": "Statement",
                "account": account,
                "period_end": "2026-03-31",
                "sections": [
                    {
                        "currency": "DOP",
                        "printed_debits_cents": 20000,
                        "transactions": [
                            {
                                "day": "2026-03-10",
                                "description": "MADE UP",
                                "amount_cents": 10000,
                                "direction": "debit",
                            }
                        ],
                    }
                ],
            },
        },
    )["result"]

    assert result["isError"] is True
    assert "not_squared" in result["content"][0]["text"]
    assert "200.00" in result["content"][0]["text"]
    assert alice.get("/api/proposals").json() == []


def test_an_unknown_account_is_refused(h: Hosted, alice: TestClient) -> None:
    _, token = _connect(h, alice)

    result = _rpc(
        h,
        token,
        "tools/call",
        {
            "name": "import_provisional_charges",
            "arguments": {
                "title": "x",
                "account": "nope",
                "charges": [
                    {"day": "2026-01-02", "description": "X", "amount_cents": 1, "currency": "DOP"}
                ],
            },
        },
    )["result"]

    assert result["isError"] is True and "unknown account" in result["content"][0]["text"]


# Onboarding.


def test_onboarding_guides_through_the_top_merchants_until_they_are_handled(
    h: Hosted, alice: TestClient
) -> None:
    _, token = _connect(h, alice)
    names = {t["name"] for t in _rpc(h, token, "tools/list")["result"]["tools"]}
    assert "get_onboarding" in names

    first = _tool(h, token, "get_onboarding")["data"]

    assert first["stage"] == "merchants"
    assert first["links"]["upload"] == URL + "/import"
    pending = first["merchants"]
    assert pending and all(m["status"] == "pending" for m in pending)
    assert all(isinstance(m["total_cents"], int) and m["total_cents"] > 0 for m in pending)
    confirmations = [
        {"fingerprint": m["fingerprint"], "category_id": m["category_id"], "scope": "merchant"}
        for m in pending
        if m["category_id"] is not None
    ]
    sent = _tool(h, token, "propose_category_changes", title="Top merchants", changes=confirmations)
    (proposal,) = alice.get("/api/proposals").json()
    applied = alice.post(
        f"/api/proposals/{proposal['id']}/apply",
        json={"item_ids": [i["id"] for i in proposal["items"]]},
        headers=WRITE,
    )
    assert applied.status_code == 200, applied.text
    assert sent["link"].startswith(URL + "/review")

    after = _tool(h, token, "get_onboarding")["data"]

    left = {m["merchant"] for m in after["merchants"]}
    assert left == {m["merchant"] for m in pending if m["category_id"] is None}
    if not left:
        assert after["stage"] in ("checklist", "done")
