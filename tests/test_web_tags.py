"""Tags through the API (`web.tag_routes`), made-up data: create, list, tag many in one log
entry and undo it, chips on rows, a group tag that holds its group's movements (the user's
share only), "mark all as one-off", candidates, the write header and the claude author."""

from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import ledger_store
from michelito.analysis.ledger import Split
from tests.test_web_log import (
    DELIVERY,
    WITHDRAWAL,
    WRITE,
    _fp,
    _fps,
    _log,
    _tx,
    _undo,
)
from tests.test_web_log import client as client  # noqa: F401 (fixture)

CLAUDE = {**WRITE, "X-Michelito-Author": "claude"}
PHARMACY = "FARMACIA INVENTADA"
CAFE = "CAFE FICTICIO"


def _expenses(client: TestClient) -> list[str]:
    """Two made-up expenses of the fixture: RD$ 500 and RD$ 300."""
    return [_fp(client, PHARMACY), _fp(client, CAFE)]


def _create(client: TestClient, name: str = "Party", headers: dict = WRITE):
    return client.post("/api/tags", json={"name": name}, headers=headers)


def _tag(client: TestClient, tag_id: int) -> dict:
    response = client.get(f"/api/tags/{tag_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _add(client: TestClient, tag_id: int, fps: list[str], headers: dict = WRITE):
    return client.post(
        f"/api/tags/{tag_id}/transactions", json={"fingerprints": fps}, headers=headers
    )


def _shared_group(tmp_path: Path, fingerprint: str) -> int:
    """A group where the user paid RD$ 20,000 (this transaction) split in two, and a friend
    paid RD$ 3,000 split in two: the user's share is 10,000 + 1,500."""
    with closing(db.connect(tmp_path / "michelito.db")) as conn, conn:
        me = ledger_store.ensure_me(conn)
        friend = ledger_store.create_contact(conn, "Made-up Friend")
        group = ledger_store.create_group(conn, "Beach trip", [friend])
        ledger_store.add_entry(
            conn,
            group,
            paid_by=me,
            amount=Decimal("20000"),
            currency="DOP",
            day=date(2026, 1, 10),
            description="Hotel",
            splits=[Split(me, Decimal("10000")), Split(friend, Decimal("10000"))],
            mode="exact",
            fingerprint=fingerprint,
        )
        ledger_store.add_entry(
            conn,
            group,
            paid_by=friend,
            amount=Decimal("3000"),
            currency="DOP",
            day=date(2026, 1, 11),
            description="Dinner",
            splits=[Split(me, Decimal("1500")), Split(friend, Decimal("1500"))],
            mode="exact",
        )
        return group


def test_create_list_and_get_a_tag(client: TestClient) -> None:
    made = _create(client, "Furnish the apartment")

    assert made.status_code == 201, made.text
    listed = client.get("/api/tags").json()
    assert [(t["name"], t["spent_cents"], t["count"]) for t in listed] == [
        ("Furnish the apartment", 0, 0)
    ]
    assert _tag(client, made.json()["id"])["members"] == []


def test_duplicate_name_is_409(client: TestClient) -> None:
    _create(client, "Party")

    assert _create(client, "PARTY").status_code == 409


def test_tagging_many_is_one_log_entry_and_undo_untags_all(client: TestClient) -> None:
    tag = _create(client).json()["id"]
    fps = _expenses(client)

    added = _add(client, tag, fps)

    assert added.status_code == 200, added.text
    assert added.json()["added"] == 2
    entry = _log(client)[0]
    assert (entry["kind"], sorted(entry["fingerprints"])) == ("tag_add", sorted(fps))
    detail = _tag(client, tag)
    assert (detail["count"], detail["spent_cents"]) == (2, 80000)
    assert _undo(client, entry["id"]).is_success
    assert _tag(client, tag)["count"] == 0


def test_rows_carry_their_tags(client: TestClient) -> None:
    tag = _create(client, "Party").json()["id"]
    fp = _fp(client, DELIVERY)
    _add(client, tag, [fp])

    chips = _tx(client, fp)["tags"]

    assert chips == [{"id": tag, "name": "Party", "color": None, "derived": False}]


def test_group_tag_holds_the_users_share_and_refuses_untagging_it(
    client: TestClient, tmp_path: Path
) -> None:
    hotel = _fp(client, WITHDRAWAL)
    _shared_group(tmp_path, hotel)
    (group_tag,) = [t for t in client.get("/api/tags").json() if t["group_id"] is not None]

    detail = _tag(client, group_tag["id"])

    assert detail["spent_cents"] == 1150000
    assert {m["via"] for m in detail["members"]} == {"group"}
    assert all(m["derived"] for m in detail["members"])
    refused = client.request(
        "DELETE",
        f"/api/tags/{group_tag['id']}/transactions",
        json={"fingerprints": [hotel]},
        headers=WRITE,
    )
    assert refused.status_code == 400
    assert client.delete(f"/api/tags/{group_tag['id']}", headers=WRITE).status_code == 400


def test_mark_all_as_one_off_marks_only_counted_members(client: TestClient) -> None:
    tag = _create(client).json()["id"]
    fps = [*_expenses(client), *_fps(client, DELIVERY)]
    _add(client, tag, fps)

    marked = client.post(f"/api/tags/{tag}/one-off", json={"one_off": True}, headers=WRITE)

    assert marked.status_code == 200, marked.text
    assert marked.json()["changed"] == 2
    assert [_tx(client, fp)["one_off"] for fp in fps] == [True, True, False, False, False]
    assert _log(client)[0]["kind"] == "tag_one_off"


def test_candidates_flag_likely_rows_and_default_range(client: TestClient) -> None:
    tag = _create(client).json()["id"]
    _add(client, tag, [_fp(client, DELIVERY)])

    found = client.get(f"/api/tags/{tag}/candidates").json()

    assert found["from"] == "2026-01-05" and found["to"] == "2026-01-05"
    wide = client.get(
        f"/api/tags/{tag}/candidates", params={"from": "2026-01-01", "to": "2026-01-31"}
    ).json()
    rows = {r["fingerprint"]: r for r in wide["items"]}
    assert rows[_fp(client, DELIVERY)]["tagged"] is True
    assert any(r["likely"] for r in wide["items"])
    assert all(r["counted"] for r in wide["items"] if r["likely"])


def test_writes_need_the_header(client: TestClient) -> None:
    assert client.post("/api/tags", json={"name": "Party"}).status_code == 403


def test_claude_author_is_logged(client: TestClient) -> None:
    _create(client, "Party", headers=CLAUDE)

    assert _log(client)[0]["author"] == "claude"


def test_loan_patch_sets_has_payout(client: TestClient) -> None:
    made = client.post(
        "/api/loans",
        json={
            "name": "Fridge",
            "number": "1234567890",
            "currency": "DOP",
            "principal_cents": 6000000,
            "rate_bp": 1800,
            "term": 12,
            "start_date": "2026-01-15",
        },
        headers=WRITE,
    )
    assert made.status_code == 201, made.text
    loan_id = made.json()["id"]

    patched = client.patch(f"/api/loans/{loan_id}", json={"has_payout": True}, headers=WRITE)

    assert patched.status_code == 200, patched.text
    assert patched.json()["has_payout"] is True


def _loan(client: TestClient) -> int:
    made = client.post(
        "/api/loans",
        json={
            "name": "Fridge",
            "number": "1234567890",
            "currency": "DOP",
            "principal_cents": 6000000,
            "rate_bp": 1800,
            "term": 12,
            "start_date": "2026-01-15",
        },
        headers=WRITE,
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


def test_a_tagged_loan_is_listed_with_what_is_left_and_can_be_removed(client: TestClient) -> None:
    tag = _create(client, "Kitchen").json()["id"]
    loan = _loan(client)

    tagged = client.put(f"/api/tags/{tag}/loans/{loan}", headers=WRITE)

    assert tagged.status_code == 200, tagged.text
    (target,) = tagged.json()["targets"]
    assert (target["kind"], target["id"], target["name"], target["has_payout"]) == (
        "loan",
        loan,
        "Fridge",
        False,
    )
    assert target["still_to_pay_cents"] > 0
    client.patch(f"/api/loans/{loan}", json={"has_payout": True}, headers=WRITE)
    (paid_out,) = _tag(client, tag)["targets"]
    assert (paid_out["has_payout"], paid_out["still_to_pay_cents"]) == (True, 0)
    removed = client.delete(f"/api/tags/{tag}/loans/{loan}", headers=WRITE)
    assert removed.json()["targets"] == []


def test_tagging_an_unknown_loan_is_404(client: TestClient) -> None:
    tag = _create(client, "Kitchen").json()["id"]

    assert client.put(f"/api/tags/{tag}/loans/99", headers=WRITE).status_code == 404
