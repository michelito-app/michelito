"""Seeding a hosted test account (`hosted.seeding`): only for emails marked as test accounts, the
account's database is replaced in place with made-up data at an onboarding stage, keeping the
account, its key and its connections. Every address and statement is made up."""

from __future__ import annotations

from contextlib import closing
from datetime import date
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis.spending import load_all
from michelito.hosted import onboarding, seeding
from tests.hosted_helpers import Hosted, hosted

TESTER = "tester@example.com"
TODAY = date(2026, 11, 20)


@pytest.fixture
def h(tmp_path: Path) -> Hosted:
    return hosted(tmp_path)


def load_flow(conn):  # noqa: ANN001, ANN201
    return load_all(conn, (), None, TODAY)


def _workspace(h: Hosted, email: str):  # noqa: ANN202
    h.sign_in(email)
    account = h.service.store.account_by_email(email)
    return account, h.service.workspace_of(account)


def test_an_email_is_a_test_account_only_once_marked(h: Hosted) -> None:
    store = h.service.store

    assert not store.is_test_email(TESTER)
    store.mark_test_email(TESTER, 100)
    store.mark_test_email(TESTER, 200)  # idempotent

    assert store.is_test_email(TESTER)
    assert store.is_test_email(TESTER.upper())
    assert not store.is_test_email("someone@example.com")


def test_an_account_that_is_not_marked_is_never_seeded(h: Hosted) -> None:
    _, workspace = _workspace(h, TESTER)
    with closing(db.connect(workspace.database, workspace.key)) as conn:
        before = conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0]

    with pytest.raises(seeding.SeedError, match="test account"):
        seeding.seed(h.service.store, TESTER, workspace, "first-statement", TODAY)

    with closing(db.connect(workspace.database, workspace.key)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == before


def test_an_unknown_stage_is_refused(h: Hosted) -> None:
    h.service.store.mark_test_email(TESTER, 1)
    _, workspace = _workspace(h, TESTER)

    with pytest.raises(seeding.SeedError, match="stage"):
        seeding.seed(h.service.store, TESTER, workspace, "everything", TODAY)


def test_first_statement_leaves_the_account_right_after_its_first_upload(h: Hosted) -> None:
    h.service.store.mark_test_email(TESTER, 1)
    account, workspace = _workspace(h, TESTER)

    seeding.seed(h.service.store, TESTER, workspace, "first-statement", TODAY)

    with closing(db.connect(workspace.database, workspace.key)) as conn:
        assert conn.execute("SELECT COUNT(DISTINCT document_id) FROM statements").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM merchant_categories").fetchone()[0] == 0
        state = onboarding.build_state(conn, load_flow(conn))
        merchants = onboarding.top_merchants(conn, load_flow(conn))
        statuses = {onboarding.merchant_status(conn, m) for m in merchants}
    assert state.open and state.first_review
    assert merchants and statuses == {"pending"}
    assert h.service.store.account_by_email(TESTER).id == account.id


def test_seeding_again_undoes_what_the_walkthrough_changed(h: Hosted) -> None:
    h.service.store.mark_test_email(TESTER, 1)
    _, workspace = _workspace(h, TESTER)
    seeding.seed(h.service.store, TESTER, workspace, "first-statement", TODAY)
    with closing(db.connect(workspace.database, workspace.key)) as conn:
        merchant = onboarding.top_merchants(conn, load_flow(conn))[0]
        with conn:
            onboarding.mark_reviewed(conn, merchant.fingerprints)
            onboarding.set_flag(conn, "first_review_closed")
        held = db.connect(workspace.database, workspace.key)  # the server may hold one open

    try:
        seeding.seed(h.service.store, TESTER, workspace, "first-statement", TODAY)
        assert held.execute("SELECT COUNT(*) FROM reviewed_fingerprints").fetchone()[0] == 0
    finally:
        held.close()
    with closing(db.connect(workspace.database, workspace.key)) as conn:
        assert onboarding.flags(conn) == frozenset()
        assert conn.execute("SELECT COUNT(DISTINCT document_id) FROM statements").fetchone()[0] == 1
    assert not list(workspace.database.parent.glob("*.seeding*"))


def test_a_database_with_data_of_its_own_is_never_replaced(h: Hosted, tmp_path: Path) -> None:
    from michelito.demo import generate

    h.service.store.mark_test_email(TESTER, 1)
    _, workspace = _workspace(h, TESTER)
    with closing(db.connect(workspace.database, workspace.key)) as conn:
        card = [s for s in generate.statements(TODAY) if s.is_liability][0]
        generate.store(conn, card, "upload-000", TODAY)

    with pytest.raises(seeding.SeedError, match="not from the seeder"):
        seeding.seed(h.service.store, TESTER, workspace, "first-statement", TODAY)

    with closing(db.connect(workspace.database, workspace.key)) as conn:
        names = [r[0] for r in conn.execute("SELECT filename FROM documents")]
    assert names == ["upload-000.statement"]


def test_deleting_the_account_drops_its_test_mark(h: Hosted) -> None:
    store = h.service.store
    store.mark_test_email(TESTER, 1)
    account, _ = _workspace(h, TESTER)

    store.delete_account(account.id, 2)

    assert not store.is_test_email(TESTER)  # a later account with that email is a real one
