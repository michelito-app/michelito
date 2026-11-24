"""AI proposals (`web.proposals`, `web.proposal_routes`) on the local board, with the synthetic
statements: what a proposal may hold, and applying, partly applying or dismissing it."""

from __future__ import annotations

from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import catalog, spending
from michelito.web import proposals
from michelito.web.app import create_app
from michelito.web.proposals import Change, ProposalError
from tests.test_spending import seed

WRITE = {"X-Michelito": "1"}


@pytest.fixture
def path(tmp_path: Path) -> Path:
    found = tmp_path / "michelito.db"
    with closing(db.connect(found)) as conn:
        seed(conn)
    return found


@pytest.fixture
def board(path: Path) -> TestClient:
    return TestClient(create_app(path, today=lambda: date(2026, 2, 12)), "http://127.0.0.1")


def _flow(conn) -> list[spending.Movement]:  # noqa: ANN001
    return [m for m in spending.load_all(conn, (), None, date(2026, 2, 12)) if m.kind == "expense"]


def _targets(conn) -> list[int]:  # noqa: ANN001
    """Expense categories a person can choose."""
    return [c.id for c in catalog.load(conn).items if c.kind == "expense" and not c.hidden]


def _propose(path: Path, picks: int = 2, scope: str = "transaction") -> tuple[int, list]:
    with closing(db.connect(path)) as conn:
        flow = [m for m in _flow(conn) if not m.link][:picks]
        target = next(c for c in _targets(conn) if all(c != _id(conn, m) for m in flow))
        changes = [Change(m.fingerprint, target, scope, "reason") for m in flow]  # type: ignore[arg-type]
        return proposals.propose(conn, _flow(conn), "Claude", "Title", "Because", changes), flow


def _id(conn, movement: spending.Movement) -> int | None:  # noqa: ANN001
    found = catalog.load(conn).by_ref(movement.ref)
    return None if found is None else found.id


def test_a_proposal_keeps_a_snapshot_and_starts_open(path: Path, board: TestClient) -> None:
    proposal_id, flow = _propose(path)

    (found,) = board.get("/api/proposals").json()

    assert found["id"] == proposal_id and found["status"] == "open"
    assert found["title"] == "Title" and found["explanation"] == "Because"
    assert [i["fingerprint"] for i in found["items"]] == [m.fingerprint for m in flow]
    assert all(i["to_category"] and i["from_category"] for i in found["items"])


def test_what_a_proposal_cannot_hold(path: Path) -> None:
    with closing(db.connect(path)) as conn:
        flow = _flow(conn)
        movement = next(m for m in flow if not m.link)
        target = _targets(conn)[0]
        cases = {
            "unknown_transaction": [Change("nope", target, "transaction")],
            "repeated_transaction": [
                Change(movement.fingerprint, target, "transaction"),
                Change(movement.fingerprint, target, "merchant"),
            ],
            "unknown_category": [Change(movement.fingerprint, 999_999, "transaction")],
            "items": [],
        }
        for code, changes in cases.items():
            with pytest.raises(ProposalError) as error:
                proposals.propose(conn, flow, "Claude", "x", "", changes)
            assert error.value.code == code
        with pytest.raises(ProposalError) as error:
            proposals.propose(conn, flow, "Claude", "​ ", "", [cases["items"]])  # type: ignore[list-item]
        assert error.value.code == "title"


def test_too_many_open_proposals_are_refused(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(proposals, "OPEN_MAX", 1)
    _propose(path, 1)

    with pytest.raises(ProposalError) as error:
        _propose(path, 1)

    assert error.value.code == "too_many_open"


def test_applying_part_of_a_proposal_skips_the_rest(path: Path, board: TestClient) -> None:
    proposal_id, flow = _propose(path)
    found = board.get("/api/proposals").json()[0]
    first, second = found["items"]

    answer = board.post(
        f"/api/proposals/{proposal_id}/apply", json={"item_ids": [first["id"]]}, headers=WRITE
    )

    assert answer.status_code == 200, answer.text
    done = {i["id"]: i["status"] for i in answer.json()["items"]}
    assert done == {first["id"]: "applied", second["id"]: "skipped"}
    changed = board.get(f"/api/transactions/{flow[0].fingerprint}").json()
    untouched = board.get(f"/api/transactions/{flow[1].fingerprint}").json()
    assert changed["category_id"] == first["to_category_id"]
    assert untouched["category_id"] != second["to_category_id"]
    entry = board.get("/api/log").json()["items"][0]
    assert entry["author"] == "claude"


def test_a_merchant_rule_applies_through_the_transaction(path: Path, board: TestClient) -> None:
    proposal_id, flow = _propose(path, 1, "merchant")
    item = board.get("/api/proposals").json()[0]["items"][0]

    answer = board.post(
        f"/api/proposals/{proposal_id}/apply", json={"item_ids": [item["id"]]}, headers=WRITE
    )

    assert answer.json()["items"][0]["status"] == "applied"
    row = board.get(f"/api/transactions/{flow[0].fingerprint}").json()
    assert row["category_id"] == item["to_category_id"]


def test_dismissing_changes_nothing_and_answers_once(path: Path, board: TestClient) -> None:
    proposal_id, flow = _propose(path, 1)
    before = board.get(f"/api/transactions/{flow[0].fingerprint}").json()["category_id"]

    answer = board.post(f"/api/proposals/{proposal_id}/dismiss", headers=WRITE)

    assert answer.json()["status"] == "dismissed"
    assert answer.json()["items"][0]["status"] == "skipped"
    assert board.get(f"/api/transactions/{flow[0].fingerprint}").json()["category_id"] == before
    assert board.post(f"/api/proposals/{proposal_id}/dismiss", headers=WRITE).status_code == 409
    assert board.post("/api/proposals/999/dismiss", headers=WRITE).status_code == 404


def test_an_item_of_another_proposal_is_refused(path: Path, board: TestClient) -> None:
    first, _ = _propose(path, 1)
    _propose(path, 1)
    other = board.get("/api/proposals").json()[0]["items"][0]["id"]  # the newest one's item

    answer = board.post(f"/api/proposals/{first}/apply", json={"item_ids": [other]}, headers=WRITE)

    assert answer.status_code == 422


def test_a_proposal_being_applied_cannot_be_applied_again(path: Path, board: TestClient) -> None:
    proposal_id, _ = _propose(path, 1)
    with closing(db.connect(path)) as conn:
        assert proposals.claim(conn, proposal_id) is True
        assert proposals.claim(conn, proposal_id) is False

    answer = board.post(f"/api/proposals/{proposal_id}/apply", json={"item_ids": []}, headers=WRITE)

    assert answer.status_code == 409
    with closing(db.connect(path)) as conn:
        proposals.release(conn, proposal_id)
        assert proposals.claim(conn, proposal_id) is True
