"""Selección múltiple (lógica pura, datos inventados): qué se cambia y qué se omite, y la línea
de la bitácora."""

from dataclasses import replace

from finanzas.analysis import categories as cat
from finanzas.analysis.catalog import Category
from finanzas.web import batch_edit
from tests.test_web_transactions import movement

CRYPTO = Category(1, cat.CRYPTO, "ingreso", None, False, "CRYPTO")
DELIVERY = Category(2, cat.DELIVERY, "gasto", None, False, "DELIVERY")


def _credit(fp: str, category: str = cat.OTHER_INCOME, **kw):
    return movement("2026-01-10", "-5000", category, "MB DESDE 0000000123", fp=fp, **kw)


def test_plan_applies_and_skips_with_a_reason_in_the_requested_order() -> None:
    moves = [
        _credit("a"),
        replace(_credit("b"), link="exchange"),
        movement("2026-01-11", "300", cat.CASH, "CAJERO", fp="c"),
        _credit("d", cat.CRYPTO),
        replace(_credit("e"), link="shared"),  # compartido: no fija la categoría
        _credit("f"),
    ]
    found = batch_edit.plan(moves, ["f", "a", "b", "c", "d", "zz", "a", "e"], CRYPTO)
    assert [m.fingerprint for m in found.chosen] == ["f", "a", "e"]
    assert [(s.fingerprint, s.reason) for s in found.skipped] == [
        ("b", "vinculo"),
        ("c", "direccion"),
        ("d", "sin_cambio"),
        ("zz", "desconocida"),
    ]
    assert found.skipped[0].message == "está en un vínculo que fija su categoría"


def test_every_fixed_link_is_skipped() -> None:
    for link in ("cash_box", "investment", "reimbursement", "exchange"):
        found = batch_edit.plan([replace(_credit("a"), link=link)], ["a"], CRYPTO)
        assert [s.reason for s in found.skipped] == ["vinculo"]


def test_a_credit_can_go_to_an_expense_but_a_debit_never_to_an_income() -> None:
    debit = movement("2026-01-11", "300", cat.CASH, "CAJERO", fp="c")
    assert batch_edit.fits(_credit("a"), "gasto")
    assert batch_edit.fits(_credit("a"), "transferencia")
    assert batch_edit.fits(debit, "gasto")
    assert not batch_edit.fits(debit, "ingreso")
    assert [m.fingerprint for m in batch_edit.plan([debit], ["c"], DELIVERY).chosen] == ["c"]


def test_log_texts() -> None:
    assert batch_edit.count_text(1) == "1 transacción"
    assert batch_edit.count_text(12) == "12 transacciones"
    same = [_credit("a"), _credit("b")]
    assert batch_edit.before_text(same) == cat.OTHER_INCOME
    mixed = [_credit("a"), _credit("b", cat.SALARY), _credit("c", cat.SALARY)]
    assert batch_edit.before_text(mixed) == f"{cat.SALARY}, {cat.OTHER_INCOME}"
    many = [_credit(str(i), name) for i, name in enumerate(cat.INCOME)]
    assert batch_edit.before_text(many) == "varias categorías"


def test_cash_box_entries_only_go_to_their_own_kind() -> None:
    came_in = _credit("caja-1")
    went_out = movement("2026-01-11", "300", cat.CASH, "CAJA FUERTE", fp="caja-2")
    found = batch_edit.plan([came_in, went_out], ["caja-1", "caja-2"], CRYPTO)
    assert [m.fingerprint for m in found.chosen] == ["caja-1"]
    assert [(s.fingerprint, s.reason) for s in found.skipped] == [("caja-2", "caja")]
    found = batch_edit.plan([came_in, went_out], ["caja-1", "caja-2"], DELIVERY)
    assert [m.fingerprint for m in found.chosen] == ["caja-2"]
    assert [(s.fingerprint, s.reason) for s in found.skipped] == [("caja-1", "caja")]
