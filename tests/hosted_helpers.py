"""Helpers for the hosted-mode tests: an app with the in-memory mailer and a controllable clock.

Only synthetic addresses (`example.com`); nothing is sent anywhere. Each app gets a throwaway
master key, generated in the test's temporary folder (outside the hosted data folder).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from michelito.hosted.app import Settings, create_hosted_app
from michelito.hosted.keys import write_master
from michelito.hosted.mailer import MemoryMailer

WRITE = {"X-Michelito": "1"}
PHONE = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Mobile Safari/537.36"
)
_CODE = re.compile(r"\b(\d{6})\b")
_LINK = re.compile(r"#link=([A-Za-z0-9_-]+)")


@dataclass
class Clock:
    now: float = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class Hosted:
    app: FastAPI
    mailer: MemoryMailer
    clock: Clock
    data: Path
    clients: list[TestClient] = field(default_factory=list)

    @property
    def service(self):  # noqa: ANN201
        return self.app.state.service

    def client(self, agent: str = PHONE) -> TestClient:
        client = TestClient(self.app, base_url="http://127.0.0.1", headers={"User-Agent": agent})
        self.clients.append(client)
        return client

    def last_code(self, email: str) -> str:
        found = [m for m in self.mailer.sent if m.to == email]
        match = _CODE.search(found[-1].text)
        assert match is not None
        return match.group(1)

    def last_link(self, email: str) -> str:
        found = [m for m in self.mailer.sent if m.to == email]
        match = _LINK.search(found[-1].text)
        assert match is not None
        return match.group(1)

    def sign_in(
        self, email: str, client: TestClient | None = None, gate: bool = False
    ) -> TestClient:
        """Invite (if needed) and sign in that email; the client keeps the cookie. Unless
        `gate`, the server-side upload gate lets the account through (the tests about the gate
        and uploads pass `gate=True`; the gate's own checks still read the database)."""
        client = client or self.client()
        if self.service.store.account_by_email(email) is None:
            self.service.invite(email)
        else:
            assert client.post("/api/auth/code", json={"email": email}, headers=WRITE).is_success
        code = self.last_code(email)
        answer = client.post("/api/auth/verify", json={"email": email, "code": code}, headers=WRITE)
        assert answer.status_code == 204, answer.text
        if not gate:
            past_the_gate(self, email)
        return client


def past_the_gate(h: Hosted, *emails: str) -> None:
    """Let these accounts through the upload gate without uploading (the gate itself is tested
    in test_hosted_hardening.py): for tests about other routes."""
    for email in emails:
        account = h.service.store.account_by_email(email)
        assert account is not None
        h.app.state.uploads.opened.add(account.id)


def master_file(tmp_path: Path, name: str = "master.key") -> Path:
    """A throwaway master key file in `tmp_path` (0400), created once."""
    path = tmp_path / name
    if not path.exists():
        write_master(path)
    return path


def hosted(tmp_path: Path, static_dir: Path | None = None, **overrides: object) -> Hosted:
    clock = Clock()
    mailer = MemoryMailer()
    options: dict[str, object] = {
        "data": tmp_path / "hosted",
        "master_key": master_file(tmp_path),
        "secure_cookie": False,
        "floor": 0.0,
        "background_mail": False,
        "public_url": "https://app.example",
        "sweep": False,
        **overrides,
    }
    settings = Settings(**options)  # type: ignore[arg-type]
    app = create_hosted_app(settings, mailer, static_dir, clock=clock)
    return Hosted(app, mailer, clock, tmp_path / "hosted")
