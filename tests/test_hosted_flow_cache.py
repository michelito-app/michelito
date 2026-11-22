"""Hosted mode: the loaded flow kept between requests (`web.flow_cache`) works on an encrypted
database and never outlives a person's sessions. Synthetic addresses only."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from michelito.analysis import spending
from michelito.hosted.app import Sweeper
from michelito.web.flow_cache import IDLE_SECONDS, FlowCache
from tests.hosted_helpers import WRITE, Hosted, hosted

ALICE = "alice@example.com"
BOB = "bob@example.com"


def _settle(h: Hosted) -> None:
    """Date every account database an hour ago: old enough to be told apart from a later write."""
    when = time.time() - 3600
    for path in (h.data / "users").rglob("*"):
        if path.is_file():
            os.utime(path, (when, when))


@pytest.fixture
def loads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    original = spending.load_all

    def counting(*args: object, **kwargs: object) -> object:
        calls.append(1)
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(spending, "load_all", counting)
    return calls


def test_an_encrypted_database_is_loaded_once_while_unchanged(
    tmp_path: Path, loads: list[int]
) -> None:
    h = hosted(tmp_path)
    client = h.sign_in(ALICE)
    assert client.get("/api/months").status_code == 200  # the account's database exists now
    _settle(h)
    loads.clear()

    for _ in range(3):
        assert client.get("/api/months").status_code == 200

    assert len(loads) == 1
    assert len(h.app.state.flows) == 1


def test_each_account_gets_its_own_flow(tmp_path: Path, loads: list[int]) -> None:
    h = hosted(tmp_path)
    alice = h.sign_in(ALICE)
    bob = h.sign_in(BOB)
    alice.get("/api/months")
    bob.get("/api/months")
    _settle(h)
    loads.clear()

    for client in (alice, bob, alice, bob):
        assert client.get("/api/months").status_code == 200

    assert len(loads) == 2
    assert len(h.app.state.flows) == 2


def test_signing_out_drops_the_loaded_flows(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.sign_in(ALICE)
    client.get("/api/months")
    _settle(h)
    client.get("/api/months")
    assert len(h.app.state.flows) == 1

    assert client.post("/api/auth/sign-out", headers=WRITE).status_code == 204

    assert len(h.app.state.flows) == 0


def test_the_sweeper_drops_idle_flows_without_a_request(tmp_path: Path) -> None:
    database = tmp_path / "michelito.db"
    database.write_bytes(b"data")
    os.utime(database, (time.time() - 3600,) * 2)
    seconds = [0.0]
    flows = FlowCache(clock=lambda: seconds[0])
    flows.get(database, "inputs", lambda: ("flow",))
    swept = threading.Event()
    stores = SimpleNamespace(prune=lambda: None)
    gate = SimpleNamespace(jobs=stores, shares=SimpleNamespace(prune=swept.set))
    seconds[0] = IDLE_SECONDS + 1

    sweeper = Sweeper(gate, flows, every=0.01)  # type: ignore[arg-type]
    try:
        assert swept.wait(timeout=5)
        deadline = time.monotonic() + 5
        while len(flows) and time.monotonic() < deadline:
            swept.clear()
            swept.wait(timeout=1)
    finally:
        sweeper.stop()

    assert len(flows) == 0
