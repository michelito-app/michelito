"""Hosted mode: uploading statements through the gate. Synthetic PDFs only (`tests.synthetic_pdf`,
built from `tests.samples`) and synthetic addresses.

Covers the per-file states (squared, doesn't square, locked/wrong password, unsupported,
duplicate), that only what squares is stored, that the password never shows up anywhere (logs,
responses, the databases, any file), that no PDF is left on disk, the data-free fingerprint of
failures, the limits, the share target and that a job belongs to its account only.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.hosted import uploads
from michelito.hosted.onboarding_routes import UploadCaps
from tests import samples
from tests.hosted_helpers import WRITE, Hosted, hosted
from tests.synthetic_pdf import build

ALICE = "alice@example.com"
BOB = "bob@example.com"
PASSWORD = "made-up-password-xyz"
POPULAR = build(samples.POPULAR_PAGES)
BHD_LOCKED = build(samples.BHD_TC_PAGES, PASSWORD)
SAVINGS = build(samples.BHD_AHORRO_PAGES)
WRONG_TOTAL = build((samples.POPULAR_DOP_WRONG_TOTAL,))
UNKNOWN = build((samples.UNKNOWN,))


def payload(*files: tuple[str, bytes]) -> dict:
    return {"files": [{"name": n, "data": base64.b64encode(d).decode()} for n, d in files]}


def upload(client: TestClient, *files: tuple[str, bytes]) -> dict:
    answer = client.post("/api/uploads", json=payload(*files), headers=WRITE)
    assert answer.status_code == 202, answer.text
    return wait(client, answer.json()["id"])


def wait(client: TestClient, job_id: str) -> dict:
    for _ in range(200):
        job = client.get(f"/api/uploads/{job_id}").json()
        if job["done"]:
            return job
        time.sleep(0.02)
    raise AssertionError("the upload never finished")


def states(job: dict) -> dict[str, str]:
    return {f["name"]: f["state"] for f in job["files"]}


# The data keys of the account databases these tests opened (they are encrypted).
_KEYS: dict[Path, bytes] = {}


def user_db(h: Hosted, email: str) -> Path:
    account = h.service.store.account_by_email(email)
    path = h.data / "users" / account.folder / "michelito.db"
    _KEYS[path] = h.service._data_key(account)
    return path


def open_user_db(path: Path) -> sqlite3.Connection:
    """An account's database, opened with its data key (`user_db` looked it up)."""
    return db.connect(path, _KEYS[path])


def count(path: Path, table: str) -> int:
    with closing(open_user_db(path)) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@pytest.fixture
def h(tmp_path: Path) -> Hosted:
    return hosted(tmp_path)


def test_a_new_account_is_gated_until_a_statement_squares(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    gate = alice.get("/api/onboarding").json()
    assert gate["open"] is False and gate["landing"] is None
    job = upload(alice, ("card.pdf", POPULAR))
    assert states(job) == {"card.pdf": "squared"}
    reads = job["files"][0]["reads"]
    assert reads == [
        {
            "bank": "popular",
            "kind": "credit_card",
            "identifier": "1234",
            "month": "2026-01",
            "transactions": 4,
        }
    ]
    assert job["squared"] == 1
    opened = alice.get("/api/onboarding").json()
    assert opened["open"] is True
    assert opened["landing"] == alice.get("/api/months").json()[0]["month"]
    assert count(user_db(h, ALICE), "transactions") > 0


def test_per_file_states_and_only_what_squares_is_kept(
    h: Hosted, caplog: pytest.LogCaptureFixture
) -> None:
    alice = h.sign_in(ALICE)
    caplog.set_level(logging.WARNING)
    job = upload(alice, ("bad.pdf", WRONG_TOTAL), ("other.pdf", UNKNOWN), ("x.pdf", b"not a pdf"))
    assert states(job) == {"bad.pdf": "invalid", "other.pdf": "unsupported", "x.pdf": "unreadable"}
    assert job["squared"] == 0
    database = user_db(h, ALICE)
    assert count(database, "documents") == 0 and count(database, "statements") == 0
    assert alice.get("/api/onboarding").json()["open"] is False
    # The fingerprints: structure only.
    lines = [r.getMessage() for r in caplog.records if "upload not stored" in r.getMessage()]
    assert any("stage=validate" in line and "parser=popular_card" in line for line in lines)
    assert any("stage=detect" in line and "pages=1" in line for line in lines)
    text = "\n".join(lines)
    for leaked in ("1600", "1,600", "1234", "SUPERMERCADO", "INVENTADA", "ESTADO", ".pdf"):
        assert leaked not in text


def test_the_fingerprint_names_the_failing_checks_without_values() -> None:
    examined = uploads.examine(WRONG_TOTAL, "")
    assert examined.state == uploads.INVALID
    assert examined.fingerprint is not None
    line = examined.fingerprint.line()
    assert "section1:" in line and "bank=popular" in line
    checks = line.split("checks=")[1].split(",")
    assert all(re.fullmatch(r"part\d+:(section\d+:)?[a-z_]+", check) for check in checks), line


def test_wrong_password_asks_again_for_that_bank_only_and_never_leaks(
    h: Hosted, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    caplog.set_level(logging.DEBUG)
    alice = h.sign_in(ALICE)
    job = upload(alice, ("bhd.pdf", BHD_LOCKED), ("card.pdf", POPULAR))
    assert states(job) == {"bhd.pdf": "locked", "card.pdf": "squared"}
    wrong = alice.post(
        f"/api/uploads/{job['id']}/password",
        json={"bank": "bhd", "password": "not-it-123"},
        headers=WRITE,
    )
    assert wrong.status_code == 200
    assert wrong.json()["misses"] == ["bhd"]
    assert states(wrong.json())["bhd.pdf"] == "locked"
    right = alice.post(
        f"/api/uploads/{job['id']}/password",
        json={"bank": "bhd", "password": PASSWORD},
        headers=WRITE,
    )
    assert right.status_code == 200, right.text
    assert states(right.json()) == {"bhd.pdf": "squared", "card.pdf": "squared"}
    assert right.json()["misses"] == []
    for answer in (wrong, right):
        assert PASSWORD not in answer.text and "not-it-123" not in answer.text
    # Nowhere: logs, either database, any file of the hosted folder.
    assert PASSWORD not in caplog.text and "not-it-123" not in caplog.text
    for path in h.data.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert PASSWORD.encode() not in data, path
            assert b"not-it-123" not in data, path


def test_a_malformed_password_body_never_echoes_it(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    job = upload(alice, ("bhd.pdf", BHD_LOCKED))
    for body in (
        {"bank": "bhd", "password": PASSWORD * 10},
        {"bank": "nowhere", "password": PASSWORD},
        {"bank": "bhd", "password": [PASSWORD]},
    ):
        answer = alice.post(f"/api/uploads/{job['id']}/password", json=body, headers=WRITE)
        assert answer.status_code == 422
        assert PASSWORD not in answer.text


def test_no_pdf_is_left_on_disk(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    temp = Path(tempfile.gettempdir())
    before = {p for p in temp.iterdir()}
    upload(alice, ("bhd.pdf", BHD_LOCKED), ("card.pdf", POPULAR), ("bad.pdf", WRONG_TOTAL))
    job = alice.get("/api/uploads/latest").json()
    alice.post(
        f"/api/uploads/{job['id']}/password",
        json={"bank": "bhd", "password": PASSWORD},
        headers=WRITE,
    )
    for path in h.data.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert b"%PDF" not in data, path
            assert b"SUPERMERCADO" not in data or path.suffix in (".db", ".db-wal"), path
    new = [p for p in temp.iterdir() if p not in before and p.is_file()]
    assert not any(p.read_bytes().startswith(b"%PDF") for p in new if os.access(p, os.R_OK))


def test_the_same_file_twice_is_a_duplicate(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    upload(alice, ("card.pdf", POPULAR))
    again = upload(alice, ("copy.pdf", POPULAR))
    assert states(again) == {"copy.pdf": "duplicate"}
    assert again["squared"] == 1  # it already counts: the gate is open


def test_a_job_belongs_to_its_account_only(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    bob = h.sign_in(BOB, h.client())
    job = upload(alice, ("card.pdf", POPULAR))
    assert bob.get(f"/api/uploads/{job['id']}").status_code == 404
    assert bob.get("/api/uploads/latest").json() is None
    assert count(user_db(h, BOB), "statements") == 0
    assert bob.get("/api/onboarding").json()["open"] is False


def test_uploads_need_a_session_and_the_header(h: Hosted) -> None:
    anonymous = h.client()
    assert (
        anonymous.post("/api/uploads", json=payload(("a.pdf", POPULAR)), headers=WRITE).status_code
        == 401
    )
    alice = h.sign_in(ALICE)
    assert alice.post("/api/uploads", json=payload(("a.pdf", POPULAR))).status_code == 403


def test_upload_limits(tmp_path: Path) -> None:
    caps = UploadCaps(files_per_upload=2, file_bytes=len(POPULAR), uploads_per_hour=3)
    h = hosted(tmp_path, uploads=caps)
    alice = h.sign_in(ALICE)
    many = payload(*((f"{i}.pdf", POPULAR) for i in range(3)))
    assert alice.post("/api/uploads", json=many, headers=WRITE).status_code == 413
    big = payload(("big.pdf", POPULAR + b"0"))
    assert alice.post("/api/uploads", json=big, headers=WRITE).status_code == 413
    bad = {"files": [{"name": "a.pdf", "data": "not base64!"}]}
    assert alice.post("/api/uploads", json=bad, headers=WRITE).status_code == 422
    assert alice.post("/api/uploads", json={"files": []}, headers=WRITE).status_code == 422
    huge = b'{"files": []}'.ljust(caps.body_limit + 1)
    answer = alice.post(
        "/api/uploads", content=huge, headers={**WRITE, "content-type": "application/json"}
    )
    assert answer.status_code == 413
    ok = payload(("a.pdf", POPULAR))
    codes = [alice.post("/api/uploads", json=ok, headers=WRITE).status_code for _ in range(4)]
    assert codes == [202, 202, 202, 429]


def test_password_attempts_are_capped(tmp_path: Path) -> None:
    h = hosted(tmp_path, uploads=UploadCaps(passwords_per_window=2))
    alice = h.sign_in(ALICE)
    job = upload(alice, ("bhd.pdf", BHD_LOCKED))
    body = {"bank": "bhd", "password": "nope-nope"}
    codes = [
        alice.post(f"/api/uploads/{job['id']}/password", json=body, headers=WRITE).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


def test_the_share_target_holds_files_in_memory_until_claimed(h: Hosted) -> None:
    phone = h.client()
    answer = phone.post(
        "/share-target",
        files={"statements": ("card.pdf", POPULAR, "application/pdf")},
        headers={"Sec-Fetch-Site": "none"},
        follow_redirects=False,
    )
    assert answer.status_code == 303
    target = answer.headers["location"]
    assert target.startswith("/import#share=")
    token = target.split("=", 1)[1]
    assert not any(p.is_file() and b"%PDF" in p.read_bytes() for p in h.data.rglob("*"))
    alice = h.sign_in(ALICE, phone)
    claimed = alice.post("/api/uploads/shared", json={"token": token}, headers=WRITE)
    assert claimed.status_code == 202
    assert states(wait(alice, claimed.json()["id"])) == {"card.pdf": "squared"}
    again = alice.post("/api/uploads/shared", json={"token": token}, headers=WRITE)
    assert again.status_code == 404  # single use


def test_the_share_target_without_files_just_opens_the_upload_screen(h: Hosted) -> None:
    answer = h.client().post(
        "/share-target", data={"x": "1"}, headers={"Sec-Fetch-Site": "none"}, follow_redirects=False
    )
    assert answer.status_code == 303 and answer.headers["location"] == "/import"


def test_bank_requests_count_only_the_bank_name(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    assert (
        alice.post("/api/banks/requests", json={"bank": "scotiabank"}, headers=WRITE).status_code
        == 204
    )
    assert (
        alice.post("/api/banks/requests", json={"bank": "My Own Bank"}, headers=WRITE).status_code
        == 422
    )
    assert h.service.store.bank_requests() == {"scotiabank": 1}
    with sqlite3.connect(h.data / "accounts.db") as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(bank_requests)")}
    assert columns == {"bank", "requests"}
