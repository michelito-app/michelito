"""The operations state and the daily check: an email to the owner only when something failed
(backup, statements that could not be read, sign-in emails not sent), with no personal or
financial data. Synthetic data and throwaway keys only."""

from __future__ import annotations

import hashlib
import logging
from contextlib import closing
from pathlib import Path

from michelito import db
from michelito.hosted import auth, keys, ops
from michelito.hosted.keys import load_master
from michelito.hosted.mailer import MemoryMailer
from tests.hosted_helpers import Clock, hosted, master_file

DAY = 86400


def test_nothing_failed_sends_nothing(tmp_path: Path) -> None:
    clock = Clock()
    status = ops.Status(tmp_path, clock)
    status.backup_succeeded("2026-11-19")
    assert ops.check(tmp_path, None, None, clock) == []
    mailer = MemoryMailer()
    assert not ops.notify(mailer, "owner@example.com", [])
    assert mailer.sent == []


def test_a_failed_or_missing_backup_is_a_problem(tmp_path: Path) -> None:
    clock = Clock()
    status = ops.Status(tmp_path, clock)
    assert [p.kind for p in ops.check(tmp_path, None, None, clock)] == ["backup"]  # never ran
    status.backup_succeeded("2026-11-19")
    clock.advance(60)
    status.backup_failed("PUT answered 500 InternalError")
    found = ops.check(tmp_path, None, None, clock)
    assert [p.kind for p in found] == ["backup"] and "500" in found[0].text
    clock.advance(60)
    status.backup_succeeded("2026-11-20")
    assert ops.check(tmp_path, None, None, clock) == []
    clock.advance(2 * DAY)
    (old,) = ops.check(tmp_path, None, None, clock)
    assert old.kind == "backup" and "48" in old.text
    assert (tmp_path / "ops" / "status.json").stat().st_mode & 0o777 == 0o600


def test_sign_in_emails_that_failed_are_counted_from_the_log(tmp_path: Path) -> None:
    clock = Clock()
    ops.Status(tmp_path, clock).backup_succeeded("x")
    handler = ops.count_mail_failures(tmp_path)
    handler.status.clock = clock
    try:
        logger = logging.getLogger(ops.MAIL_LOGGER)
        logger.error("a sign-in email could not be sent: %s", "HTTP 500")
        logger.error("a sign-in email could not be sent: %s", "HTTP 500")
        logger.warning("not a failure")
    finally:
        logging.getLogger(ops.MAIL_LOGGER).removeHandler(handler)
    (problem,) = ops.check(tmp_path, None, None, clock)
    assert problem.kind == "mail" and "2" in problem.text
    clock.advance(3 * DAY)
    ops.Status(tmp_path, clock).backup_succeeded("y")
    assert ops.check(tmp_path, None, None, clock) == []  # older than the window


def test_statements_that_failed_today_are_reported_by_fingerprint(tmp_path: Path) -> None:
    env = hosted(tmp_path)
    env.sign_in("alice@example.com")
    master = load_master(master_file(tmp_path), env.data)
    store = env.service.store
    account = store.account_by_email("alice@example.com")
    stored = store.data_key(account.id)
    key = keys.unwrap(master, stored.wrapped, account.id, account.folder)
    path = env.data / auth.USERS / account.folder / auth.DATABASE
    with closing(db.connect(path, key)) as conn, conn:
        conn.execute(
            "INSERT INTO gmail_messages (message_id, source, sender, subject, received_at, "
            "attachments_saved, fetched_at) VALUES ('m1', 'upload', 'f', 's', '2026-11-19', 1, "
            "'2026-11-19')"
        )
        for n, (status, processed) in enumerate(
            [
                ("invalid", "2099-01-01T00:00:00"),
                ("error", "2099-01-01T00:00:00"),
                ("invalid", "2000-01-01T00:00:00"),
                ("parsed", "2099-01-01T00:00:00"),
            ]
        ):
            conn.execute(
                "INSERT INTO documents (message_id, source, filename, path, sha256, size, "
                "received_at, status, parser, detail, processed_at) "
                "VALUES ('m1', 'upload', ?, 'p', 'h', 1, '2026-11-19', ?, 'bhd_savings', "
                "'difference of 1234.56 in ALICE-SYNTHETIC', ?)",
                (f"secret-name-{n}.pdf", status, processed),
            )
    clock = Clock(now=4_070_908_800.0 + 3600)  # 2099-01-01T01:00Z
    ops.Status(env.data, clock).backup_succeeded("x")
    (problem,) = ops.check(env.data, store, master, clock)
    assert problem.kind == "parser" and "2 " in problem.text and "bhd_savings:" in problem.text
    mailer = MemoryMailer()
    assert ops.notify(mailer, "owner@example.com", [problem])
    (email,) = mailer.sent
    assert email.to == "owner@example.com"
    for leak in ("1234.56", "ALICE", "secret-name", "alice@example.com"):
        assert leak not in email.text and leak not in email.subject


def test_fingerprints_are_keyed_and_group_details_by_their_shape(tmp_path: Path) -> None:
    master = load_master(master_file(tmp_path))
    other = load_master(master_file(tmp_path, "other.key"))
    one = ops.fingerprint(master, "bhd_savings", "invalid", "difference of 1234.56 in ALICE")
    same = ops.fingerprint(master, "bhd_savings", "invalid", "difference of 99.01 in BOB")
    assert one == same  # amounts and names do not make another kind
    assert ops.template("difference of 1234.56 in ALICE") == "a a 0.0 a a"
    assert one != ops.fingerprint(master, "bhd_savings", "invalid", "missing total: 12")
    assert one != ops.fingerprint(other, "bhd_savings", "invalid", "difference of 1 in X")
    plain = hashlib.sha256(b"bhd_savings\0invalid\0a a 0.0 a a").hexdigest()[:8]
    assert one != plain  # without the master key it cannot be recomputed from a guess
