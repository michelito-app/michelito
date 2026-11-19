"""Multi-select (pure logic, made-up data): what changes and what is skipped, and the change-log
line."""

from dataclasses import replace

from michelito.analysis import categories as cat
from michelito.analysis.catalog import Category
from michelito.web import batch_edit
from tests.test_web_transactions import movement

CRYPTO = Category(1, cat.CRYPTO, "income", None, False, "CRYPTO")
DELIVERY = Category(2, cat.DELIVERY, "expense", None, False, "DELIVERY")


def _credit(fp: str, category: str = cat.OTHER_INCOME, **kw):
    return movement("2026-01-10", "-5000", category, "MB DESDE 0000000123", fp=fp, **kw)


def test_plan_applies_and_skips_with_a_reason_in_the_requested_order() -> None:
    moves = [
        _credit("a"),
        replace(_credit("b"), link="exchange"),
        movement("2026-01-11", "300", cat.CASH, "CAJERO", fp="c"),
        _credit("d", cat.CRYPTO),
        replace(_credit("e"), link="shared"),  # shared: does not fix the category
        _credit("f"),
    ]
    found = batch_edit.plan(moves, ["f", "a", "b", "c", "d", "zz", "a", "e"], CRYPTO)
    assert [m.fingerprint for m in found.chosen] == ["f", "a", "e"]
    assert [(s.fingerprint, s.reason) for s in found.skipped] == [
        ("b", "linked"),
        ("c", "direction"),
        ("d", "unchanged"),
        ("zz", "unknown"),
    ]
    assert found.skipped[0].message == "está en un vínculo que fija su categoría"  # spanish-ui


def test_every_fixed_link_is_skipped() -> None:
    for link in ("cash_box", "investment", "reimbursement", "exchange"):
        found = batch_edit.plan([replace(_credit("a"), link=link)], ["a"], CRYPTO)
        assert [s.reason for s in found.skipped] == ["linked"]


def test_a_credit_can_go_to_an_expense_but_a_debit_never_to_an_income() -> None:
    debit = movement("2026-01-11", "300", cat.CASH, "CAJERO", fp="c")
    assert batch_edit.fits(_credit("a"), "expense")
    assert batch_edit.fits(_credit("a"), "transfer")
    assert batch_edit.fits(debit, "expense")
    assert not batch_edit.fits(debit, "income")
    assert [m.fingerprint for m in batch_edit.plan([debit], ["c"], DELIVERY).chosen] == ["c"]


def test_log_texts() -> None:
    assert batch_edit.count_text(1) == "1 transacción"  # spanish-ui
    assert batch_edit.count_text(12) == "12 transacciones"  # spanish-ui
    same = [_credit("a"), _credit("b")]
    assert batch_edit.before_text(same) == cat.OTHER_INCOME
    mixed = [_credit("a"), _credit("b", cat.SALARY), _credit("c", cat.SALARY)]
    assert batch_edit.before_text(mixed) == f"{cat.SALARY}, {cat.OTHER_INCOME}"
    many = [_credit(str(i), name) for i, name in enumerate(cat.INCOME)]
    assert batch_edit.before_text(many) == "varias categorías"  # spanish-ui


def test_cash_box_entries_only_go_to_their_own_kind() -> None:
    came_in = _credit("cash-1")
    went_out = movement("2026-01-11", "300", cat.CASH, "CAJA FUERTE", fp="cash-2")
    found = batch_edit.plan([came_in, went_out], ["cash-1", "cash-2"], CRYPTO)
    assert [m.fingerprint for m in found.chosen] == ["cash-1"]
    assert [(s.fingerprint, s.reason) for s in found.skipped] == [("cash-2", "cash_box")]
    found = batch_edit.plan([came_in, went_out], ["cash-1", "cash-2"], DELIVERY)
    assert [m.fingerprint for m in found.chosen] == ["cash-2"]
    assert [(s.fingerprint, s.reason) for s in found.skipped] == [("cash-1", "cash_box")]
