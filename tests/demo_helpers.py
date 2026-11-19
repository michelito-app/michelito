"""Ayudas de las pruebas del modo demo (datos inventados del generador)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas.analysis import providers
from finanzas.demo.app import Settings, create_demo_app
from finanzas.demo.copias import Limits

TODAY = date(2026, 11, 18)
HOST = "demo.example"
WRITE = {"X-Finanzas": "1"}


@pytest.fixture(autouse=True)
def _restore_providers(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """La demo suma proveedores inventados a la lista global: se deshace al terminar."""
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
    """Otro visitante (sus propias cookies) sobre la misma app; ya con su copia."""
    other = TestClient(base.app, base_url=f"http://{HOST}")
    assert other.post("/api/demo/sesion", headers=WRITE).status_code == 201
    return other
