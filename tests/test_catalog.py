from datetime import date
from decimal import Decimal

import pytest

from finanzas import db
from finanzas.analysis import catalog, corrections, one_offs, spending
from finanzas.analysis import categories as cat
from finanzas.analysis.spending import Movement
from finanzas.web import summary
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


def _user(conn, name: str, kind: str = "gasto", keywords=()) -> catalog.Category:
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
            "gasto",
        )
        assert known.by_ref(cat.THIRD_PARTY).kind == "transferencia"

    def test_by_name_reads_old_and_birth_names(self, conn) -> None:
        with conn:
            catalog.update(conn, _id(conn, cat.GROCERIES), name="Súper")
        known = catalog.load(conn)
        assert known.by_name("súper").ref == cat.GROCERIES  # sin mayúsculas ni acentos exactos
        assert known.by_name("Supermercado").ref == cat.GROCERIES  # enlace viejo
        assert known.by_name("Efectivo y transferencias").ref == cat.CASH
        assert known.by_name("Inventada") is None

    def test_user_categories_go_after_the_builtins_of_their_kind(self, conn) -> None:
        made = _user(conn, "Mantenimiento del vehículo")
        income = _user(conn, "Alquileres", "ingreso")
        refs = [c.ref for c in catalog.load(conn).items]
        assert refs.index(made.ref) == len(cat.EXPENSES)
        assert refs.index(income.ref) == len(cat.EXPENSES) + 1 + len(cat.INCOME)
        assert made.ref == f"user:{made.id}"

    def test_duplicate_names_are_rejected_ignoring_case_and_accents(self, conn) -> None:
        with pytest.raises(catalog.DuplicateName):
            catalog.create(conn, "vehiculo y COMBUSTIBLE", "gasto")
        made = _user(conn, "Taller")
        with pytest.raises(catalog.DuplicateName):
            catalog.update(conn, _id(conn, cat.OTHER), name="taller")
        catalog.update(conn, made.id, name="Taller")  # su propio nombre sí

    def test_invalid_input(self, conn) -> None:
        with pytest.raises(catalog.CategoryError, match="tipo"):
            catalog.create(conn, "X", "ahorro")
        with pytest.raises(catalog.CategoryError, match="color"):
            catalog.create(conn, "X", "gasto", "rojo")
        with pytest.raises(catalog.CategoryError, match="vacío"):
            catalog.create(conn, "   ", "gasto")
        with pytest.raises(catalog.CategoryError, match="palabra clave"):
            catalog.set_keywords(conn, _id(conn, cat.OTHER), ["--"])
        with pytest.raises(catalog.NotFound):
            catalog.update(conn, 9999, name="Nada")

    def test_builtins_cannot_change_kind_or_be_deleted(self, conn) -> None:
        loans = _id(conn, cat.LOANS)
        with pytest.raises(catalog.Forbidden):
            catalog.update(conn, loans, kind="transferencia")
        with pytest.raises(catalog.Forbidden):
            catalog.delete(conn, loans, _id(conn, cat.OTHER))
        with conn:
            changed = catalog.update(
                conn, loans, name="Deudas", color="#1F6F5C", hidden=True, kind="gasto"
            )
        assert (changed.name, changed.color, changed.hidden) == ("Deudas", "#1F6F5C", True)
        with conn:
            assert catalog.update(conn, loans, color=None).color is None

    def test_keywords_are_normalized_like_descriptions(self, conn) -> None:
        made = _user(conn, "Taller", keywords=["  taller ", "Mecánica-Rápida", "TALLER"])
        assert catalog.load(conn).by_id(made.id).keywords == ("TALLER", "MECANICA RAPIDA")


class TestRename:
    def test_rename_keeps_corrections(self, conn) -> None:
        cafe = _by_description(conn, "CAFE FICTICIO")
        with conn:
            corrections.set_transaction_category(conn, cafe.fingerprint, cat.GROCERIES)
            corrections.set_merchant_category(conn, "FARMACIA INVENTADA", cat.HEALTH)
            catalog.update(conn, _id(conn, cat.GROCERIES), name="Súper")
            catalog.update(conn, _id(conn, cat.HEALTH), name="Médico")
        fixed = _by_description(conn, "CAFE FICTICIO")
        assert (fixed.category, fixed.ref, fixed.corrected) == ("Súper", cat.GROCERIES, True)
        assert fixed.original_category == cat.RESTAURANTS
        assert _by_description(conn, "FARMACIA INVENTADA").category == "Médico"

    def test_builtin_logic_survives_renaming_the_builtins(self, conn) -> None:
        with conn:
            for ref in (cat.CARD_PAYMENT, cat.OWN_TRANSFER, cat.OTHER_INCOME, cat.THIRD_PARTY):
                catalog.update(conn, _id(conn, ref), name=f"{ref} (mío)")
        payment = _by_description(conn, "SU PAGO GRACIAS")
        assert (payment.ref, payment.kind, payment.category) == (
            cat.CARD_PAYMENT,
            "transferencia",
            "Pago de tarjeta (mío)",
        )
        bank = _by_description(conn, "PAGO DE TC")  # emparejado con el pago de la tarjeta
        assert (bank.ref, bank.kind) == (cat.CARD_PAYMENT, "transferencia")
        income = _by_description(conn, "TRANSFERENCIA RECIBIDA")
        assert (income.ref, income.kind) == (cat.OTHER_INCOME, "ingreso")

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

        sent = move(cat.THIRD_PARTY, "Envíos", "700")
        assert summary._third_party([sent], {}, "2026-01") == Decimal(700)
        # Préstamos nunca se sugiere como gasto único, se llame como se llame.
        loan = move(cat.LOANS, "Deudas", "90000")
        found = one_offs.suggest([loan], "2026-01", rate_for_month=lambda _: None, dismissed=())
        assert found == []


class TestDelete:
    def test_delete_reassigns_corrections_and_keywords(self, conn) -> None:
        made = _user(conn, "Farmacia", keywords=["FARMACIA"])
        cafe = _by_description(conn, "CAFE FICTICIO")
        with conn:
            corrections.set_transaction_category(conn, cafe.fingerprint, made.id)
            corrections.set_merchant_category(conn, "TIENDA ONLINE", made.ref)
        assert _by_description(conn, "FARMACIA INVENTADA").category == "Farmacia"
        with pytest.raises(catalog.Forbidden, match="elige"):
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
        made = _user(conn, "Vacía")
        with conn:
            catalog.delete(conn, made.id, None)
        assert catalog.load(conn).by_id(made.id) is None

    def test_target_must_exist_and_differ(self, conn) -> None:
        made = _user(conn, "Farmacia", keywords=["FARMACIA"])
        with pytest.raises(catalog.Forbidden):
            catalog.delete(conn, made.id, made.id)
        with pytest.raises(catalog.NotFound):
            catalog.delete(conn, made.id, 9999)


class TestKeywords:
    def test_keywords_move_past_movements(self, conn) -> None:
        made = _user(conn, "Farmacia", keywords=["FARMACIA"])
        pharmacy = _by_description(conn, "FARMACIA INVENTADA")
        assert (pharmacy.category, pharmacy.ref, pharmacy.kind) == ("Farmacia", made.ref, "gasto")
        assert not pharmacy.corrected
        assert pharmacy.original_category == "Farmacia"

    def test_keyword_beats_builtin_rules_and_mcc(self, conn) -> None:
        made = _user(conn, "Colmados", keywords=["COLMADO"])
        assert _by_description(conn, "COLMADO INVENTADO").ref == made.ref  # MCC de supermercado

    def test_whole_words_only(self, conn) -> None:
        _user(conn, "Raro", keywords=["COLMA"])
        assert _by_description(conn, "COLMADO INVENTADO").ref == cat.GROCERIES

    def test_correction_beats_keyword(self, conn) -> None:
        _user(conn, "Colmados", keywords=["COLMADO"])
        colmado = _by_description(conn, "COLMADO INVENTADO")
        with conn:
            corrections.set_transaction_category(conn, colmado.fingerprint, cat.HOME)
        assert _by_description(conn, "COLMADO INVENTADO").ref == cat.HOME
        with conn:
            corrections.set_transaction_category(conn, colmado.fingerprint, None)
            corrections.set_merchant_category(conn, colmado.merchant, cat.HEALTH)
        assert _by_description(conn, "COLMADO INVENTADO").ref == cat.HEALTH

    def test_detected_transfer_beats_keyword(self, conn) -> None:
        _user(conn, "Pagos", keywords=["PAGO", "SU PAGO GRACIAS"])
        assert _by_description(conn, "SU PAGO GRACIAS").ref == cat.CARD_PAYMENT
        assert _by_description(conn, "PAGO DE TC").ref == cat.CARD_PAYMENT

    def test_longest_keyword_wins_and_ties_go_to_the_lower_id(self, conn) -> None:
        short = _user(conn, "Tiendas", keywords=["TIENDA"])
        long = _user(conn, "En línea", keywords=["TIENDA ONLINE"])
        assert _by_description(conn, "TIENDA ONLINE SEATTLE").ref == long.ref
        first = _user(conn, "Primera", keywords=["CAFE"])
        _user(conn, "Segunda", keywords=["CAFE"])
        assert _by_description(conn, "CAFE FICTICIO").ref == first.ref
        assert short.id < long.id

    def test_bank_keyword_only_when_the_kind_fits_the_direction(self, conn) -> None:
        _user(conn, "Gasto raro", keywords=["TRANSFERENCIA RECIBIDA"])
        assert _by_description(conn, "TRANSFERENCIA RECIBIDA").ref == cat.OTHER_INCOME
        rent = _user(conn, "Alquileres", "ingreso", keywords=["TRANSFERENCIA"])
        assert _by_description(conn, "TRANSFERENCIA RECIBIDA").ref == rent.ref
        assert _by_description(conn, "TRANSFERENCIA RECIBIDA").kind == "ingreso"

    def test_preview_catalog_does_not_touch_the_base(self, conn) -> None:
        made = _user(conn, "Farmacia")
        proposed = catalog.load(conn).with_keywords(made.id, ["farmacia"])
        moved = next(
            m for m in spending.load_all(conn, HOLDERS, proposed) if m.description[:8] == "FARMACIA"
        )
        assert moved.ref == made.ref
        assert _by_description(conn, "FARMACIA INVENTADA").ref == cat.OTHER
