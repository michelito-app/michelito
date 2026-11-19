"""The category catalog: built-ins, user categories, renames, deletes and keywords."""

import re
from datetime import date
from decimal import Decimal

import pytest

from michelito import db
from michelito.analysis import catalog, corrections, one_offs, spending
from michelito.analysis import categories as cat
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import summary
from tests.test_spending import seed

HOLDERS = ["JUAN PEREZ"]


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    seed(connection)
    yield connection
    connection.close()


def _id(conn, ref: str) -> int:
    found = catalog.load(conn).by_ref(ref)
    assert found is not None
    return found.id


def _by_description(conn, text: str) -> Movement:
    return next(m for m in spending.load_all(conn, HOLDERS) if m.description.startswith(text))


def _user(conn, name: str, kind: str = "expense", keywords=()) -> catalog.Category:
    with conn:
        made = catalog.create(conn, name, kind)
        if keywords:
            catalog.set_keywords(conn, made.id, keywords)
    return made


class TestCatalog:
    def test_builtins_are_seeded_with_their_kind_and_order(self, conn) -> None:
        known = catalog.load(conn)
        assert [c.ref for c in known.items] == list(cat.ALL)
        vehicle = known.by_ref(cat.VEHICLE)
        assert vehicle is not None
        assert (vehicle.builtin_key, vehicle.name, vehicle.kind) == (
            "VEHICLE",
            cat.VEHICLE,
            "expense",
        )
        assert known.by_ref(cat.THIRD_PARTY).kind == "transfer"

    def test_by_name_reads_old_and_birth_names(self, conn) -> None:
        with conn:
            catalog.update(conn, _id(conn, cat.GROCERIES), name="Súper")  # spanish-data
        known = catalog.load(conn)
        # Ignoring case and accents.
        assert known.by_name("super").ref == cat.GROCERIES
        assert known.by_name(cat.GROCERIES).ref == cat.GROCERIES  # old link by birth name
        assert known.by_name("Efectivo y transferencias").ref == cat.CASH  # spanish-data
        assert known.by_name("Made-up") is None

    def test_user_categories_go_after_the_builtins_of_their_kind(self, conn) -> None:
        made = _user(conn, "Vehicle maintenance")
        income = _user(conn, "Rentals", "income")
        refs = [c.ref for c in catalog.load(conn).items]
        assert refs.index(made.ref) == len(cat.EXPENSES)
        assert refs.index(income.ref) == len(cat.EXPENSES) + 1 + len(cat.INCOME)
        assert made.ref == f"user:{made.id}"

    def test_duplicate_names_are_rejected_ignoring_case_and_accents(self, conn) -> None:
        with pytest.raises(catalog.DuplicateName):
            catalog.create(conn, cat.VEHICLE.upper(), "expense")
        with pytest.raises(catalog.DuplicateName):
            catalog.create(conn, "vehiculo y COMBUSTIBLE", "expense")  # spanish-data
        made = _user(conn, "Garage")
        with pytest.raises(catalog.DuplicateName):
            catalog.update(conn, _id(conn, cat.OTHER), name="garage")
        catalog.update(conn, made.id, name="Garage")  # its own name is fine

    def test_invalid_input(self, conn) -> None:
        with pytest.raises(
            catalog.CategoryError,
            match=re.escape(t("analysis.catalog.unknown_kind", kind="savings")),
        ):
            catalog.create(conn, "X", "savings")
        with pytest.raises(
            catalog.CategoryError, match=re.escape(t("analysis.catalog.invalid_color", color="red"))
        ):
            catalog.create(conn, "X", "expense", "red")
        with pytest.raises(
            catalog.CategoryError, match=re.escape(t("analysis.catalog.name_empty"))
        ):
            catalog.create(conn, "   ", "expense")
        empty_keyword = t("analysis.catalog.keyword_empty", keyword=repr("--"))
        with pytest.raises(catalog.CategoryError, match=re.escape(empty_keyword)):
            catalog.set_keywords(conn, _id(conn, cat.OTHER), ["--"])
        with pytest.raises(catalog.NotFound):
            catalog.update(conn, 9999, name="Nothing")

    def test_builtins_cannot_change_kind_or_be_deleted(self, conn) -> None:
        loans = _id(conn, cat.LOANS)
        with pytest.raises(catalog.Forbidden):
            catalog.update(conn, loans, kind="transfer")
        with pytest.raises(catalog.Forbidden):
            catalog.delete(conn, loans, _id(conn, cat.OTHER))
        with conn:
            changed = catalog.update(
                conn, loans, name="Debts", color="#1F6F5C", hidden=True, kind="expense"
            )
        assert (changed.name, changed.color, changed.hidden) == ("Debts", "#1F6F5C", True)
        with conn:
            assert catalog.update(conn, loans, color=None).color is None

    def test_keywords_are_normalized_like_descriptions(self, conn) -> None:
        keywords = ["  garage ", "Mecánica-Rápida", "GARAGE"]  # spanish-data
        made = _user(conn, "Garage", keywords=keywords)
        assert catalog.load(conn).by_id(made.id).keywords == ("GARAGE", "MECANICA RAPIDA")


class TestRename:
    def test_rename_keeps_corrections(self, conn) -> None:
        cafe = _by_description(conn, "CAFE FICTICIO")
        with conn:
            corrections.set_transaction_category(conn, cafe.fingerprint, cat.GROCERIES)
            corrections.set_merchant_category(conn, "FARMACIA INVENTADA", cat.HEALTH)
            catalog.update(conn, _id(conn, cat.GROCERIES), name="Market")
            catalog.update(conn, _id(conn, cat.HEALTH), name="Doctor")
        fixed = _by_description(conn, "CAFE FICTICIO")
        assert (fixed.category, fixed.ref, fixed.corrected) == ("Market", cat.GROCERIES, True)
        assert fixed.original_category == cat.RESTAURANTS
        assert _by_description(conn, "FARMACIA INVENTADA").category == "Doctor"

    def test_builtin_logic_survives_renaming_the_builtins(self, conn) -> None:
        with conn:
            for ref in (cat.CARD_PAYMENT, cat.OWN_TRANSFER, cat.OTHER_INCOME, cat.THIRD_PARTY):
                catalog.update(conn, _id(conn, ref), name=f"{ref} (mine)")
        payment = _by_description(conn, "SU PAGO GRACIAS")
        assert (payment.ref, payment.kind, payment.category) == (
            cat.CARD_PAYMENT,
            "transfer",
            f"{cat.CARD_PAYMENT} (mine)",
        )
        bank = _by_description(conn, "PAGO DE TC")  # paired with the card payment
        assert (bank.ref, bank.kind) == (cat.CARD_PAYMENT, "transfer")
        income = _by_description(conn, "TRANSFERENCIA RECIBIDA")
        assert (income.ref, income.kind) == (cat.OTHER_INCOME, "income")

    def test_summary_and_one_offs_compare_references_not_names(self) -> None:
        def move(ref: str, name: str, amount: str) -> Movement:
            return Movement(
                day=date(2026, 1, 10),
                merchant="X",
                description="X",
                category=name,
                amount=Decimal(amount),
                currency="DOP",
                institution="bhd",
                fingerprint=f"fp-{ref}",
                account="bhd:savings:1",
                category_key=ref,
            )

        sent = move(cat.THIRD_PARTY, "Transfers out", "700")
        assert summary._third_party([sent], {}, "2026-01") == Decimal(700)
        # Loans are never suggested as a one-off expense, whatever they are called.
        loan = move(cat.LOANS, "Debts", "90000")
        found = one_offs.suggest([loan], "2026-01", rate_for_month=lambda _: None, dismissed=())
        assert found == []


class TestDelete:
    def test_delete_reassigns_corrections_and_keywords(self, conn) -> None:
        made = _user(conn, "Pharmacy", keywords=["FARMACIA"])
        cafe = _by_description(conn, "CAFE FICTICIO")
        with conn:
            corrections.set_transaction_category(conn, cafe.fingerprint, made.id)
            corrections.set_merchant_category(conn, "TIENDA ONLINE", made.ref)
        assert _by_description(conn, "FARMACIA INVENTADA").category == "Pharmacy"
        with pytest.raises(catalog.Forbidden, match=re.escape(t("analysis.catalog.in_use"))):
            catalog.delete(conn, made.id, None)
        health = _id(conn, cat.HEALTH)
        with conn:
            catalog.delete(conn, made.id, health)
        assert catalog.load(conn).by_id(made.id) is None
        assert catalog.load(conn).by_id(health).keywords == ("FARMACIA",)
        assert _by_description(conn, "FARMACIA INVENTADA").ref == cat.HEALTH
        assert _by_description(conn, "CAFE FICTICIO").ref == cat.HEALTH
        assert _by_description(conn, "TIENDA ONLINE").ref == cat.HEALTH

    def test_unused_category_is_deleted_without_target(self, conn) -> None:
        made = _user(conn, "Empty")
        with conn:
            catalog.delete(conn, made.id, None)
        assert catalog.load(conn).by_id(made.id) is None

    def test_target_must_exist_and_differ(self, conn) -> None:
        made = _user(conn, "Pharmacy", keywords=["FARMACIA"])
        with pytest.raises(catalog.Forbidden):
            catalog.delete(conn, made.id, made.id)
        with pytest.raises(catalog.NotFound):
            catalog.delete(conn, made.id, 9999)


class TestKeywords:
    def test_keywords_move_past_movements(self, conn) -> None:
        made = _user(conn, "Pharmacy", keywords=["FARMACIA"])
        pharmacy = _by_description(conn, "FARMACIA INVENTADA")
        assert (pharmacy.category, pharmacy.ref, pharmacy.kind) == ("Pharmacy", made.ref, "expense")
        assert not pharmacy.corrected
        assert pharmacy.original_category == "Pharmacy"

    def test_keyword_beats_builtin_rules_and_mcc(self, conn) -> None:
        made = _user(conn, "Corner stores", keywords=["COLMADO"])
        assert _by_description(conn, "COLMADO INVENTADO").ref == made.ref  # grocery MCC

    def test_whole_words_only(self, conn) -> None:
        _user(conn, "Odd", keywords=["COLMA"])
        assert _by_description(conn, "COLMADO INVENTADO").ref == cat.GROCERIES

    def test_correction_beats_keyword(self, conn) -> None:
        _user(conn, "Corner stores", keywords=["COLMADO"])
        colmado = _by_description(conn, "COLMADO INVENTADO")
        with conn:
            corrections.set_transaction_category(conn, colmado.fingerprint, cat.HOME)
        assert _by_description(conn, "COLMADO INVENTADO").ref == cat.HOME
        with conn:
            corrections.set_transaction_category(conn, colmado.fingerprint, None)
            corrections.set_merchant_category(conn, colmado.merchant, cat.HEALTH)
        assert _by_description(conn, "COLMADO INVENTADO").ref == cat.HEALTH

    def test_detected_transfer_beats_keyword(self, conn) -> None:
        _user(conn, "Payments", keywords=["PAGO", "SU PAGO GRACIAS"])
        assert _by_description(conn, "SU PAGO GRACIAS").ref == cat.CARD_PAYMENT
        assert _by_description(conn, "PAGO DE TC").ref == cat.CARD_PAYMENT

    def test_longest_keyword_wins_and_ties_go_to_the_lower_id(self, conn) -> None:
        short = _user(conn, "Stores", keywords=["TIENDA"])
        long = _user(conn, "Online", keywords=["TIENDA ONLINE"])
        assert _by_description(conn, "TIENDA ONLINE SEATTLE").ref == long.ref
        first = _user(conn, "First", keywords=["CAFE"])
        _user(conn, "Second", keywords=["CAFE"])
        assert _by_description(conn, "CAFE FICTICIO").ref == first.ref
        assert short.id < long.id

    def test_bank_keyword_only_when_the_kind_fits_the_direction(self, conn) -> None:
        _user(conn, "Odd expense", keywords=["TRANSFERENCIA RECIBIDA"])
        assert _by_description(conn, "TRANSFERENCIA RECIBIDA").ref == cat.OTHER_INCOME
        rent = _user(conn, "Rentals", "income", keywords=["TRANSFERENCIA"])
        assert _by_description(conn, "TRANSFERENCIA RECIBIDA").ref == rent.ref
        assert _by_description(conn, "TRANSFERENCIA RECIBIDA").kind == "income"

    def test_preview_catalog_does_not_touch_the_base(self, conn) -> None:
        made = _user(conn, "Pharmacy")
        proposed = catalog.load(conn).with_keywords(made.id, ["farmacia"])
        moved = next(
            m for m in spending.load_all(conn, HOLDERS, proposed) if m.description[:8] == "FARMACIA"
        )
        assert moved.ref == made.ref
        assert _by_description(conn, "FARMACIA INVENTADA").ref == cat.OTHER
