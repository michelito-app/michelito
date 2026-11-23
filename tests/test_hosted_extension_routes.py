"""The browser extension's routes (`hosted.extension_routes`): the code from Settings, its
exchange for a token, the item names it sends and their revocation. Every address, order number
and item name is made up."""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import receipt_items
from michelito.analysis.receipt_items import Item
from michelito.hosted import extension_bundle, extension_routes
from tests.hosted_helpers import WRITE, Hosted, hosted

ALICE = "alice@example.com"
BRUNO = "bruno@example.com"
STATUS = "/api/extension"
CODE = "/api/extension/code"
LINK = extension_routes.LINK_PATH
ORDERS = extension_routes.ORDERS_PATH
DOWNLOAD = "/api/extension/download"
ORIGIN = {"Origin": extension_routes.EXTENSION_ORIGIN}
FIRST = "111-1111111-1111111"
SECOND = "222-2222222-2222222"


@pytest.fixture
def h(tmp_path: Path) -> Hosted:
    return hosted(tmp_path)


def _code(client: TestClient) -> str:
    answer = client.post(CODE, headers=WRITE)
    assert answer.status_code == 200, answer.text
    return str(answer.json()["code"])


def _token(h: Hosted, client: TestClient) -> str:
    plain = h.client()
    answer = plain.post(LINK, json={"code": _code(client)}, headers={**WRITE, **ORIGIN})
    assert answer.status_code == 200, answer.text
    return str(answer.json()["token"])


def _bearer(token: str) -> dict[str, str]:
    return {**WRITE, **ORIGIN, "Authorization": f"Bearer {token}"}


def _orders(*orders: tuple[str, list[dict[str, object]]]) -> dict[str, object]:
    return {"orders": [{"order": number, "items": items} for number, items in orders]}


def _send(h: Hosted, token: str, body: object) -> object:
    return h.client().put(ORDERS, json=body, headers=_bearer(token))


def _items(h: Hosted, email: str) -> dict[str, tuple[Item, ...]]:
    account = h.service.store.account_by_email(email)
    assert account is not None
    workspace = h.service.workspace_of(account)
    with closing(db.connect(workspace.database, workspace.key)) as conn:
        return receipt_items.by_order(conn)


TOO_MANY = range(extension_routes.ORDERS_PER_REQUEST + 1)
HEADPHONES = {"title": "Synthetic headphones", "quantity": 1, "price_cents": 2999}


# Linking.


def test_settings_shows_an_unlinked_extension_first(h: Hosted) -> None:
    alice = h.sign_in(ALICE)

    found = alice.get(STATUS).json()

    assert found == {"linked": False, "linked_at": None, "last_used_at": None, "orders": 0}


def test_a_code_from_settings_becomes_a_token_once(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    code = _code(alice)
    plain = h.client()

    answer = plain.post(LINK, json={"code": code}, headers={**WRITE, **ORIGIN})
    again = plain.post(LINK, json={"code": code}, headers={**WRITE, **ORIGIN})

    assert answer.status_code == 200
    assert answer.headers["access-control-allow-origin"] == extension_routes.EXTENSION_ORIGIN
    assert answer.json()["token"].startswith("mchx_")
    assert again.status_code == 400
    status = alice.get(STATUS).json()
    assert status["linked"] is True and status["linked_at"] is not None


def test_the_code_needs_a_session_and_the_header(h: Hosted) -> None:
    assert h.client().post(CODE, headers=WRITE).status_code == 401
    alice = h.sign_in(ALICE)
    assert alice.post(CODE).status_code == 403


def test_a_wrong_code_is_refused_and_guessing_is_limited(h: Hosted) -> None:
    plain = h.client()
    answers = [
        plain.post(LINK, json={"code": "AAAA-BBBB-CCCC"}, headers={**WRITE, **ORIGIN}).status_code
        for _ in range(extension_routes.ExtensionCaps().links_per_source + 1)
    ]

    assert set(answers[:-1]) == {400}
    assert answers[-1] == 429


def test_a_web_page_cannot_use_the_extension_routes(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    token = _token(h, alice)
    page = {"Origin": "https://attacker.example"}

    link = h.client().post(LINK, json={"code": _code(alice)}, headers={**WRITE, **page})
    send = h.client().put(
        ORDERS,
        json=_orders((FIRST, [HEADPHONES])),
        headers={**WRITE, **page, "Authorization": f"Bearer {token}"},
    )

    assert link.status_code == 403 and send.status_code == 403
    assert "access-control-allow-origin" not in link.headers
    assert _items(h, ALICE) == {}


# Sending names.


def test_the_token_stores_the_item_names_of_each_order(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    token = _token(h, alice)
    body = _orders(
        (FIRST, [HEADPHONES, {"title": "  Cable​  USB\n", "quantity": 2}]),
        (SECOND, [{"title": "Desk lamp"}]),
    )

    answer = _send(h, token, body)

    assert answer.status_code == 200, answer.text  # type: ignore[attr-defined]
    assert answer.json() == {"orders": 2, "items": 3, "with_receipt": 0}  # type: ignore[attr-defined]
    assert _items(h, ALICE) == {
        FIRST: (Item("Synthetic headphones", 1, 2999), Item("Cable USB", 2, None)),
        SECOND: (Item("Desk lamp", None, None),),
    }
    status = alice.get(STATUS).json()
    assert status["orders"] == 2 and status["last_used_at"] is not None


def test_sending_the_same_orders_again_changes_nothing(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    token = _token(h, alice)
    body = _orders((FIRST, [HEADPHONES]))

    _send(h, token, body)
    _send(h, token, body)

    assert _items(h, ALICE) == {FIRST: (Item("Synthetic headphones", 1, 2999),)}


def test_each_token_writes_only_its_own_account(h: Hosted) -> None:
    alice, bruno = h.sign_in(ALICE), h.sign_in(BRUNO)
    alice_token = _token(h, alice)
    _token(h, bruno)

    _send(h, alice_token, _orders((FIRST, [HEADPHONES])))

    assert FIRST in _items(h, ALICE)
    assert _items(h, BRUNO) == {}


def test_the_token_opens_nothing_else(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    token = _token(h, alice)
    plain = h.client()

    for path in ("/api/transactions", STATUS, "/api/auth/me", "/api/mailbox"):
        assert plain.get(path, headers=_bearer(token)).status_code == 401, path
    assert plain.post(CODE, headers=_bearer(token)).status_code == 401
    assert plain.delete(STATUS, headers=_bearer(token)).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {**WRITE, **ORIGIN},
        {**WRITE, **ORIGIN, "Authorization": "Bearer mchx_not-a-token"},
        {**WRITE, **ORIGIN, "Authorization": "Basic abc"},
    ],
)
def test_without_a_valid_token_nothing_is_written(h: Hosted, headers: dict[str, str]) -> None:
    h.sign_in(ALICE)

    answer = h.client().put(ORDERS, json=_orders((FIRST, [HEADPHONES])), headers=headers)

    assert answer.status_code == 401
    assert _items(h, ALICE) == {}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"orders": []},
        _orders(("not-an-order", [HEADPHONES])),
        _orders((FIRST, [])),
        _orders((FIRST, [{"title": ""}])),
        _orders((FIRST, [{"title": " ​\n "}])),
        _orders((FIRST, [{"title": "x" * 301}])),
        _orders((FIRST, [{"title": "Lamp", "quantity": 0}])),
        _orders((FIRST, [{"title": "Lamp", "quantity": "2"}])),
        _orders((FIRST, [{"title": "Lamp", "price_cents": -1}])),
        _orders((FIRST, [{"title": "Lamp", "html": "<b>x</b>"}])),
        _orders((FIRST, [{"title": "Lamp"}] * 51)),
        {"orders": [{"order": FIRST, "items": [HEADPHONES], "address": "1 Synthetic St"}]},
        {
            "orders": [
                {"order": f"{n:03d}-{n:07d}-{n:07d}", "items": [HEADPHONES]} for n in TOO_MANY
            ]
        },
    ],
)
def test_only_the_order_number_and_item_fields_are_accepted(h: Hosted, body: object) -> None:
    alice = h.sign_in(ALICE)
    token = _token(h, alice)

    answer = _send(h, token, body)

    assert answer.status_code == 422  # type: ignore[attr-defined]
    assert _items(h, ALICE) == {}


def test_a_body_over_the_limit_is_refused_before_reading(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    token = _token(h, alice)
    big = json.dumps({"orders": [], "padding": "x" * (extension_routes.BODY_LIMIT + 1)})

    answer = h.client().put(
        ORDERS, content=big, headers={**_bearer(token), "Content-Type": "application/json"}
    )

    assert answer.status_code == 413


def test_sending_is_rate_limited_per_account(tmp_path: Path) -> None:
    h = hosted(tmp_path, extension=extension_routes.ExtensionCaps(orders_per_hour=2))
    alice = h.sign_in(ALICE)
    token = _token(h, alice)
    body = _orders((FIRST, [HEADPHONES]))

    codes = [_send(h, token, body).status_code for _ in range(3)]  # type: ignore[attr-defined]

    assert codes == [200, 200, 429]


def test_the_answer_counts_the_orders_that_have_an_email_receipt(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    token = _token(h, alice)
    account = h.service.store.account_by_email(ALICE)
    assert account is not None
    workspace = h.service.workspace_of(account)
    with closing(db.connect(workspace.database, workspace.key)) as conn, conn:
        _a_receipt(conn, FIRST)

    answer = _send(h, token, _orders((FIRST, [HEADPHONES]), (SECOND, [HEADPHONES])))

    assert answer.json()["with_receipt"] == 1  # type: ignore[attr-defined]


def _a_receipt(conn: sqlite3.Connection, order: str) -> None:
    now = "2026-02-14T15:00:00+00:00"
    email = conn.execute(
        "INSERT INTO receipt_emails (message_id, source, parser, received_at, status, "
        "created_at, updated_at) VALUES ('m1', 'gmail', 'amazon_order', ?, 'read', ?, ?)",
        (now, now, now),
    ).lastrowid
    receipt = conn.execute(
        "INSERT INTO receipts (email_id, position, merchant, kind, amount_cents, currency) "
        "VALUES (?, 0, 'Amazon', 'order', 2999, 'USD')",
        (email,),
    ).lastrowid
    conn.execute(
        "INSERT INTO receipt_orders (receipt_id, order_number, position) VALUES (?, ?, 0)",
        (receipt, order),
    )


# Revoking.


def test_revoking_from_settings_stops_the_extension_at_once(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    token = _token(h, alice)

    answer = alice.delete(STATUS, headers=WRITE)

    assert answer.status_code == 200 and answer.json()["linked"] is False
    assert _send(h, token, _orders((FIRST, [HEADPHONES]))).status_code == 401  # type: ignore[attr-defined]


def test_the_names_already_sent_stay_after_revoking(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    token = _token(h, alice)
    _send(h, token, _orders((FIRST, [HEADPHONES])))

    alice.delete(STATUS, headers=WRITE)

    assert FIRST in _items(h, ALICE)


# The download.


def test_settings_downloads_the_extension_as_a_zip(h: Hosted) -> None:
    alice = h.sign_in(ALICE)

    answer = alice.get(DOWNLOAD)

    assert answer.status_code == 200
    assert answer.headers["content-type"] == "application/zip"
    assert "attachment" in answer.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(answer.content)).namelist()
    assert "manifest.json" in names
    assert not any(name.endswith(".test.ts") or "/." in name for name in names)
    assert h.client().get(DOWNLOAD).status_code == 401


def test_the_zip_is_the_same_bytes_every_time() -> None:
    assert extension_bundle.bundle() == extension_bundle.bundle()


def test_the_manifest_key_gives_the_allowed_origin() -> None:
    manifest = json.loads((extension_bundle.SOURCE / "manifest.json").read_text())

    assert extension_bundle.extension_id(manifest["key"]) == extension_routes.EXTENSION_ID


def test_the_manifest_asks_only_for_the_order_pages_and_michelito() -> None:
    manifest = json.loads((extension_bundle.SOURCE / "manifest.json").read_text())

    assert manifest["manifest_version"] == 3
    assert sorted(manifest["permissions"]) == ["scripting", "storage"]
    assert sorted(manifest["host_permissions"]) == [
        "https://michelito.app/api/extension/*",
        "https://www.amazon.com/your-orders/orders*",
    ]
    assert "content_scripts" not in manifest


def test_the_zip_has_every_file_the_manifest_names() -> None:
    archive = zipfile.ZipFile(io.BytesIO(extension_bundle.bundle()))
    names = set(archive.namelist())
    manifest = json.loads(archive.read("manifest.json"))

    named = {
        manifest["background"]["service_worker"],
        manifest["action"]["default_popup"],
        *manifest["icons"].values(),
        *manifest["action"]["default_icon"].values(),
    }
    assert named <= names
    assert {"reader.js", "walk.js", "_locales/es/messages.json"} <= names
    assert archive.read("icons/icon16.png").startswith(b"\x89PNG")


def test_the_privacy_page_says_what_the_extension_reads_in_both_languages(h: Hosted) -> None:
    page = h.client().get("/privacy").text

    assert page.count("www.amazon.com/your-orders/orders") == 2
    assert "The Chrome extension for Amazon" in page
    assert "La extensión de Chrome para Amazon" in page  # spanish-ui
