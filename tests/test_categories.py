import pytest

from michelito.analysis import categories as cat


@pytest.mark.parametrize(
    "description",
    [
        "33333333333333333333333 SU PAGO GRACIAS",
        "1234567890 Pago Via Internet",  # spanish-data
        "PAGO DEBITO A CUENTA MBP",
        "PAGO ACH BANCO INVENTADO",
        "PAGO LBTR",
    ],
)
def test_payments_are_recognized(description: str) -> None:
    assert cat.is_payment(description)


@pytest.mark.parametrize(
    "description",
    ["66666666666666666666666 DEVOLUCION", "AMZN Mktp US", "1234567890 CR Interes"],
)
def test_refunds_are_not_payments(description: str) -> None:
    assert not cat.is_payment(description)


@pytest.mark.parametrize(
    ("description", "key"),
    [
        ("UBER *EATS SANTO DOMINGO-DO", "UBER EATS"),
        ("UBER EATS SANTO DOMINGO", "UBER EATS"),
        ("Pedidos Ya 12345", "PEDIDOS YA"),
        ("11111111111111111111111 COLMADO INVENTADO SANTO DOMINGO", "COLMADO INVENTADO"),
        ("Comisión Trans", "COMISION TRANS"),  # spanish-data
        ("1234", "SIN DESCRIPCION"),
    ],
)
def test_merchant_key(description: str, key: str) -> None:
    assert cat.merchant_key(description) == key


@pytest.mark.parametrize(
    ("mcc", "category"),
    [
        ("5411", cat.GROCERIES),
        ("5814", cat.RESTAURANTS),
        ("3174", cat.TRAVEL),  # airline, range 3000-3299
        ("3600", cat.TRAVEL),  # hotel, range 3501-3999
        ("5541", cat.VEHICLE),
        ("0001", None),
        (None, None),
    ],
)
def test_category_for_mcc(mcc: str | None, category: str | None) -> None:
    assert cat.category_for_mcc(mcc) == category


def test_bank_fees_without_mcc() -> None:
    # Bank fees never carry an MCC; a merchant with an MCC is not a fee.
    assert cat.categorize("1234567890 Interes Financiamiento", None, {}) == cat.BANK_FEES
    assert cat.categorize("INTERES GOURMET", "5411", {}) == cat.GROCERIES
    assert cat.categorize("COMISION X MORA", None, {}) == cat.BANK_FEES
    assert cat.categorize("1234567890 CR Interes", None, {}) == cat.BANK_FEES


def test_keyword_rules_win_over_mcc() -> None:
    # Uber Eats comes with a restaurant MCC, but it is delivery.
    assert cat.categorize("UBER *EATS SANTO DOMINGO", "5812", {}) == cat.DELIVERY
    assert cat.categorize("UBER *TRIP", "4121", {}) == cat.TRANSPORT


def test_mcc_then_learned_merchant_then_other() -> None:
    learned = {"TIENDA ONLINE": cat.BOOKS}
    assert cat.categorize("COLMADO INVENTADO", "5411", learned) == cat.GROCERIES
    assert cat.categorize("TIENDA ONLINE SEATTLE-US", None, learned) == cat.BOOKS
    assert cat.categorize("COMERCIO DESCONOCIDO", None, learned) == cat.OTHER


def test_learn_merchants_takes_the_most_common_category() -> None:
    learned = cat.learn_merchants(
        [
            ("TIENDA ONLINE SEATTLE", "5942"),
            ("TIENDA ONLINE MIAMI", "5942"),
            ("TIENDA ONLINE", "5411"),
            ("SIN CODIGO", None),
            ("CODIGO RARO", "0001"),
        ]
    )
    assert learned == {"TIENDA ONLINE": cat.BOOKS}


@pytest.mark.parametrize(
    ("description", "key"),
    [
        ("AMZN Mktp US", "AMAZON"),
        ("AMAZON MARK* 123", "AMAZON"),
        ("UBR* PENDING.UBER.COM", "UBER VIAJES"),
        ("UBER *TRIP", "UBER VIAJES"),
        ("PEDIDOSYA SUCURSAL FICTICIA", "PEDIDOS YA"),
        ("WM SUPERCENTER #123", "WALMART"),
        ("AMERICAN0012345678901 MADRID", "AMERICAN MADRID"),  # letters and digits run together
    ],
)
def test_merchant_aliases(description: str, key: str) -> None:
    assert cat.merchant_key(description) == key


@pytest.mark.parametrize(
    ("description", "category"),
    [
        ("RESTAURANT FICTICIO", cat.RESTAURANTS),
        ("PIZZA FICTICIA SANTO DOMINGO", cat.RESTAURANTS),
        ("CARDNET PEAJES", cat.TRANSPORT),
        ("LUBRICENTRO FICTICIO", cat.VEHICLE),
        ("ELECTRODOM SD", cat.HOME),
        ("PEDIDOSYA SUCURSAL FICTICIA", cat.DELIVERY),
        ("AMERICAN0012345678901 MADRID", cat.TRAVEL),
        ("DEV. AMAZON", cat.ONLINE),  # the refund goes to the merchant's category
        ("66666666666666666666666 DEVOLUCION", cat.OTHER),
    ],
)
def test_fallback_keywords(description: str, category: str) -> None:
    assert cat.categorize(description, None, {}) == category


def test_mcc_wins_over_fallback_keywords() -> None:
    # "CAFE" suggests a restaurant, but the merchant's MCC wins.
    assert cat.categorize("CAFE TIENDA GOURMET", "5411", {}) == cat.GROCERIES


@pytest.mark.parametrize(
    ("mcc", "category"),
    [("6513", cat.HOUSING), ("0742", cat.PETS), ("7995", cat.ENTERTAINMENT), ("4829", cat.CASH)],
)
def test_more_mcc_codes(mcc: str, category: str) -> None:
    assert cat.category_for_mcc(mcc) == category


def test_refund_groups_with_its_merchant() -> None:
    assert cat.merchant_key("DEV. AMAZON") == "AMAZON"
    assert cat.merchant_key("1234567890 Dev. Ficticiomatic") == "FICTICIOMATIC"


@pytest.mark.parametrize(
    ("description", "mcc", "category"),
    [
        ("PUMA STORE PLAZA FICTICIA", "5651", cat.SHOPPING),
        ("TOTAL VINOS FICTICIOS", "5921", cat.GROCERIES),
        ("DISNEY TICKETS FICTICIOS", "7996", cat.ENTERTAINMENT),
        ("GOOGLE ADS", "7311", cat.PROFESSIONAL),
        ("CLAUDES CAFE FICTICIO", "5812", cat.RESTAURANTS),
        ("MORA FICTICIA", "5812", cat.RESTAURANTS),
        ("CARGO EXPRESS COURIER", None, cat.OTHER),
    ],
)
def test_ambiguous_names_defer_to_mcc(description: str, mcc: str | None, category: str) -> None:
    assert cat.categorize(description, mcc, {}) == category


def test_ambiguous_brands_still_apply_without_mcc() -> None:
    assert cat.categorize("TOTALENERGIES FICTICIA", None, {}) == cat.VEHICLE
    assert cat.categorize("GOOGLE *YouTubePremium", None, {}) == cat.SUBSCRIPTIONS
    assert cat.categorize("CARGO COBERTURA DE SEGURO", None, {}) == cat.BANK_FEES


@pytest.mark.parametrize(
    ("category", "kind"),
    [
        (cat.GROCERIES, "expense"),
        (cat.OTHER, "expense"),
        (cat.SALARY, "income"),
        (cat.SERVICE_PAYMENTS, "income"),
        (cat.CRYPTO, "transfer"),  # crypto <-> fiat: neither income nor spending
        (cat.OTHER_INCOME, "income"),
        (cat.CARD_PAYMENT, "transfer"),
        (cat.OWN_TRANSFER, "transfer"),
        (cat.THIRD_PARTY, "transfer"),
        (cat.LOANS, "expense"),
        (cat.INSURANCE, "expense"),
        ("Made-up category", "expense"),
    ],
)
def test_kind_of(category: str, kind: str) -> None:
    assert cat.kind_of(category) == kind


def test_all_lists_expenses_then_income_then_transfers() -> None:
    # There used to be 6 fixed ones; the third-party transfers category adds one more.
    tail = len(cat.INCOME) + len(cat.TRANSFER)
    assert cat.ALL[-tail:] == (*cat.INCOME, *cat.TRANSFER)
    assert [cat.kind_of(c) for c in cat.ALL[:-tail]] == ["expense"] * (len(cat.ALL) - tail)
    assert set(cat.KIND_OF) == set(cat.ALL)


@pytest.mark.parametrize(
    ("description", "promotion"),
    [
        ("CR PROMOCION INVENTADA", True),
        ("CASHBACK MENSUAL", True),
        ("REEMBOLSO PROMO NAVIDAD", True),
        ("1234567890 CR BONO DE BIENVENIDA", True),
        ("CREDITO BONO NAVIDAD", True),
        ("CR. BONO", True),
        ("BONO SPA", False),
        ("CR DEVOLUCION BONO", False),
        ("Promoción Black Friday", True),  # spanish-data
        ("DEV TIENDA ONLINE", False),
        ("ABONO A CUENTA", False),
        ("66666666666666666666666 DEVOLUCION", False),
    ],
)
def test_promotion_credits(description: str, promotion: bool) -> None:
    assert cat.is_promotion(description) is promotion


class TestBankDebits:
    """A bank debit is not an expense unless a rule recognizes it."""

    @pytest.mark.parametrize(
        ("text", "category"),
        [
            ("PAGO IMPUESTO 0.15% DGII INVENTADO", cat.GOVERNMENT),
            ("RETENCION ISR INVENTADA", cat.GOVERNMENT),
            ("COMISION MANEJO DE CUENTA", cat.BANK_FEES),
            ("CARGO POR SERVICIO", cat.BANK_FEES),
            ("EXI COMISIONES INVENTADAS", cat.BANK_FEES),
            ("INTERES SOBREGIRO", cat.BANK_FEES),
            ("BANCASEGURO INVENTADO", cat.INSURANCE),
            ("PAGO SEGURO DE VIDA FICTICIO", cat.INSURANCE),
            ("RETIRO CAJERO INVENTADO", cat.CASH),
            ("CONSUMO ATM 123", cat.CASH),
            ("COD CASH 0001 INVENTADO", cat.CASH),
            ("CASH ADVANCE INVENTADO", cat.CASH),
            ("AUT PAGO 0000000009 INVENTADO", cat.LOANS),
            ("PAGO PRESTAMO PERSONAL", cat.LOANS),
            ("MB a 0000000001 PERSONA INVENTADA", cat.THIRD_PARTY),
            ("TOKE a 0000000001 PERSONA INVENTADA", cat.THIRD_PARTY),
            ("LBTR/IB/ VIA LBTR 0000000002 OTRO BANCO", cat.THIRD_PARTY),
            ("NETFLIX COM", cat.THIRD_PARTY),
            ("ALGO DESCONOCIDO", cat.THIRD_PARTY),
        ],
    )
    def test_rules(self, text: str, category: str) -> None:
        assert cat.categorize_bank(text, "debit") == category

    def test_card_merchant_rules_do_not_apply_to_debits(self) -> None:
        assert cat.categorize_bank("UBER EATS INVENTADO", "debit") == cat.THIRD_PARTY

    def test_cash_word_inside_the_text_is_not_cash(self) -> None:
        assert cat.categorize_bank("MB a 001 CASHFICTICIO TIENDA", "debit") == cat.THIRD_PARTY


class TestBankCredits:
    @pytest.mark.parametrize(
        ("text", "category"),
        [
            ("PAGO DE NOMINAS EMPRESA FICTICIA", cat.SALARY),
            ("PAGO DE NOMINA EMPRESA FICTICIA", cat.SALARY),
            ("REEMBOLSO MAPFRE INVENTADO", cat.HEALTH),
            ("TRANSF HUMANO SEGUROS", cat.HEALTH),
            ("SENASA REEMBOLSO", cat.HEALTH),
            ("PALIC SALUD", cat.HEALTH),
            # Formerly Health: UNIVERSAL and HUMANO alone are common names; they need ARS or SEGURO.
            ("UNIVERSAL ASISTENCIA", cat.OTHER_INCOME),
            ("DEP ARS UNIVERSAL", cat.HEALTH),
            ("UNIVERSAL SEGUROS INVENTADO", cat.HEALTH),
            ("HUMANO INVENTADO", cat.OTHER_INCOME),
            ("TRANSFERENCIA DE UNIVERSAL DE FICTICIOS SRL", cat.OTHER_INCOME),
            ("REEMBOLSO GASTOS VIAJE EMPRESA", cat.OTHER_INCOME),
            ("REEMBOLSO MAPFRE SALUD", cat.HEALTH),
            ("REEMBOLSO ARS INVENTADA", cat.HEALTH),
            ("REEMBOLSO SEGURO MEDICO", cat.HEALTH),
            ("REEMBOLSO SALUD FICTICIO", cat.HEALTH),
            ("MB desde 000000003 PERSONA", cat.OTHER_INCOME),  # spanish-data
            ("RETIRO ANULADO", cat.OTHER_INCOME),
        ],
    )
    def test_rules(self, text: str, category: str) -> None:
        assert cat.categorize_bank(text, "credit") == category

    def test_nominal_is_not_payroll(self) -> None:
        assert cat.categorize_bank("VALOR NOMINAL", "credit") == cat.OTHER_INCOME


def test_cash_category_name_and_the_old_name_maps_to_it() -> None:
    assert cat.CASH == "Efectivo"  # spanish-ui
    assert cat.canonical("Efectivo y transferencias") == cat.CASH  # spanish-data
    assert cat.canonical(cat.GROCERIES) == cat.GROCERIES


class TestBankMerchantKey:
    """A bank account's merchant key is the counterpart, not the channel."""

    @pytest.mark.parametrize(
        ("description", "key"),
        [
            ("MB a 0123456789 JUAN PEREZ", "MB A 0123456789"),
            ("MB desde 000000003 FULANO DE", "MB DESDE 000000003"),  # spanish-data
            ("MB a JUAN PEREZ D BANCO", "MB A JUAN PEREZ"),  # no number: the name
            ("TOKE a NOMBRE APELLIDO", "TOKE A NOMBRE APELLIDO"),
            ("TOKE de NOMBRE APELLIDO OTRO", "TOKE DE NOMBRE APELLIDO"),  # spanish-data
            ("TOKE a 0000000001 PERSONA INVENTADA", "TOKE A PERSONA INVENTADA"),
            ("TOKE a 0000000001", "TOKE A 0000000001"),
            (
                "LBTR/IB/ VIA LBTR 0088001234567 NOMBRE APELLIDO BANCO X",
                "LBTR NOMBRE APELLIDO",
            ),
            ("LBTR 1234567890 NOMBRE", "LBTR NOMBRE"),
            ("LBTR/IB/ VIA LBTR 0088001234567", "LBTR 0088001234567"),
            ("AUT PAGO 1234567890 123-45678", "AUT PAGO 1234567890"),
            ("TRNFUSD9,999.99ACME, INC.9.99 USD99.99", "TRNFUSD ACME INC"),
            ("PAGO IMPUESTO 0.15 DGII INVENTADO", "PAGO IMPUESTO DGII"),
            ("PAGO DE NOMINAS EMPRESA FICTICIA", "PAGO NOMINAS EMPRESA"),
            ("Depósito  Cliente", "DEPOSITO CLIENTE"),  # spanish-data
            ("DEV LBTR E123456.ADEV1234CAS", "DEV LBTR"),
            ("1234", "SIN DESCRIPCION"),
            # No particles or single letters in the counterpart's name.
            ("TOKE DE MARIA DE LA CRUZ", "TOKE DE MARIA CRUZ"),
            ("TOKE DE MARIA DE LEON", "TOKE DE MARIA LEON"),
            ("LBTR 1234567890 NOMBRE A", "LBTR NOMBRE"),
            ("TOKE a/de JUAN PEREZ", "TOKE A DE JUAN PEREZ"),  # spanish-data
            # An account number has at least 6 digits; a short one is not the counterpart.
            ("MB a 001 MARIA PEREZ", "MB A MARIA PEREZ"),
            ("AUT PAGO 12345 PRESTAMO FICTICIO", "AUT PAGO PRESTAMO FICTICIO"),
            ("LBTR 12345 678901 NOMBRE", "LBTR NOMBRE"),
            # Months and years are not part of the merchant.
            ("CUOTA ENERO 2026 CLUB FICTICIO", "CUOTA CLUB FICTICIO"),
            ("PAGO SEPT2025 ALQUILER LOCAL", "PAGO ALQUILER LOCAL"),
            ("MANTENIMIENTO DIC 2025 EDIFICIO", "MANTENIMIENTO EDIFICIO"),
        ],
    )
    def test_keys(self, description: str, key: str) -> None:
        assert cat.bank_merchant_key(description) == key

    @pytest.mark.parametrize(
        "descriptions",
        [
            ("MB a 0123456789 JUAN PEREZ", "MB a 0123456789 JUAN PER", "MB A 0123456789"),
            # "FULANO DE TA" and "FULANO DE TAL" used to give the same key ("LBTR FULANO DE");
            # without particles a truncated name no longer matches, so use the same cut each month.
            (
                "LBTR/IB/ VIA LBTR 0088001234567 FULANO DE TAL BANCO BHD",
                "LBTR/IB/ VIA LBTR 0088009999999 FULANO DE TAL BANCO POPULAR",
            ),
            ("AUT PAGO 1234567890 123-45678", "AUT PAGO 1234567890 123-45999"),
            (
                "TRNFUSD9,999.99ACME, INC.9.99 USD99.99",
                "TRNFUSD1,234.56ACME, INC.1.23 USD12.34",
            ),
            ("PAGO IMPUESTO 0.15 DGII 12345", "PAGO IMPUESTO 0.15 DGII 67890"),
            ("DEV LBTR E123456.ADEV1234CAS", "DEV LBTR E999999.ADEV5555XYZ"),
        ],
    )
    def test_same_counterpart_same_key_month_to_month(self, descriptions: tuple[str, ...]) -> None:
        assert len({cat.bank_merchant_key(d) for d in descriptions}) == 1

    def test_different_counterparts_get_different_keys(self) -> None:
        keys = {
            cat.bank_merchant_key("MB a 0123456789 JUAN PEREZ"),
            cat.bank_merchant_key("MB a 0999999999 MARIA GOMEZ"),
            cat.bank_merchant_key("TOKE a JUAN PEREZ"),
            cat.bank_merchant_key("TOKE a MARIA GOMEZ"),
            cat.bank_merchant_key("LBTR 1234567890 JUAN PEREZ"),
            cat.bank_merchant_key("LBTR 1234567890 MARIA GOMEZ"),
        }
        assert len(keys) == 6

    def test_card_key_is_unchanged(self) -> None:
        # Cards keep using `merchant_key`: two words.
        assert cat.merchant_key("MB a 0123456789 JUAN PEREZ") == "MB A"
        assert cat.merchant_key("COLMADO INVENTADO SANTO DOMINGO") == "COLMADO INVENTADO"


class TestBankReversals:
    def test_unpaired_reversal_credit_is_a_third_party_refund(self) -> None:
        assert cat.categorize_bank("DEV LBTR E123456.ADEV1234CAS", "credit") == cat.THIRD_PARTY

    @pytest.mark.parametrize(
        ("text", "category"),
        [
            ("DEV COMISION MANEJO DE CUENTA", cat.BANK_FEES),
            ("DEV IMPUESTO 0.15% DGII", cat.GOVERNMENT),
            ("DEV CARGO POR SERVICIO", cat.BANK_FEES),
            ("DEV RETIRO CAJERO", cat.CASH),
            ("DEV MB a 0123456789 JUAN PEREZ", cat.THIRD_PARTY),
        ],
    )
    def test_unpaired_reversal_follows_the_debit_rules(self, text: str, category: str) -> None:
        # Without its debit, the reversal of a fee or a tax subtracts from that category.
        assert cat.categorize_bank(text, "credit") == category

    def test_dev_word_inside_is_not_a_reversal(self) -> None:
        incoming = "MB desde 0001 DEVANA PEREZ"  # spanish-data
        assert cat.categorize_bank(incoming, "credit") == cat.OTHER_INCOME

    def test_is_reversal(self) -> None:
        assert cat.is_reversal("DEV LBTR E123456.ADEV1234CAS")
        assert cat.is_reversal("dev. comision")
        assert not cat.is_reversal("DEVANA PEREZ")
        assert not cat.is_reversal("MB a 001 DEV")


class TestBanreservasShapes:
    """Banreservas descriptions (the row and the counterpart lines joined)."""

    @pytest.mark.parametrize(
        ("text", "direction", "category"),
        [
            ("COBRO IMP DGII 0.15%_IMPUESTO INV", "debit", cat.GOVERNMENT),
            ("COMISION PAGO AL INSTANTE BCRD", "debit", cat.BANK_FEES),
            ("TRANSFERENCIA A MENGANO INVENTADO PEREZ", "debit", cat.THIRD_PARTY),
            ("PAGOS AL INSTANTE BCRD A ZUTANO FICTICIO RODRIGUEZ", "debit", cat.THIRD_PARTY),
            ("TRANSFERENCIA", "debit", cat.THIRD_PARTY),
            ("TRANSFERENCIA DE PERSONA INVENTADA OTRO APELLIDO", "credit", cat.OTHER_INCOME),
            ("PAGO INTERES INVENTADO", "credit", cat.OTHER_INCOME),
        ],
    )
    def test_categories(self, text: str, direction: str, category: str) -> None:
        assert cat.categorize_bank(text, direction) == category

    @pytest.mark.parametrize(
        ("description", "key"),
        [
            ("TRANSFERENCIA A MENGANO INVENTADO PEREZ", "TRANSFERENCIA A MENGANO INVENTADO"),
            ("TRANSFERENCIA DE PERSONA DE LA CRUZ OTRO", "TRANSFERENCIA DE PERSONA CRUZ"),
            (
                "PAGOS AL INSTANTE BCRD A ZUTANO FICTICIO RODRIGUEZ",
                "PAGOS AL INSTANTE BCRD A ZUTANO FICTICIO",
            ),
            ("COBRO IMP DGII 0.15%_IMPUESTO INV", "COBRO IMP DGII"),
            ("COMISION PAGO AL INSTANTE BCRD", "COMISION PAGO INSTANTE"),
            ("TRANSFERENCIA", "TRANSFERENCIA"),
        ],
    )
    def test_keys(self, description: str, key: str) -> None:
        assert cat.bank_merchant_key(description) == key

    def test_sent_and_received_get_different_keys(self) -> None:
        sent = cat.bank_merchant_key("TRANSFERENCIA A MENGANO INVENTADO")
        received = cat.bank_merchant_key("TRANSFERENCIA DE MENGANO INVENTADO")
        instant = cat.bank_merchant_key("PAGOS AL INSTANTE BCRD A MENGANO INVENTADO")
        assert len({sent, received, instant}) == 3

    def test_different_counterparts_get_different_keys(self) -> None:
        assert cat.bank_merchant_key("PAGOS AL INSTANTE BCRD A MENGANO INVENTADO") != (
            cat.bank_merchant_key("PAGOS AL INSTANTE BCRD A ZUTANO FICTICIO")
        )


@pytest.mark.parametrize(
    ("description", "previous"),
    [
        ("TRANSFERENCIA DE UNIVERSAL DE FICTICIOS SRL", "TRANSFERENCIA UNIVERSAL FICTICIOS"),
        ("TRANSFERENCIA A CUENTA PROPIA", "TRANSFERENCIA CUENTA PROPIA"),
        ("PAGOS AL INSTANTE BCRD A ZUTANO FICTICIO", "PAGOS INSTANTE BCRD"),
        ("MB a 0123456789 JUAN PEREZ", "MB A 0123456789"),  # unchanged
    ],
)
def test_previous_bank_key_is_the_one_before_the_banreservas_channels(
    description: str, previous: str
) -> None:
    assert cat.previous_bank_key(description) == previous
