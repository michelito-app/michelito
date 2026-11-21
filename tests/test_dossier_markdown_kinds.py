"""The dossier Markdown shows kinds the way the release before the English rename did.

The data carries the English stored values (`expense`, `one_off`, …), but the Markdown Claude Code
reads must not change: the transactions table writes a category kind and the "to review" table a
review kind as the old release did, i.e. their old stored Spanish values. The old values come from
`legacy`, the maps the database migration used, so this compares against what the previous release
stored and printed.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from michelito import db, dossier, legacy
from michelito.analysis import review
from michelito.i18n import t
from tests.e2e_server import build_demo_db

FEBRUARY = "2026-02"
OLD_CATEGORY_KINDS = {new: old for old, new in legacy.CATEGORY_KINDS.items()}
# A kind added after the rename is written the same way (schema 19: "To review" proposes
# payments of shared groups).
OLD_REVIEW_KINDS = {
    **{new: old for old, new in legacy.REVIEW_KINDS.items()},
    "possible_payment": "pago_posible",  # spanish-data
    "possible_cover": "pago_por_otros",  # spanish-data (schema 22: paid for others)
}


@pytest.fixture
def built(tmp_path: Path) -> dossier.Dossier:
    path = tmp_path / "demo.db"
    build_demo_db(path)
    with closing(db.connect(path)) as conn:
        return dossier.build(conn, FEBRUARY, holders=())


def _table_rows(markdown: str, section_key: str) -> list[list[str]]:
    """The cells of the data table under the section titled `t(section_key)`."""
    lines = markdown.splitlines()
    start = lines.index(t(section_key))
    fence = lines.index("```text", start)
    end = lines.index("```", fence + 1)
    rows = lines[fence + 3 : end]  # after the column titles and the rule
    return [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]


def _escaped(value: str) -> str:
    """How a table cell writes `value` (`_` is escaped)."""
    return value.replace("_", "\\_")


def test_the_transaction_kind_is_the_old_spanish_value(built: dossier.Dossier) -> None:
    kind_column = 3  # date, description, category, kind, …
    rows = _table_rows(built.markdown, "dossier.section.transactions")
    expected = [_escaped(OLD_CATEGORY_KINDS[m["kind"]]) for m in built.data["transactions"]]
    assert rows and [row[kind_column] for row in rows] == expected
    assert {row[kind_column] for row in rows} >= {"gasto", "ingreso"}  # spanish-ui


def test_the_review_kind_is_the_old_stored_value(built: dossier.Dossier) -> None:
    kind_column = 0  # kind, date, …
    rows = _table_rows(built.markdown, "dossier.section.to_review")
    expected = [_escaped(OLD_REVIEW_KINDS[item["kind"]]) for item in built.data["to_review"]]
    assert rows and [row[kind_column] for row in rows] == expected
    assert {row[kind_column] for row in rows} >= {"unico", "subio"}  # spanish-ui


def test_no_english_kind_value_reaches_the_markdown(built: dossier.Dossier) -> None:
    for section, column in (
        ("dossier.section.transactions", 3),
        ("dossier.section.to_review", 0),
    ):
        cells = {row[column] for row in _table_rows(built.markdown, section)}
        english = {_escaped(k) for k in (*OLD_CATEGORY_KINDS, *OLD_REVIEW_KINDS)}
        assert not cells & english, section


# Review kinds added after the rename: they never had an old stored value.
NEWER_REVIEW_KINDS = ("unconfirmed", "reversal")


@pytest.mark.parametrize("kind", [k for k in review.KINDS if k not in NEWER_REVIEW_KINDS])
def test_every_review_kind_has_its_old_label(kind: str) -> None:
    assert t(f"dossier.review_kind.{kind}") == OLD_REVIEW_KINDS[kind]


@pytest.mark.parametrize("kind", NEWER_REVIEW_KINDS)
def test_a_newer_review_kind_has_a_spanish_label_in_the_same_style(kind: str) -> None:
    label = t(f"dossier.review_kind.{kind}")
    assert kind in review.KINDS
    assert label != kind and label == label.lower() and " " not in label


@pytest.mark.parametrize("kind", sorted(OLD_CATEGORY_KINDS))
def test_every_category_kind_has_its_old_label(kind: str) -> None:
    assert t(f"dossier.kind.{kind}") == OLD_CATEGORY_KINDS[kind]
