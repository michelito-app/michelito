"""The public pages as Google's branding checker reads them: the home page says what the app is
and links to the privacy policy without JavaScript, and every public page answers `HEAD`."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito.hosted import privacy
from tests.hosted_helpers import hosted

INDEX = (
    '<html><body><div id="root"></div><script type="module" src="/app.js"></script></body></html>'
)


@pytest.fixture
def anonymous(tmp_path: Path) -> TestClient:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text(INDEX, encoding="utf-8")
    return hosted(tmp_path, static_dir=static).client()


def test_the_home_page_describes_the_app_and_links_the_policy_without_javascript(
    anonymous: TestClient,
) -> None:
    page = anonymous.get("/")

    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert '<div id="root"><main' in page.text
    assert privacy.ENGLISH["privacy.home.lead"] in page.text
    assert 'href="/privacy"' in page.text
    assert '<script type="module" src="/app.js"></script>' in page.text


def test_other_paths_of_the_interface_keep_the_plain_index(anonymous: TestClient) -> None:
    assert anonymous.get("/settings").text == INDEX


@pytest.mark.parametrize("path", ["/", "/privacy", "/privacy.css", "/settings"])
def test_the_public_pages_answer_head(anonymous: TestClient, path: str) -> None:
    got = anonymous.head(path)

    assert got.status_code == 200
    assert got.text == ""


def test_the_home_texts_are_escaped() -> None:
    hostile = {key: "<b>&</b>" for key in privacy.ENGLISH}

    found = privacy._home_part(hostile, "en")

    assert "<b>" not in found and "&lt;b&gt;&amp;&lt;/b&gt;" in found
