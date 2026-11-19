"""Helpers for the demo-mode tests (made-up data from the generator)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito.analysis import providers
from michelito.demo.app import Settings, create_demo_app
from michelito.demo.copies import Limits

TODAY = date(2026, 11, 18)
HOST = "demo.example"
WRITE = {"X-Michelito": "1"}


@pytest.fixture(autouse=True)
def _restore_providers(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The demo adds made-up providers to the global list: undo that afterwards."""
    monkeypatch.setattr(providers, "PROVIDERS", providers.PROVIDERS)
    yield


def settings(tmp_path: Path, **limits: float) -> Settings:
    return Settings(
        data=tmp_path / "demo",
        public_host=HOST,
        secure_cookie=False,
        repo="https://example.com/repo",
        limits=Limits(**limits),  # type: ignore[arg-type]
        background=False,
    )


def client(tmp_path: Path, **limits: float) -> TestClient:
    app = create_demo_app(settings(tmp_path, **limits), today=lambda: TODAY)
    return TestClient(app, base_url=f"http://{HOST}")


def visitor(base: TestClient) -> TestClient:
    """Another visitor (own cookies) on the same app, already holding its copy."""
    other = TestClient(base.app, base_url=f"http://{HOST}")
    assert other.post("/api/demo/session", headers=WRITE).status_code == 201
    return other
