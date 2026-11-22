"""Hosted uploads: fixes from the security review. Synthetic PDFs and addresses only.

Body limits on the share target, per-network share bytes, errors that never leak input, strict
names and passwords, one pool of worker slots, worker output caps and hardening, retention, the
change log for the first review, re-ingesting a half-stored upload, the last password try, URL
checks, the base64 length check, several shares per browser, the server-side gate, and proof that
nothing is spooled to disk.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from michelito.demo.app import check_return_url
from michelito.hosted import pdf_worker, uploads
from michelito.hosted.app import check_demo_url
from michelito.hosted.jobs import Jobs
from michelito.hosted.onboarding_routes import GATE_CODE, UploadCaps, clean_name
from michelito.hosted.routes import ERROR_HEADER
from michelito.hosted.shares import Shares
from tests import samples
from tests.hosted_helpers import WRITE, Hosted, hosted, past_the_gate
from tests.synthetic_pdf import build
from tests.test_hosted_uploads import (
    ALICE,
    BHD_LOCKED,
    BOB,
    PASSWORD,
    POPULAR,
    count,
    open_user_db,
    states,
    upload,
    user_db,
)

SHEET = {"Sec-Fetch-Site": "none"}
SURROGATE_PASSWORD = '{"bank": "bhd", "password": "pw-\\ud800-zz"}'


@pytest.fixture
def h(tmp_path: Path) -> Hosted:
    return hosted(tmp_path)


def _snapshot(*roots: Path) -> dict[Path, bytes]:
    found = {}
    for root in roots:
        for path in root.rglob("*"):
            if path.is_file():
                try:
                    found[path] = path.read_bytes()
                except OSError:
                    continue
    return found


# 1. The share target's body limit and the per-network stash.


def test_a_share_bigger_than_64_kb_is_accepted(h: Hosted) -> None:
    big = build(samples.POPULAR_PAGES * 30)
    assert len(big) > 64 * 1024
    answer = h.client().post(
        "/share-target",
        files={"statements": ("big.pdf", big, "application/pdf")},
        headers=SHEET,
        follow_redirects=False,
    )
    assert answer.status_code == 303
    assert answer.headers["location"].startswith("/import#share=")


def test_the_share_target_opens_no_database(h: Hosted, monkeypatch: pytest.MonkeyPatch) -> None:
    from michelito import db

    opened: list[object] = []
    real = db.connect

    def watch(*args: object, **kwargs: object) -> object:
        opened.append(args[0])
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(db, "connect", watch)
    answer = h.client().post(
        "/share-target",
        files={"statements": ("card.pdf", POPULAR, "application/pdf")},
        headers=SHEET,
        follow_redirects=False,
    )
    assert answer.status_code == 303 and opened == []


def test_one_network_cannot_fill_the_share_stash() -> None:
    shares = Shares(max_bytes=1000, per_source=300)
    assert shares.put((("a.pdf", b"x" * 200),), "net-1") is not None
    assert shares.put((("b.pdf", b"x" * 200),), "net-1") is None  # over its own share
    assert shares.put((("c.pdf", b"x" * 200),), "net-2") is not None


# 2 and 3. Errors never carry input; names and passwords are checked first.


def test_an_unexpected_error_ends_the_file_without_its_message(
    h: Hosted, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    def boom(data: bytes, password: str, limits: object = None) -> uploads.Examined:
        raise RuntimeError("leaked-fragment-xyz")

    monkeypatch.setattr(uploads, "examine", boom)
    alice = h.sign_in(ALICE)
    job = upload(alice, ("card.pdf", POPULAR))
    assert states(job) == {"card.pdf": "unreadable"}
    assert "RuntimeError" in caplog.text
    assert "leaked-fragment-xyz" not in caplog.text
    stored = h.app.state.uploads.jobs.get(h.service.store.account_by_email(ALICE).id, job["id"])
    assert all(f.data is None for f in stored.files)


def test_a_password_that_is_not_utf8_is_refused_before_anything(
    h: Hosted, caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    alice = h.sign_in(ALICE)
    job = upload(alice, ("bhd.pdf", BHD_LOCKED))
    answer = alice.post(
        f"/api/uploads/{job['id']}/password",
        content=SURROGATE_PASSWORD,
        headers={**WRITE, "content-type": "application/json"},
    )
    assert answer.status_code == 422
    out, err = capfd.readouterr()
    for text in (answer.text, caplog.text, out, err):
        assert "pw-" not in text and "ud800" not in text
    assert states(alice.get(f"/api/uploads/{job['id']}").json()) == {"bhd.pdf": "locked"}


def test_a_name_that_is_not_utf8_is_refused(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    body = '{"files": [{"name": "bad-\\udcff.pdf", "data": "JVBERg=="}]}'
    answer = alice.post(
        "/api/uploads", content=body, headers={**WRITE, "content-type": "application/json"}
    )
    assert answer.status_code == 422
    assert "udcff" not in answer.text


def test_names_are_cleaned() -> None:
    assert clean_name("folder/sub\\estado\x00‮.pdf") == "estado.pdf"  # spanish-data
    assert clean_name("  a \t b.pdf ") == "a b.pdf"
    long = clean_name("x" * 500 + ".pdf")
    assert long is not None and len(long) == 120 and long.endswith(".pdf")
    assert clean_name("\x07\x08") == "statement.pdf"
    assert clean_name("bad-\udcff.pdf") is None


# 4 and 5. One pool of worker slots; capped output.


def test_every_read_waits_for_the_same_worker_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def slow(data: bytes, password: str, limits: pdf_worker.Limits) -> bytes:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return b'{"pages": []}'

    monkeypatch.setattr(pdf_worker, "_run", slow)
    pdf_worker.configure(1)
    try:
        threads = [threading.Thread(target=pdf_worker.read, args=(b"%PDF", "")) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        pdf_worker.configure(2)
    assert peak == 1


def test_the_worker_caps_words_and_output() -> None:
    with pytest.raises(pdf_worker.TooComplex) as words:
        pdf_worker.read(POPULAR, "", pdf_worker.Limits(words_per_page=5))
    assert words.value.reason == "words"
    with pytest.raises(pdf_worker.TooComplex) as total:
        pdf_worker.read(POPULAR, "", pdf_worker.Limits(total_words=20))
    assert total.value.reason == "words"
    with pytest.raises(pdf_worker.TooComplex) as output:
        pdf_worker.read(POPULAR, "", pdf_worker.Limits(max_output=200))
    assert output.value.reason == "output"


def test_a_worker_that_hangs_fails_only_that_file() -> None:
    with pytest.raises(pdf_worker.TooComplex) as slow:
        pdf_worker.read(POPULAR, "", pdf_worker.Limits(wall_seconds=0.01))
    assert slow.value.reason == "time"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="RLIMIT_AS is Linux")
def test_a_worker_that_dies_fails_only_that_file() -> None:
    with pytest.raises(pdf_worker.TooComplex) as dead:  # it cannot even start in 32 MB
        pdf_worker.read(POPULAR, "", pdf_worker.Limits(memory_bytes=32 * 1024 * 1024))
    assert dead.value.reason in ("memory", "time")


# 14. Worker hardening.


def test_the_hardened_worker_can_neither_fork_nor_open_many_files() -> None:
    code = (
        "import os\n"
        "from michelito.hosted import pdf_worker as w\n"
        "w._harden(512 * 2**20, 5)\n"
        "try:\n"
        "    os.fork()\n"
        "except OSError:\n"
        "    print('no fork')\n"
        "files = []\n"
        "try:\n"
        "    for _ in range(20):\n"
        "        files.append(os.open('/dev/null', os.O_RDONLY))\n"
        "except OSError:\n"
        "    print('no files')\n"
        "try:\n"
        "    open('written.txt', 'w').write('x' * 10)\n"
        "except OSError:\n"
        "    print('no write')\n"
    )
    with tempfile.TemporaryDirectory() as folder:
        done = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, cwd=folder, check=False
        )
        assert "no fork" in done.stdout and "no files" in done.stdout, done.stderr
        assert "no write" in done.stdout or not Path(folder, "written.txt").stat().st_size


def test_the_worker_runs_in_an_empty_private_folder(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    upload(alice, ("card.pdf", POPULAR))
    folder = pdf_worker._empty_folder()
    assert list(folder.iterdir()) == []
    assert folder.stat().st_mode & 0o777 == 0o700


# 6. Retention.


def test_signing_out_drops_the_accounts_jobs_and_their_bytes(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    job = upload(alice, ("bhd.pdf", BHD_LOCKED))
    jobs = h.app.state.uploads.jobs
    account = h.service.store.account_by_email(ALICE).id
    kept = jobs.get(account, job["id"])
    assert kept.files[0].data is not None  # locked: waiting for its password
    assert alice.post("/api/auth/sign-out", headers=WRITE).status_code == 204
    assert jobs.get(account, job["id"]) is None
    assert all(f.data is None for f in kept.files)


def test_expired_jobs_are_pruned_and_lose_their_bytes() -> None:
    now = [1000.0]
    jobs = Jobs(ttl=10, clock=lambda: now[0])
    job = jobs.create(1, [("a.pdf", b"%PDF-1")])
    now[0] += 11
    jobs.prune()
    assert jobs.get(1, job.id) is None
    assert job.files[0].data is None and not jobs.alive(job)


def test_a_dropped_job_stops_before_its_next_file(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    state = h.app.state.uploads
    account = h.service.store.account_by_email(ALICE).id
    job = state.jobs.create(account, [("a.pdf", POPULAR), ("b.pdf", POPULAR)])
    state.jobs.forget(account)
    assert all(f.data is None for f in job.files)
    assert alice.get(f"/api/uploads/{job.id}").status_code == 404


# 7. The first review goes through the change log and can be undone.


def test_correct_and_later_are_logged_and_undoable(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    upload(alice, ("card.pdf", POPULAR))
    first = alice.get("/api/onboarding/merchants").json()[0]
    alice.put(
        "/api/onboarding/merchants/review", json={"merchant": first["merchant"]}, headers=WRITE
    )
    assert alice.put("/api/onboarding/flags/first_review_closed", headers=WRITE).status_code == 204
    entries = alice.get("/api/log").json()["items"]
    kinds = [e["kind"] for e in entries]
    assert "reviewed" in kinds and "onboarding" in kinds
    for entry in entries:
        undone = alice.post(f"/api/log/{entry['id']}/undo", headers=WRITE)
        assert undone.status_code == 200, undone.text
    merchants = alice.get("/api/onboarding/merchants").json()
    assert next(m for m in merchants if m["merchant"] == first["merchant"])["status"] == "pending"
    assert alice.get("/api/onboarding").json()["first_review"] is True


# 8. A half-stored upload is a new attempt.


def test_an_upload_row_without_statements_is_processed_again(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    from michelito import importer

    path = user_db(h, ALICE)
    conn = open_user_db(path)
    try:
        importer.register_upload(conn, "card.pdf", POPULAR, __import__("datetime").datetime.now())
    finally:
        conn.close()
    assert count(path, "statements") == 0
    job = upload(alice, ("card.pdf", POPULAR))
    assert states(job) == {"card.pdf": "squared"}
    assert count(path, "statements") > 0 and count(path, "documents") == 1


def test_a_failed_ingestion_leaves_no_orphan_row(
    h: Hosted, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = h.sign_in(ALICE)
    from michelito import ingest

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(ingest, "process_documents", fail)
    job = upload(alice, ("card.pdf", POPULAR))
    assert states(job) == {"card.pdf": "unreadable"}
    assert count(user_db(h, ALICE), "documents") == 0


# 9. The last password try.


def test_the_last_try_says_how_many_it_opened_and_how_many_are_left(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    job = upload(alice, ("one.pdf", BHD_LOCKED), ("two.pdf", build(samples.BHD_TC_PAGES, "other")))
    tried = alice.post(
        f"/api/uploads/{job['id']}/password",
        json={"bank": "bhd", "password": PASSWORD},
        headers=WRITE,
    ).json()
    assert tried["last_try"] == {"bank": "bhd", "opened": 1, "left": 1}


# 10. URL checks.


def test_the_demo_and_return_urls_are_https_or_loopback() -> None:
    for good in ("https://demo.example", "http://127.0.0.1:8601", "http://localhost:1"):
        check_demo_url(good)
        check_return_url(good)
    check_return_url("")
    for bad in ("http://demo.example", "javascript:alert(1)", "ftp://x", "https://"):
        with pytest.raises(ValueError):
            check_demo_url(bad)
        with pytest.raises(ValueError):
            check_return_url(bad)


# 11. Base64 length before decoding.


def test_an_oversized_base64_is_refused_before_decoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = hosted(tmp_path, uploads=UploadCaps(file_bytes=300))
    alice = h.sign_in(ALICE)
    import base64

    called: list[int] = []
    real = base64.b64decode

    def spy(data: str, validate: bool = False) -> bytes:
        called.append(len(data))
        return real(data, validate=validate)

    monkeypatch.setattr(base64, "b64decode", spy)
    body = {"files": [{"name": "a.pdf", "data": "A" * 404}]}
    assert alice.post("/api/uploads", json=body, headers=WRITE).status_code == 413
    assert called == []


# 12. Several shares of one browser.


def test_several_pending_shares_of_one_browser_stay_claimable(h: Hosted) -> None:
    phone = h.client()
    tokens = []
    for name in ("one.pdf", "two.pdf"):
        answer = phone.post(
            "/share-target",
            files={"statements": (name, POPULAR, "application/pdf")},
            headers=SHEET,
            follow_redirects=False,
        )
        tokens.append(answer.headers["location"].split("=", 1)[1])
    alice = h.sign_in(ALICE, phone)
    for token, name in zip(tokens, ("one.pdf", "two.pdf"), strict=True):
        peek = alice.post("/api/uploads/shared/peek", json={"token": token}, headers=WRITE)
        assert peek.status_code == 200 and peek.json()[0]["name"] == name


# 13. The gate on the server.


def test_the_gate_is_enforced_by_the_server(h: Hosted) -> None:
    alice = h.sign_in(ALICE, gate=True)
    for path in ("/api/summary", "/api/transactions?month=2026-01", "/api/accounts", "/api/log"):
        answer = alice.get(path)
        assert answer.status_code == 403, path
        assert answer.headers[ERROR_HEADER] == GATE_CODE
    refused = alice.post("/api/categories", json={"name": "X", "kind": "expense"}, headers=WRITE)
    assert refused.status_code == 403
    for path in (
        "/api/mode",
        "/api/health",
        "/api/auth/me",
        "/api/auth/devices",
        "/api/onboarding",
    ):
        assert alice.get(path).status_code == 200, path
    upload(alice, ("card.pdf", POPULAR))
    assert alice.get("/api/accounts").status_code == 200


# 15. No spooling, and passwords for another account's job.


def test_an_upload_spools_nothing_to_disk(h: Hosted, monkeypatch: pytest.MonkeyPatch) -> None:
    alice = h.sign_in(ALICE)
    pdf_worker._empty_folder()  # created once, before the patches

    def no_temp_files(*args: object, **kwargs: object) -> None:
        raise AssertionError("a temporary file was opened during the upload")

    for name in ("SpooledTemporaryFile", "TemporaryFile", "NamedTemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, no_temp_files)
    temp = Path(tempfile.gettempdir())
    before = _snapshot(temp, h.data)
    job = upload(alice, ("bhd.pdf", BHD_LOCKED), ("card.pdf", POPULAR))
    alice.post(
        f"/api/uploads/{job['id']}/password",
        json={"bank": "bhd", "password": PASSWORD},
        headers=WRITE,
    )
    after = _snapshot(temp, h.data)
    for path, data in after.items():
        if before.get(path) == data:
            continue
        assert b"%PDF" not in data, path
        assert PASSWORD.encode() not in data, path
    assert list(pdf_worker._empty_folder().iterdir()) == []


def test_uploads_are_written_into_the_encrypted_database(h: Hosted) -> None:
    """The background job writes through the request's keyed workspace: the statements land
    in the account's SQLCipher file, which a plain SQLite cannot read."""
    import sqlite3

    alice = h.sign_in(ALICE, gate=True)
    job = upload(alice, ("bhd.pdf", BHD_LOCKED), ("card.pdf", POPULAR))
    alice.post(
        f"/api/uploads/{job['id']}/password",
        json={"bank": "bhd", "password": PASSWORD},
        headers=WRITE,
    )
    path = user_db(h, ALICE)
    assert count(path, "statements") >= 2  # with its data key
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(path).execute("SELECT COUNT(*) FROM statements").fetchone()
    raw = path.read_bytes()
    assert b"SQLite format 3" not in raw[:16]
    assert b"SUPERMERCADO" not in raw


def test_another_account_cannot_send_a_password_to_my_job(h: Hosted) -> None:
    alice = h.sign_in(ALICE)
    bob = h.sign_in(BOB, h.client())
    job = upload(alice, ("bhd.pdf", BHD_LOCKED))
    answer = bob.post(
        f"/api/uploads/{job['id']}/password",
        json={"bank": "bhd", "password": PASSWORD},
        headers=WRITE,
    )
    assert answer.status_code == 404
    assert states(alice.get(f"/api/uploads/{job['id']}").json()) == {"bhd.pdf": "locked"}
    assert count(user_db(h, BOB), "statements") == 0


def test_tests_can_skip_the_gate(h: Hosted) -> None:
    alice = h.sign_in(ALICE, gate=True)
    past_the_gate(h, ALICE)
    assert alice.get("/api/accounts").status_code == 200
