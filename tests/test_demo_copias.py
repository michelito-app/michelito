"""Las copias de la demo: creación atómica, barrido y límites (`demo.copias`)."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest

from finanzas.demo import generar
from finanzas.demo.copias import CopyStore, DemoFull, Limits, valid_id
from tests.demo_helpers import TODAY, _restore_providers  # noqa: F401

DAY = 24 * 3600.0


def q(key: str) -> tuple[tuple[str, int], ...]:
    """Un solo cupo con esa clave."""
    return ((key, 1),)


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def template(tmp_path: Path) -> Path:
    built = generar.build_template(tmp_path / "plantilla", TODAY)
    return built.database.parent


def test_valid_id_only_accepts_32_hex() -> None:
    assert valid_id("0123456789abcdef0123456789abcdef")
    for bad in (None, "", "../x", "0123456789ABCDEF0123456789ABCDEF", "g" * 32, "a" * 31):
        assert not valid_id(bad)


def test_sweep_removes_only_stale_copies(tmp_path: Path, template: Path) -> None:
    clock = Clock()
    store = CopyStore(tmp_path / "copias", template, clock=clock)
    old, fresh = store.create(q("ip")), store.create(q("ip2"))
    stale = clock.now - DAY - 60
    os.utime(tmp_path / "copias" / old, (stale, stale))
    (tmp_path / "copias" / ".borrar-x").mkdir()  # restos de un barrido cortado
    assert store.sweep() == 1
    assert sorted(p.name for p in (tmp_path / "copias").iterdir()) == [fresh]
    assert store.workspace(old) is None and store.workspace(fresh) is not None


def test_use_keeps_a_copy_alive(tmp_path: Path, template: Path) -> None:
    clock = Clock()
    store = CopyStore(tmp_path / "copias", template, clock=clock)
    copy_id = store.create(q("ip"))
    clock.now += DAY - 120
    assert store.workspace(copy_id) is not None  # la toca
    clock.now += 600
    assert store.sweep() == 0


def test_startup_sweeps(tmp_path: Path, template: Path) -> None:
    clock = Clock()
    first = CopyStore(tmp_path / "copias", template, clock=clock)
    copy_id = first.create(q("ip"))
    clock.now += 2 * DAY
    CopyStore(tmp_path / "copias", template, clock=clock)
    assert not (tmp_path / "copias" / copy_id).exists()


def test_ip_limit_resets_next_day(tmp_path: Path, template: Path) -> None:
    day = [date(2026, 1, 1)]
    store = CopyStore(tmp_path / "c", template, Limits(per_ip=1), today=lambda: day[0])
    store.create(q("ip-documentacion"))
    with pytest.raises(DemoFull) as caught:
        store.create(q("ip-documentacion"))
    assert caught.value.reason == "ip"
    day[0] = date(2026, 1, 2)
    store.create(q("ip-documentacion"))  # otro día: la IP se olvidó


def test_concurrent_creation_never_exceeds_the_cap(tmp_path: Path, template: Path) -> None:
    store = CopyStore(tmp_path / "copias", template, Limits(per_ip=100, max_live=5))

    def attempt(n: int) -> str | None:
        try:
            return store.create(q(f"ip{n}"))
        except DemoFull:
            return None

    with ThreadPoolExecutor(8) as pool:
        made = [found for found in pool.map(attempt, range(20)) if found]
    assert len(made) == 5 == store.live()
    for copy_id in made:
        workspace = store.workspace(copy_id)
        assert workspace is not None and workspace.database.stat().st_size > 0
    assert not [p for p in (tmp_path / "copias").iterdir() if p.name.startswith(".")]


def test_restart_has_a_cooldown_per_copy(tmp_path: Path, template: Path) -> None:
    clock = Clock()
    store = CopyStore(tmp_path / "copias", template, clock=clock)
    first = store.create(q("ip"))
    second = store.restart(first, q("ip"))  # la primera vez, sí
    assert not (tmp_path / "copias" / first).exists()
    with pytest.raises(DemoFull) as caught:
        store.restart(second, q("ip"))  # la nueva hereda la espera
    assert caught.value.reason == "reinicio"
    clock.now += 301
    store.restart(second, q("ip"))


def test_restarts_have_their_own_daily_and_global_caps(tmp_path: Path, template: Path) -> None:
    clock = Clock()
    limits = Limits(per_ip=1, per_minute_new=2, restart_cooldown=0, restarts_per_day=2)
    store = CopyStore(tmp_path / "copias", template, limits, clock=clock)
    copy_id = store.create(q("ip"))
    for _ in range(2):
        copy_id = store.restart(copy_id, q("ip"))
    with pytest.raises(DemoFull) as caught:
        store.restart(copy_id, q("ip"))
    assert caught.value.reason == "reinicio"
    # Los reinicios no gastaron ni el cupo de copias nuevas por minuto ni el de la IP de otro.
    store.create(q("otra-ip"))
    global_cap = CopyStore(
        tmp_path / "otras", template, Limits(restart_cooldown=0, restarts_per_minute=1)
    )
    a, b = global_cap.create(q("a")), global_cap.create(q("b"))
    global_cap.restart(a, q("a"))
    with pytest.raises(DemoFull) as full:
        global_cap.restart(b, q("b"))
    assert full.value.reason == "llena"


def test_restart_keeps_the_minute_budget(tmp_path: Path, template: Path) -> None:
    store = CopyStore(tmp_path / "copias", template, Limits(per_minute=3))
    copy_id = store.create(q("ip"))
    assert store.allow_request(copy_id, 3)
    fresh = store.restart(copy_id, q("ip"))
    assert not store.allow_request(fresh, 1)
