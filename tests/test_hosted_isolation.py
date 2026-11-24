"""The core of hosted batch 2: one person's requests never reach another person's data.

Two synthetic people, A and B, each with their own encrypted database full of distinct made-up
movements (every description carries the owner's marker) and a few writes of their own. The test
**enumerates every route registered in the app** (not a hand-written list), calls each one as A
with plausible parameters built from the route's own signature and body schema (with B's
fingerprints and ids wherever a route takes them), and proves that:

- no response (body or headers) carries B's marker, email or fingerprints;
- no request of A opens any file in B's folder, and B's files are byte for byte unchanged;
- without a session, no route opens any user database, and every route outside the open
  sign-in ones answers 401.

So a route added later (by any branch) is covered the moment it is registered; one that reads or
writes data without going through the session's workspace makes this test fail (see the
`planted` tests at the end, which add such a route and expect the audit to catch it).
"""

from __future__ import annotations

import dataclasses
import hashlib
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import sqlcipher3
import sqlcipher3.dbapi2
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from michelito import db, encrypted
from michelito.demo import generate
from michelito.hosted import connector_routes, privacy
from michelito.hosted.app import OPEN
from michelito.hosted.onboarding_routes import SHARE_PATH
from michelito.parsers.common import Statement
from tests.hosted_helpers import PHONE, WRITE, Hosted, hosted

A_EMAIL = "alpha.person@example.com"
B_EMAIL = "bravo.person@example.com"
A_MARK = "ALFAONLYMARK"
B_MARK = "BRAVOONLYMARK"
SEARCH = B_MARK[:9]  # searches aim at B's movements without echoing the whole marker
TODAY = date.today()
MONTH = TODAY.strftime("%Y-%m")
LAST = ("/api/auth/sign-out", "/api/auth/sign-out-everywhere", "/api/account")
SKIPPED_METHODS = {"OPTIONS"}
SPA = "/{path:path}"  # the interface's catch-all: the only route outside /api
EXTRA_ROWS = 20  # B makes these first, so B's ids are not ids A also has
# Optional query parameters that name something of the person's: always sent, aimed at B.
ID_PARAMS = ("accounts", "account", "category", "category_id", "reassign_to", "kind")


# Synthetic data.


def _marked(statement: Statement, mark: str, own_accounts: bool) -> Statement:
    """`mark` in every description; with `own_accounts`, other bank account numbers too, so
    the person's account keys are not the other person's."""
    identifier = f"{statement.identifier}9" if own_accounts else statement.identifier
    sections = tuple(
        dataclasses.replace(
            section,
            transactions=tuple(
                dataclasses.replace(
                    item,
                    description=f"{item.description} {mark}",
                    raw_line=f"{item.raw_line} {mark}",
                )
                for item in section.transactions
            ),
        )
        for section in statement.sections
    )
    return dataclasses.replace(statement, identifier=identifier, sections=sections)


def _fill(h: Hosted, email: str, mark: str, scratch: Path, own_accounts: bool) -> set[str]:
    """The demo's made-up statements with `mark` in every description, encrypted into that
    person's database (replacing their empty one). Returns the person's account keys."""
    account = h.service.store.account_by_email(email)
    assert account is not None
    workspace = h.service.workspace(h.service.store.sessions_of(account.id)[0])
    plain = scratch / f"{mark}.db"
    keys: set[str] = set()
    with closing(db.connect(plain)) as conn:
        for number, statement in enumerate(generate.statements(TODAY)):
            marked = _marked(statement, mark, own_accounts)
            keys.add(db.account_key(marked))
            stored = generate.store(conn, marked, f"{mark}-{number}", TODAY)
            assert stored.status == "parsed", stored.detail
        with conn:
            from michelito.analysis import rates  # noqa: PLC0415

            rates.store_bcrd(conn, generate.dollar_rates(TODAY))
    assert workspace.key is not None
    workspace.database.unlink()
    encrypted.encrypt_copy(plain, workspace.database, workspace.key)
    plain.unlink()
    return keys


@dataclasses.dataclass
class Person:
    email: str
    mark: str
    client: TestClient
    folder: Path
    fingerprints: list[str]
    category_id: int
    category_name: str  # one of the person's own categories, without the marker
    account_keys: set[str]


def _client(h: Hosted) -> TestClient:
    client = TestClient(
        h.app,
        base_url="http://127.0.0.1",
        headers={"User-Agent": PHONE},
        raise_server_exceptions=False,
    )
    h.clients.append(client)
    return client


def _person(h: Hosted, email: str, mark: str, scratch: Path, extra: int = 0) -> Person:
    """A person with their data; `extra` rows first, so their ids are not the other's."""
    client = h.sign_in(email, _client(h))
    keys = _fill(h, email, mark, scratch, own_accounts=extra > 0)
    fingerprints: list[str] = []
    for month in client.get("/api/months").json():
        found = client.get("/api/transactions", params={"month": month["month"]}).json()
        fingerprints += [row["fingerprint"] for row in found["items"]]
    assert fingerprints, "no synthetic movements"
    own_name = f"Own {email.partition('.')[0]} 0"
    for number in range(max(1, extra)):
        body = {"name": f"Own {email.partition('.')[0]} {number}", "kind": "expense"}
        assert client.post("/api/categories", json=body, headers=WRITE).status_code == 201
    # A few writes of their own, each carrying the marker.
    made = client.post(
        "/api/categories", json={"name": f"Cat {mark}", "kind": "expense"}, headers=WRITE
    )
    assert made.status_code == 201, made.text
    note = {"note": f"Note {mark}"}
    assert client.patch(f"/api/transactions/{fingerprints[0]}", json=note, headers=WRITE).is_success
    assert client.put(
        f"/api/insights/{MONTH}", json={"text": f"Insight {mark}"}, headers=WRITE
    ).is_success
    account = h.service.store.account_by_email(email)
    assert account is not None
    return Person(
        email,
        mark,
        client,
        h.data / "users" / account.folder,
        fingerprints,
        int(made.json()["id"]),
        own_name,
        keys,
    )


# Plausible parameters, from each route's own signature and schema.


@dataclasses.dataclass(frozen=True)
class Target:
    """What A's calls aim at: B's identifiers."""

    fingerprint: str
    number: int
    email: str
    account: str
    category: str

    @classmethod
    def of(cls, person: Person, other: Person) -> Target:
        """Aimed at `person`'s things (an account key `other` does not have)."""
        account = sorted(person.account_keys - other.account_keys or person.account_keys)[0]
        return cls(
            person.fingerprints[-1],
            person.category_id,
            person.email,
            account,
            person.category_name,
        )


def _from_schema(schema: dict[str, Any], name: str, target: Target, defs: dict[str, Any]) -> Any:
    if "$ref" in schema:
        return _from_schema(defs[schema["$ref"].split("/")[-1]], name, target, defs)
    for combo in ("anyOf", "oneOf", "allOf"):
        if combo in schema:
            options = [s for s in schema[combo] if s.get("type") != "null"]
            return _from_schema(options[0], name, target, defs) if options else None
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema and schema["default"] is not None and name not in ("month",):
        return schema["default"]
    lowered = name.lower()
    kind = schema.get("type")
    if kind == "integer":
        return max(target.number, int(schema.get("minimum", target.number)))
    if kind == "number":
        return max(1.0, float(schema.get("minimum", 1.0)))
    if kind == "boolean":
        return True
    if kind == "array":
        item = _from_schema(schema.get("items", {}), name, target, defs)
        return [item] * max(1, int(schema.get("minItems", 1)))
    if kind == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        wanted = set(schema.get("required", ())) | {
            key for key in properties if "fingerprint" in key.lower()
        }
        return {
            key: _from_schema(properties[key], key, target, defs)
            for key in properties
            if key in wanted
        }
    # Strings.
    if "fingerprint" in lowered or lowered in ("credit", "fingerprints"):
        return target.fingerprint
    if "email" in lowered:
        return target.email
    if lowered in ("account", "accounts"):
        return target.account
    if lowered == "category":
        return target.category
    if schema.get("format") == "date" or lowered in ("day", "date", "start", "end"):
        return TODAY.isoformat()
    if "month" in lowered or lowered in ("first", "last"):
        return MONTH
    if lowered in ("q", "query", "text", "search"):
        return SEARCH
    if lowered == "code":
        return "123456"
    pattern = schema.get("pattern", "")
    if "#" in pattern:
        return "#123456"
    if r"\d{4}" in pattern:
        return MONTH
    return "x" * max(1, int(schema.get("minLength", 1)))


def _value(annotation: Any, name: str, target: Target) -> Any:
    schema = TypeAdapter(annotation).json_schema()
    return _from_schema(schema, name, target, schema.get("$defs", {}))


def _request(route: APIRoute, method: str, target: Target) -> dict[str, Any]:
    path = route.path
    for param in route.dependant.path_params:
        value = _value(param.field_info.annotation, param.name, target)
        path = path.replace(f"{{{param.name}:path}}", str(value))
        path = path.replace(f"{{{param.name}}}", str(value))
    params: dict[str, Any] = {}
    for param in route.dependant.query_params:
        hinted = param.name in ("month", "q", "first", "last", "year", *ID_PARAMS)
        if param.field_info.is_required() or hinted or param.name.endswith("_id"):
            value = _value(param.field_info.annotation, param.name, target)
            params[param.name] = int(MONTH[:4]) if param.name == "year" else value
    request: dict[str, Any] = {"method": method, "url": path, "params": params}
    if route.body_field is not None:
        model = route.body_field.field_info.annotation
        schema = TypeAdapter(model).json_schema()
        request["json"] = _from_schema(schema, "", target, schema.get("$defs", {}))
    if method not in ("GET", "HEAD"):
        request["headers"] = WRITE
    return request


def _methods(route: APIRoute) -> set[str]:
    head = {"HEAD"} if "GET" in route.methods else set()
    return (set(route.methods) | head) - SKIPPED_METHODS


def _calls(app: FastAPI) -> list[tuple[APIRoute, str]]:
    """Every (route, method) the app registers (the interface's catch-all included; HEAD for
    every GET too), the session-ending ones last."""
    found = [
        (route, method)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in sorted(_methods(route))
    ]
    return sorted(
        found,
        key=lambda call: (
            call[0].path in LAST,
            LAST.index(call[0].path) if call[0].path in LAST else 0,
        ),
    )


# Watching which user files get opened.


@contextmanager
def _watch(monkeypatch: pytest.MonkeyPatch, users: Path) -> Iterator[list[Path]]:
    """Every file under `users` opened while inside: through SQLCipher's binding (by any
    path: `michelito.encrypted` or `sqlcipher3` directly) or through plain sqlite3."""
    opened: list[Path] = []

    def spy(real: Callable[..., Any]) -> Callable[..., Any]:
        def connect(path: Any, *args: Any, **kwargs: Any) -> Any:
            place = Path(str(path)).resolve()
            if place.is_relative_to(users.resolve()):
                opened.append(place)
            return real(path, *args, **kwargs)

        return connect

    with monkeypatch.context() as patch:
        patch.setattr(sqlcipher3, "connect", spy(sqlcipher3.connect))
        patch.setattr(sqlcipher3.dbapi2, "connect", spy(sqlcipher3.dbapi2.connect))
        patch.setattr(sqlite3, "connect", spy(sqlite3.connect))
        yield opened


def _snapshot(folder: Path) -> dict[str, str]:
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


# The audit.


@dataclasses.dataclass
class World:
    h: Hosted
    a: Person
    b: Person


@pytest.fixture
def world(tmp_path: Path) -> World:
    static = tmp_path / "static"  # a built interface, so its catch-all route exists too
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>Michelito</title>")
    (static / "assets" / "app.js").write_text("console.log('synthetic')")
    h = hosted(tmp_path, static)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    a = _person(h, A_EMAIL, A_MARK, scratch)
    b = _person(h, B_EMAIL, B_MARK, scratch, extra=EXTRA_ROWS)  # extra rows: higher ids
    assert not set(a.fingerprints) & set(b.fingerprints)
    assert b.account_keys - a.account_keys  # B has account keys A does not
    assert b.category_id > a.category_id + EXTRA_ROWS // 2  # and ids A does not reach
    return world_of(h, a, b)


def world_of(h: Hosted, a: Person, b: Person) -> World:
    return World(h, a, b)


def _signed_in(world: World) -> bool:
    return world.a.client.get("/api/auth/me").status_code == 200


def _forbidden(world: World) -> list[str]:
    """What only B's data contains: the marker, the email, the fingerprints, B's own category
    names and the account keys A does not have."""
    b, a = world.b, world.a
    own = [f"Own {b.email.partition('.')[0]} {n}" for n in range(EXTRA_ROWS)]
    return [B_MARK, b.email, *b.fingerprints, *own, *sorted(b.account_keys - a.account_keys)]


def audit(world: World, monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], dict[str, int]]:
    """Call every route as A, aimed once at B's identifiers and once at A's own (so routes also
    answer with real data); return the problems found and how many calls got each status."""
    h, a, b = world.h, world.a, world.b
    targets = (Target.of(b, a), Target.of(a, b))
    forbidden = _forbidden(world)
    before = _snapshot(b.folder)
    problems: list[str] = []
    statuses: dict[str, int] = {}
    users = h.data / "users"
    for route, method, target in ((*call, t) for call in _calls(h.app) for t in targets):
        if not _signed_in(world):
            h.clock.advance(5 * 60)  # past the resend pause of the previous code
            h.sign_in(a.email, a.client)
        request = _request(route, method, target)
        with _watch(monkeypatch, users) as opened:
            answer = a.client.request(**request)
        label = f"{method} {route.path}"
        statuses[str(answer.status_code)] = statuses.get(str(answer.status_code), 0) + 1
        text = answer.text + "".join(f"{k}:{v}" for k, v in answer.headers.items())
        # An identifier A itself sent may come back (e.g. "unknown fingerprint"): only what A
        # did not send counts; B's data always carries the marker, which A never sends.
        sent = repr(request)
        problems += [
            f"{label} returned B's {item[:12]}"
            for item in forbidden
            if item in text and item not in sent
        ]
        problems += [
            f"{label} opened B's {p.name}" for p in opened if p.is_relative_to(b.folder.resolve())
        ]
        if answer.status_code >= 500:
            problems.append(f"{label} failed with {answer.status_code}")
    if _snapshot(b.folder) != before:
        problems.append("B's files changed")
    return problems, statuses


def test_no_route_lets_one_person_reach_anothers_data(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _calls(world.h.app)
    assert len(calls) > 100  # every route of the board and of hosted mode
    assert any(route.path == SPA for route, _ in calls)
    assert any(method == "HEAD" for _, method in calls)
    problems, statuses = audit(world, monkeypatch)
    assert problems == []
    # The parameters are plausible: few calls are refused by validation (422), and many
    # get real answers; aimed at B's identifiers, routes answer "unknown" (404).
    # (HEAD is not routed to GET handlers: those calls end in the API's 404 and are left out.)
    made = sum(statuses.values())
    assert made == 2 * len(calls)
    reaching = made - 2 * sum(1 for _, method in calls if method == "HEAD")
    succeeded = sum(n for status, n in statuses.items() if status.startswith("2"))
    assert statuses.get("422", 0) < reaching // 5, statuses
    assert succeeded > reaching // 4, statuses
    # B's own data is intact and still theirs.
    b = world.b
    names = {c["name"] for c in b.client.get("/api/categories").json()}
    assert f"Cat {B_MARK}" in names and f"Cat {A_MARK}" not in names
    found = b.client.get(f"/api/transactions/{b.fingerprints[0]}")
    assert found.status_code == 200 and f"Note {B_MARK}" in found.text


def test_every_route_is_an_api_route_or_the_interfaces_catch_all(world: World) -> None:
    """Nothing escapes the audit: no mounted sub-app, no other kind of route, and outside /api
    only the interface's catch-all (audited like the rest)."""
    routes = world.h.app.routes
    assert all(isinstance(route, APIRoute) for route in routes), [
        type(route).__name__ for route in routes if not isinstance(route, APIRoute)
    ]
    outside = {route.path for route in routes if not route.path.startswith("/api")}  # type: ignore[attr-defined]
    # Besides the interface, only the installed app's share target and the privacy page with
    # its stylesheet, which open no database (test_hosted_upload_limits.py,
    # test_hosted_hardening.py, test_hosted_mailbox.py), and the AI connector's OAuth discovery
    # and endpoints, which open no database either (test_hosted_mcp.py).
    oauth = {
        connector_routes.PROTECTED_PATH,
        connector_routes.PROTECTED_PATH + "/api/mcp",
        connector_routes.SERVER_PATH,
        connector_routes.REGISTER_PATH,
        connector_routes.AUTHORIZE_PATH,
        connector_routes.TOKEN_PATH,
    }
    assert outside == {SPA, SHARE_PATH, privacy.PATH, privacy.CSS_PATH, *oauth}
    anonymous = _client(world.h)
    page = anonymous.get("/settings")
    assert page.status_code == 200 and "Michelito" in page.text
    assert anonymous.get("/assets/app.js").status_code == 200


def test_without_a_session_no_route_opens_a_user_database(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = world.h
    target = Target.of(world.b, world.a)
    anonymous = _client(h)
    before = {p.email: _snapshot(p.folder) for p in (world.a, world.b)}
    for route, method in _calls(h.app):
        request = _request(route, method, target)
        with _watch(monkeypatch, h.data / "users") as opened:
            answer = anonymous.request(**request)
        label = f"{method} {route.path}"
        assert opened == [], label
        assert answer.status_code < 500, label
        for item in _forbidden(world):
            assert item not in answer.text, label
        path = request["url"]
        if path.startswith("/api") and path not in OPEN:
            assert answer.status_code in (401, 403), label
    assert {p.email: _snapshot(p.folder) for p in (world.a, world.b)} == before


# The audit catches a route that is not scoped to the session.


def _plant(app: FastAPI, path: str, handler: Callable[..., Any], method: str = "GET") -> None:
    """Register a route ahead of the catch-all (as a new feature's route would be)."""
    app.add_api_route(path, handler, methods=[method])
    app.router.routes.insert(0, app.router.routes.pop())


def _first_other_workspace(h: Hosted, email: str):  # noqa: ANN202
    """An unscoped helper: "the first account that is not me" (a typical bug)."""
    for stored in h.service.store.data_keys():
        sessions = h.service.store.sessions_of(stored.account_id)
        if sessions and sessions[0].account.email != email:
            return h.service.workspace(sessions[0])
    raise AssertionError("no other account")


def test_planted_unscoped_read_is_caught(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    h = world.h

    def leak() -> list[str]:
        workspace = _first_other_workspace(h, A_EMAIL)
        with closing(db.connect(workspace.database, workspace.key)) as conn:
            return [row["name"] for row in conn.execute("SELECT name FROM categories")]

    _plant(h.app, "/api/zz-planted-read", leak)
    problems, _ = audit(world, monkeypatch)
    assert any("/api/zz-planted-read returned B's" in p for p in problems), problems
    assert any("/api/zz-planted-read opened B's" in p for p in problems), problems


def test_planted_unscoped_write_is_caught(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    h = world.h

    def scribble() -> dict[str, str]:
        workspace = _first_other_workspace(h, A_EMAIL)
        with closing(db.connect(workspace.database, workspace.key)) as conn, conn:
            conn.execute("UPDATE categories SET hidden = 1 - hidden")
        return {"status": "ok"}

    _plant(h.app, "/api/zz-planted-write", scribble, "POST")
    problems, _ = audit(world, monkeypatch)
    assert "B's files changed" in problems
    assert any("/api/zz-planted-write opened B's" in p for p in problems), problems


def test_a_direct_engine_open_is_seen(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """A route that bypasses `michelito.db` and `michelito.encrypted` and calls the binding
    itself is still watched (it would be reported as "opened B's")."""
    h = world.h

    def peek() -> dict[str, int]:
        workspace = _first_other_workspace(h, A_EMAIL)
        assert workspace.key is not None
        raw = sqlcipher3.connect(str(workspace.database))
        try:
            raw.executescript(f"PRAGMA key = \"x'{workspace.key.hex()}'\";")
            return {"n": raw.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]}
        finally:
            raw.close()

    _plant(h.app, "/api/zz-planted-peek", peek)
    with _watch(monkeypatch, h.data / "users") as opened:
        assert world.a.client.get("/api/zz-planted-peek").status_code == 200
    assert any(p.is_relative_to(world.b.folder.resolve()) for p in opened)
