"""The browser extension's link (`hosted.extension`): one-time codes and scoped tokens in the
accounts database. Only synthetic addresses."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from michelito.hosted import extension
from michelito.hosted.store import Store
from tests.hosted_helpers import Clock

SECRET = b"s" * 32
FOLDER_A = "a" * 32
FOLDER_B = "b" * 32


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "accounts.db")


@pytest.fixture
def linker(store: Store, clock: Clock) -> extension.Linker:
    return extension.Linker(store, SECRET, clock)


def _account(store: Store, email: str, folder: str) -> int:
    return store.create_account(email, folder, 1, None).id


def test_a_code_reads_easily_and_normalizes_back() -> None:
    code = extension.new_code()

    assert extension.CODE_PATTERN.fullmatch(code)
    assert extension.normalize_code(f"  {code.lower().replace('-', ' ')} ") == code.replace("-", "")
    assert extension.normalize_code("not a code") is None
    assert extension.normalize_code("A" * 200) is None
    assert {extension.new_code() for _ in range(50)}.__len__() == 50


def test_a_code_is_exchanged_once_for_a_token(store: Store, linker: extension.Linker) -> None:
    alice = _account(store, "alice@example.com", FOLDER_A)
    code, _ = linker.issue(alice)

    token = linker.exchange(code)

    assert token is not None and token.startswith(extension.TOKEN_PREFIX)
    assert linker.exchange(code) is None  # single use
    account = linker.account_of(token)
    assert account is not None and account.id == alice


def test_only_hashes_are_stored(store: Store, linker: extension.Linker) -> None:
    alice = _account(store, "alice@example.com", FOLDER_A)
    code, _ = linker.issue(alice)
    token = linker.exchange(code)
    assert token is not None

    raw = store.path.read_bytes()
    with store.connect() as conn:
        (stored,) = conn.execute("SELECT token_hash FROM extension_tokens").fetchone()

    assert stored == hashlib.sha256(token.encode()).hexdigest()
    assert token.encode() not in raw and code.replace("-", "").encode() not in raw


def test_a_code_expires(store: Store, linker: extension.Linker, clock: Clock) -> None:
    alice = _account(store, "alice@example.com", FOLDER_A)
    code, expires_at = linker.issue(alice)
    assert expires_at == int(clock()) + extension.CODE_SECONDS

    clock.advance(extension.CODE_SECONDS + 1)

    assert linker.exchange(code) is None


def test_a_new_code_replaces_the_previous_one(store: Store, linker: extension.Linker) -> None:
    alice = _account(store, "alice@example.com", FOLDER_A)
    old, _ = linker.issue(alice)
    new, _ = linker.issue(alice)

    assert linker.exchange(old) is None
    assert linker.exchange(new) is not None


def test_linking_again_replaces_the_old_token(store: Store, linker: extension.Linker) -> None:
    alice = _account(store, "alice@example.com", FOLDER_A)
    first = linker.exchange(linker.issue(alice)[0])
    second = linker.exchange(linker.issue(alice)[0])
    assert first and second

    assert linker.account_of(first) is None
    found = linker.account_of(second)
    assert found is not None and found.id == alice


def test_revoking_stops_the_token_and_the_pending_code(
    store: Store, linker: extension.Linker
) -> None:
    alice = _account(store, "alice@example.com", FOLDER_A)
    token = linker.exchange(linker.issue(alice)[0])
    pending, _ = linker.issue(alice)
    assert token

    assert linker.revoke(alice) is True

    assert linker.account_of(token) is None
    assert linker.exchange(pending) is None
    assert linker.status(alice) is None
    assert linker.revoke(alice) is False


def test_each_token_opens_only_its_own_account(store: Store, linker: extension.Linker) -> None:
    alice = _account(store, "alice@example.com", FOLDER_A)
    bruno = _account(store, "bruno@example.com", FOLDER_B)
    alice_token = linker.exchange(linker.issue(alice)[0])
    bruno_token = linker.exchange(linker.issue(bruno)[0])
    assert alice_token and bruno_token

    found_a, found_b = linker.account_of(alice_token), linker.account_of(bruno_token)

    assert found_a is not None and found_a.id == alice
    assert found_b is not None and found_b.id == bruno


def test_a_disabled_account_token_does_not_work(store: Store, linker: extension.Linker) -> None:
    alice = _account(store, "alice@example.com", FOLDER_A)
    token = linker.exchange(linker.issue(alice)[0])
    pending, _ = linker.issue(alice)
    assert token
    with store.connect() as conn, conn:
        conn.execute("UPDATE accounts SET status = 'disabled' WHERE id = ?", (alice,))

    assert linker.account_of(token) is None
    assert linker.exchange(pending) is None


def test_status_says_when_it_was_linked_and_last_used(
    store: Store, linker: extension.Linker, clock: Clock
) -> None:
    alice = _account(store, "alice@example.com", FOLDER_A)
    assert linker.status(alice) is None
    token = linker.exchange(linker.issue(alice)[0])
    assert token
    linked_at = int(clock())
    found = linker.status(alice)
    assert found == extension.Link(linked_at=linked_at, last_used_at=None)

    clock.advance(60)
    linker.account_of(token)

    assert linker.status(alice) == extension.Link(linked_at=linked_at, last_used_at=linked_at + 60)


@pytest.mark.parametrize("token", ["", "x", "mchx_" + "a" * 500, "wrong"])
def test_malformed_tokens_find_nothing(linker: extension.Linker, token: str) -> None:
    assert linker.account_of(token) is None


def test_deleting_the_account_deletes_its_link(store: Store, linker: extension.Linker) -> None:
    alice = _account(store, "alice@example.com", FOLDER_A)
    token = linker.exchange(linker.issue(alice)[0])
    assert token

    store.delete_account(alice, 2)

    assert linker.account_of(token) is None
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM extension_tokens").fetchone()[0] == 0


def test_an_unused_token_stops_working(
    store: Store, linker: extension.Linker, clock: Clock
) -> None:
    alice = _account(store, "alice@example.com", FOLDER_A)
    token = linker.exchange(linker.issue(alice)[0])
    assert token
    clock.advance(extension.IDLE_SECONDS - 10)
    assert linker.account_of(token) is not None  # a use moves the deadline

    clock.advance(extension.IDLE_SECONDS - 10)
    assert linker.account_of(token) is not None
    clock.advance(extension.IDLE_SECONDS + 1)

    assert linker.account_of(token) is None


def test_signing_out_everywhere_cuts_the_extension(store: Store, linker: extension.Linker) -> None:
    alice = _account(store, "alice@example.com", FOLDER_A)
    token = linker.exchange(linker.issue(alice)[0])
    pending, _ = linker.issue(alice)
    assert token

    store.delete_sessions_of(alice)

    assert linker.account_of(token) is None
    assert linker.exchange(pending) is None
