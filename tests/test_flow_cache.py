"""The loaded flow kept between requests (`web.flow_cache`): reused only while the database
file is provably unchanged."""

import os
import threading
import time
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import config, db
from michelito.analysis import categories, spending
from michelito.web.app import create_app
from michelito.web.flow_cache import IDLE_SECONDS, RACY_SECONDS, FlowCache
from tests.test_spending import seed

WRITE = {"X-Michelito": "1"}
NOW = 1_800_000_000.0
LONG_AGO = NOW - 3600


class Clock:
    """A wall clock and a monotonic one the test moves by hand."""

    def __init__(self) -> None:
        self.seconds = 0.0

    def wall(self) -> float:
        return NOW + self.seconds

    def monotonic(self) -> float:
        return self.seconds


class Loader:
    """Counts the loads; each one returns a new value."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> tuple[int, ...]:
        self.calls += 1
        return (self.calls,)


def _aged(path: Path, content: bytes = b"data", when: float = LONG_AGO) -> Path:
    path.write_bytes(content)
    os.utime(path, (when, when))
    return path


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def cache(clock: Clock) -> FlowCache:
    return FlowCache(wall=clock.wall, clock=clock.monotonic)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return _aged(tmp_path / "michelito.db")


def test_reuses_the_value_while_the_file_is_unchanged(cache: FlowCache, database: Path) -> None:
    load = Loader()

    first = cache.get(database, "inputs", load)
    second = cache.get(database, "inputs", load)

    assert first is second
    assert load.calls == 1


def test_loads_again_when_the_file_changed(cache: FlowCache, database: Path) -> None:
    load = Loader()
    cache.get(database, "inputs", load)

    _aged(database, b"other", LONG_AGO + 60)

    assert cache.get(database, "inputs", load) == (2,)


def test_loads_again_when_only_the_modification_time_changed(
    cache: FlowCache, database: Path
) -> None:
    load = Loader()
    cache.get(database, "inputs", load)

    _aged(database, b"data", LONG_AGO + 60)  # the same size

    assert cache.get(database, "inputs", load) == (2,)


def test_a_file_written_just_now_is_never_kept(
    cache: FlowCache, clock: Clock, tmp_path: Path
) -> None:
    # A second write in the same clock tick would leave the same size and time: not provable.
    recent = _aged(tmp_path / "recent.db", when=NOW - RACY_SECONDS / 2)
    load = Loader()

    cache.get(recent, "inputs", load)
    cache.get(recent, "inputs", load)
    assert load.calls == 2

    clock.seconds = RACY_SECONDS  # the write is old enough now
    cache.get(recent, "inputs", load)
    cache.get(recent, "inputs", load)
    assert load.calls == 3


def test_a_file_dated_in_the_future_is_never_kept(cache: FlowCache, tmp_path: Path) -> None:
    ahead = _aged(tmp_path / "ahead.db", when=NOW + 3600)
    load = Loader()

    cache.get(ahead, "inputs", load)
    cache.get(ahead, "inputs", load)

    assert load.calls == 2


def test_a_write_in_progress_is_never_kept(cache: FlowCache, database: Path) -> None:
    _aged(database.with_name(database.name + "-journal"))
    load = Loader()

    cache.get(database, "inputs", load)
    cache.get(database, "inputs", load)

    assert load.calls == 2


def test_the_write_ahead_log_counts_as_the_file(cache: FlowCache, database: Path) -> None:
    wal = _aged(database.with_name(database.name + "-wal"))
    load = Loader()
    cache.get(database, "inputs", load)

    _aged(wal, b"more pages", LONG_AGO + 60)

    assert cache.get(database, "inputs", load) == (2,)


def test_other_inputs_load_again(cache: FlowCache, database: Path) -> None:
    load = Loader()
    cache.get(database, ("holders", date(2026, 1, 1)), load)

    assert cache.get(database, ("holders", date(2026, 1, 2)), load) == (2,)


def test_a_missing_file_is_loaded_every_time(cache: FlowCache, tmp_path: Path) -> None:
    load = Loader()

    cache.get(tmp_path / "gone.db", "inputs", load)
    cache.get(tmp_path / "gone.db", "inputs", load)

    assert load.calls == 2


def test_an_idle_value_is_dropped(cache: FlowCache, clock: Clock, database: Path) -> None:
    load = Loader()
    cache.get(database, "inputs", load)

    clock.seconds = IDLE_SECONDS + 1

    assert cache.get(database, "inputs", load) == (2,)
    assert len(cache) == 1


def test_a_value_in_use_is_kept_past_the_idle_time(
    cache: FlowCache, clock: Clock, database: Path
) -> None:
    load = Loader()
    cache.get(database, "inputs", load)

    for step in range(1, 5):
        clock.seconds = step * IDLE_SECONDS * 0.9
        cache.get(database, "inputs", load)

    assert load.calls == 1


def test_only_the_most_recently_used_databases_are_kept(clock: Clock, tmp_path: Path) -> None:
    cache = FlowCache(max_entries=2, wall=clock.wall, clock=clock.monotonic)
    first, second, third = (_aged(tmp_path / f"{name}.db") for name in ("a", "b", "c"))
    load = Loader()
    cache.get(first, "inputs", load)
    clock.seconds = 1
    cache.get(second, "inputs", load)
    clock.seconds = 2
    cache.get(first, "inputs", load)  # used again: the second is now the oldest
    clock.seconds = 3

    cache.get(third, "inputs", load)

    assert len(cache) == 2
    cache.get(first, "inputs", load)
    assert load.calls == 3  # the first was still there
    cache.get(second, "inputs", load)
    assert load.calls == 4  # the second was dropped


def test_a_failed_load_keeps_nothing(cache: FlowCache, database: Path) -> None:
    def broken() -> tuple[int, ...]:
        raise RuntimeError("no data")

    with pytest.raises(RuntimeError):
        cache.get(database, "inputs", broken)

    assert len(cache) == 0
    assert cache.get(database, "inputs", Loader()) == (1,)


def test_a_load_that_was_running_when_everything_was_dropped_is_not_kept(
    cache: FlowCache, database: Path
) -> None:
    # Someone signed out while their request was still loading: nothing of theirs stays.
    def interrupted() -> tuple[int, ...]:
        cache.clear()
        return (1,)

    assert cache.get(database, "inputs", interrupted) == (1,)

    assert len(cache) == 0


def test_requests_for_one_database_wait_for_a_single_load(cache: FlowCache, database: Path) -> None:
    started = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    def slow() -> tuple[int, ...]:
        calls.append(1)
        started.set()
        assert release.wait(timeout=5)
        return (len(calls),)

    results: list[tuple[int, ...]] = []
    threads = [
        threading.Thread(target=lambda: results.append(cache.get(database, "inputs", slow)))
        for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    assert started.wait(timeout=5)
    release.set()
    for thread in threads:
        thread.join(timeout=5)

    assert results == [(1,), (1,), (1,)]
    assert calls == [1]


def test_a_path_that_cannot_be_inspected_is_loaded_every_time(
    cache: FlowCache, database: Path
) -> None:
    inside_a_file = database / "michelito.db"  # not a missing file: another OS error
    load = Loader()

    cache.get(inside_a_file, "inputs", load)
    cache.get(inside_a_file, "inputs", load)

    assert load.calls == 2


def test_dropping_everything_empties_it(cache: FlowCache, database: Path) -> None:
    load = Loader()
    cache.get(database, "inputs", load)

    cache.clear()

    assert len(cache) == 0
    assert cache.get(database, "inputs", load) == (2,)


# Through the API: the board's routes share one load while nothing is written. The app goes by
# the real clock, so the file is dated an hour (or a little less) before now.


def _settle(path: Path, minutes_ago: int = 60) -> None:
    when = time.time() - minutes_ago * 60
    os.utime(path, (when, when))


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
    _settle(path)
    return path


@pytest.fixture
def loads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """One item per call of `spending.load_all`."""
    calls: list[int] = []
    original = spending.load_all

    def counting(*args: object, **kwargs: object) -> object:
        calls.append(1)
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(spending, "load_all", counting)
    return calls


@pytest.fixture
def client(db_path: Path) -> TestClient:
    return TestClient(create_app(db_path, today=lambda: date(2026, 10, 20)), "http://127.0.0.1")


def test_reading_requests_share_one_load(client: TestClient, loads: list[int]) -> None:
    month = client.get("/api/months").json()[0]["month"]
    first = client.get("/api/summary", params={"month": month})
    second = client.get("/api/summary", params={"month": month})
    client.get("/api/summary/pace", params={"month": month})

    assert first.status_code == 200
    assert first.json() == second.json()
    assert len(loads) == 1


def test_reading_does_not_touch_the_file(client: TestClient, db_path: Path) -> None:
    before = db_path.stat().st_mtime_ns

    client.get("/api/months")
    client.get("/api/summary")

    assert db_path.stat().st_mtime_ns == before


def test_a_correction_shows_at_once(client: TestClient, db_path: Path) -> None:
    month = client.get("/api/months").json()[0]["month"]
    tx = client.get("/api/transactions", params={"month": month}).json()["items"][0]
    target = next(c for c in categories.ALL if c not in (tx["category"], categories.OTHER))

    changed = client.patch(
        f"/api/transactions/{tx['fingerprint']}",
        json={"category": target, "scope": "transaction"},
        headers=WRITE,
    )

    assert changed.status_code == 200
    after = client.get("/api/transactions", params={"month": month}).json()["items"]
    assert next(t for t in after if t["fingerprint"] == tx["fingerprint"])["category"] == target


def test_a_correction_is_kept_once_the_write_is_old(
    client: TestClient, db_path: Path, loads: list[int]
) -> None:
    month = client.get("/api/months").json()[0]["month"]
    tx = client.get("/api/transactions", params={"month": month}).json()["items"][0]
    target = next(c for c in categories.ALL if c not in (tx["category"], categories.OTHER))
    client.patch(
        f"/api/transactions/{tx['fingerprint']}",
        json={"category": target, "scope": "transaction"},
        headers=WRITE,
    )
    _settle(db_path, minutes_ago=30)
    loads.clear()

    first = client.get("/api/transactions", params={"month": month}).json()["items"]
    second = client.get("/api/transactions", params={"month": month}).json()["items"]

    assert next(t for t in first if t["fingerprint"] == tx["fingerprint"])["category"] == target
    assert first == second
    assert len(loads) == 1


def test_another_day_loads_again(db_path: Path, loads: list[int]) -> None:
    days = [date(2026, 10, 20)]
    client = TestClient(create_app(db_path, today=lambda: days[0]), "http://127.0.0.1")
    client.get("/api/months")
    client.get("/api/months")
    assert len(loads) == 1

    days[0] = date(2026, 10, 21)
    client.get("/api/months")

    assert len(loads) == 2


def test_other_holders_load_again(client: TestClient, db_path: Path, loads: list[int]) -> None:
    client.get("/api/months")
    client.get("/api/months")
    assert len(loads) == 1

    config.Paths(db_path.parent).holders.write_text("MARIA FICTICIA\n", encoding="utf-8")
    client.get("/api/months")

    assert len(loads) == 2


def test_a_change_made_by_another_process_shows(
    client: TestClient, db_path: Path, loads: list[int]
) -> None:
    month = client.get("/api/months").json()[0]["month"]
    before = client.get("/api/summary", params={"month": month}).json()["total_cents"]
    with closing(db.connect(db_path)) as conn, conn:
        conn.execute("UPDATE transactions SET amount_cents = amount_cents + 100000")
    _settle(db_path, minutes_ago=30)

    after = client.get("/api/summary", params={"month": month}).json()["total_cents"]

    assert after != before


@pytest.mark.parametrize(
    ("day", "month"),
    [(date(2026, 3, 5), "2026-03"), (date(2025, 12, 31), "2025-12"), (date(987, 1, 1), "0987-01")],
)
def test_a_movement_month_is_year_and_month(day: date, month: str) -> None:
    movement = spending.Movement(
        day=day,
        merchant="TIENDA",
        description="TIENDA",
        category=categories.OTHER,
        amount=spending.Decimal("1"),
        currency="DOP",
        institution="bank",
    )

    assert movement.month == month
