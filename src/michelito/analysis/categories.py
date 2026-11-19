"""Sorting card transactions into spending categories.

Decision order (most to least precise):
1. Bank charges (interest, late fees, commissions), by keyword.
2. Keyword rules for merchants whose MCC is misleading (Uber Eats arrives
   as a restaurant, Amazon as a bookstore).
3. The MCC (merchant category code) that Popular prints.
4. The category learned from the same merchant in transactions that have an MCC: BHD
   does not print the MCC, but many merchants show up on both cards.
5. Fallback rules on generic words ("RESTAURANT", "PEAJES"): less reliable than the MCC,
   so they come after it.
6. `OTHER`.

A card credit that is a promotion, cashback or bonus (`is_promotion`) is `OTHER_INCOME`;
`spending` decides that, since it knows the direction.

A refund ("DEV. AMAZON") is categorized like the merchant giving the refund.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Literal

from michelito.i18n import t
from michelito.parsers.common import CREDIT, normalize

# System category names: the names each built-in category is born with. They are stored
# data (`categories.name`, corrections, merchant rules) and the reference the analysis compares
# against (`BUILTIN_KEYS`, `catalog.Category.ref`), so their values never change.
# spanish-data: begin
GROCERIES = "Supermercado"
RESTAURANTS = "Restaurantes"
DELIVERY = "Delivery"
TRANSPORT = "Transporte"
VEHICLE = "Vehículo y combustible"
TRAVEL = "Viajes"
ONLINE = "Compras en línea"
COURIER = "Courier"
BOOKS = "Libros"
SUBSCRIPTIONS = "Suscripciones digitales"
UTILITIES = "Servicios (luz, teléfono)"
HEALTH = "Salud"
SHOPPING = "Ropa y tiendas"
HOME = "Hogar y electrónica"
ENTERTAINMENT = "Entretenimiento"
PERSONAL_CARE = "Cuidado personal"
INSURANCE = "Seguros"
GOVERNMENT = "Gobierno e impuestos"
EDUCATION = "Educación"
PROFESSIONAL = "Servicios profesionales"
CASH = "Efectivo"
HOUSING = "Vivienda"
PETS = "Mascotas"
BANK_FEES = "Cargos del banco"
LOANS = "Préstamos"
OTHER = "Otros"

SALARY = "Salario"
SERVICE_PAYMENTS = "Pagos por servicios"
CRYPTO = "Cripto"
OTHER_INCOME = "Otros ingresos"

CARD_PAYMENT = "Pago de tarjeta"
OWN_TRANSFER = "Entre mis cuentas"
THIRD_PARTY = "Transferencias a terceros"
REIMBURSEMENT = "Reembolso"
CURRENCY_EXCHANGE = "Cambio de divisas"
INVESTMENT = "Inversiones"
INVESTMENT_RETURN = "Rendimientos"
INVESTMENT_CAPITAL = "Devolución de capital"
CASH_BOX = "Caja fuerte"
# A former name that may still be stored in corrections -> its current name.
_LEGACY_NAMES = {"Efectivo y transferencias": CASH}
# spanish-data: end

# THIRD_PARTY: bank debits to other people. Not spending, but they reduce what you have left.
# REIMBURSEMENT: credits linked to a shared expense (`links`): they pay back part of that
# expense; they are not income.
# CURRENCY_EXCHANGE: transactions linked in a currency exchange with third parties (`links`):
# neither spending nor income.
# INVESTMENT, INVESTMENT_RETURN, INVESTMENT_CAPITAL (`links`, `analysis.investments`): a
# contribution is your money that stays yours (neither spending nor a reduction of what you
# have left); what it yields is income; the capital that comes back is not.
# CASH_BOX (`analysis.cash_box`): a withdrawal kept in the cash box or a deposit that came out
# of it. It is your money somewhere else: neither spending nor income, and it does not reduce
# what you have left.

# The categories that only their link sets (marking an investment or the cash box): they cannot be
# picked by hand, neither through a correction nor through keywords. INVESTMENT_RETURN can: any
# income may be one.
LINK_ONLY = (INVESTMENT, INVESTMENT_CAPITAL, CASH_BOX)

Kind = Literal["income", "expense", "transfer"]
# How each kind reads in the change log (display text).
KIND_LABELS: dict[str, str] = {
    "income": t("analysis.categories.kind_income"),
    "expense": t("analysis.categories.kind_expense"),
    "transfer": t("analysis.categories.kind_transfer"),
}

# Spending categories, in the order they are offered when correcting one by hand.
EXPENSES = (
    GROCERIES,
    RESTAURANTS,
    DELIVERY,
    TRANSPORT,
    VEHICLE,
    TRAVEL,
    ONLINE,
    COURIER,
    BOOKS,
    SUBSCRIPTIONS,
    UTILITIES,
    HEALTH,
    SHOPPING,
    HOME,
    ENTERTAINMENT,
    PERSONAL_CARE,
    INSURANCE,
    GOVERNMENT,
    EDUCATION,
    PROFESSIONAL,
    CASH,
    HOUSING,
    PETS,
    BANK_FEES,
    LOANS,
    OTHER,
)
INCOME = (SALARY, SERVICE_PAYMENTS, CRYPTO, OTHER_INCOME, INVESTMENT_RETURN)
TRANSFER = (
    CARD_PAYMENT,
    OWN_TRANSFER,
    THIRD_PARTY,
    REIMBURSEMENT,
    CURRENCY_EXCHANGE,
    INVESTMENT,
    INVESTMENT_CAPITAL,
    CASH_BOX,
)

# Every category: spending, then income, then transfers.
ALL = (*EXPENSES, *INCOME, *TRANSFER)

KIND_OF: dict[str, Kind] = {
    **dict.fromkeys(EXPENSES, "expense"),
    **dict.fromkeys(INCOME, "income"),
    **dict.fromkeys(TRANSFER, "transfer"),
}


# Stable identity of each system category (`categories.builtin_key` in the database) -> its
# reference in the analysis. The reference is the name it was born with and does not change
# when the user renames it: the logic compares against these constants, never against the
# displayed name (see `catalog`).
BUILTIN_KEYS: dict[str, str] = {
    "GROCERIES": GROCERIES,
    "RESTAURANTS": RESTAURANTS,
    "DELIVERY": DELIVERY,
    "TRANSPORT": TRANSPORT,
    "VEHICLE": VEHICLE,
    "TRAVEL": TRAVEL,
    "ONLINE": ONLINE,
    "COURIER": COURIER,
    "BOOKS": BOOKS,
    "SUBSCRIPTIONS": SUBSCRIPTIONS,
    "UTILITIES": UTILITIES,
    "HEALTH": HEALTH,
    "SHOPPING": SHOPPING,
    "HOME": HOME,
    "ENTERTAINMENT": ENTERTAINMENT,
    "PERSONAL_CARE": PERSONAL_CARE,
    "INSURANCE": INSURANCE,
    "GOVERNMENT": GOVERNMENT,
    "EDUCATION": EDUCATION,
    "PROFESSIONAL": PROFESSIONAL,
    "CASH": CASH,
    "HOUSING": HOUSING,
    "PETS": PETS,
    "BANK_FEES": BANK_FEES,
    "LOANS": LOANS,
    "OTHER": OTHER,
    "SALARY": SALARY,
    "SERVICE_PAYMENTS": SERVICE_PAYMENTS,
    "CRYPTO": CRYPTO,
    "OTHER_INCOME": OTHER_INCOME,
    "CARD_PAYMENT": CARD_PAYMENT,
    "OWN_TRANSFER": OWN_TRANSFER,
    "THIRD_PARTY": THIRD_PARTY,
    "REIMBURSEMENT": REIMBURSEMENT,
    "CURRENCY_EXCHANGE": CURRENCY_EXCHANGE,
    "INVESTMENT": INVESTMENT,
    "INVESTMENT_RETURN": INVESTMENT_RETURN,
    "INVESTMENT_CAPITAL": INVESTMENT_CAPITAL,
    "CASH_BOX": CASH_BOX,
}


def kind_of(category: str) -> Kind:
    """Kind of a category; an unknown one counts as an expense."""
    return KIND_OF.get(category, "expense")


def canonical(category: str) -> str:
    """Current name of a category stored under a former name."""
    return _LEGACY_NAMES.get(category, category)


_NO_DESCRIPTION = "SIN DESCRIPCION"
_KEY_WORDS = 2

# MCC codes per category, separated by spaces.
_MCC_CODES: dict[str, str] = {
    GROCERIES: "5411 5422 5441 5451 5462 5499 5921",
    RESTAURANTS: "5811 5812 5813 5814",
    TRANSPORT: "4111 4112 4121 4131 4784 4789",
    VEHICLE: "5172 5511 5521 5531 5533 5541 5542 7523 7531 7534 7538 7542 7549 5983",
    TRAVEL: "4411 4511 4582 4722 7011 7012 7512 7519",
    ONLINE: "5964 5965 5966 5967 5968 5969",
    COURIER: "4214 4215",
    BOOKS: "5192 5942 5994",
    SUBSCRIPTIONS: "4816 4899 5815 5816 5817 5818 7372",
    UTILITIES: "4812 4814 4900",
    HEALTH: "5912 5975 5976 8011 8021 8031 8041 8042 8043 8049 8050 8062 8071 8099 7277",
    SHOPPING: "5300 5309 5310 5311 5331 5399 5611 5621 5631 5641 5651 5655 5661 5691 5699 "
    "5944 5945 5947 5948 5977 5999 5941 5943",
    HOME: "5021 5045 5065 5200 5211 5231 5251 5261 5712 5713 5714 5718 5719 5722 5732 "
    "5733 5734 5735 1711",
    ENTERTAINMENT: "7832 7841 7922 7929 7932 7933 7941 7991 7992 7994 7996 7997 7998 7999 7995",
    PERSONAL_CARE: "7230 7297 7298 7299",
    INSURANCE: "5960 6300",
    GOVERNMENT: "9211 9222 9311 9399 9402",
    EDUCATION: "8211 8220 8241 8244 8249 8299",
    PROFESSIONAL: "7311 7392 8111 8931 8999 7321 7399 8699",
    CASH: "4829 6010 6011 6051",
    HOUSING: "6513",
    PETS: "0742",
}
_MCC_TABLE = {code: category for category, codes in _MCC_CODES.items() for code in codes.split()}
# Ranges reserved for brands: airlines, car rental and hotels.
_MCC_RANGES = ((3000, 3999, TRAVEL),)

# Bank charges. The common words ("MORA", "CARGO") only in their exact form, so merchants
# like "MORA FICTICIA" are not caught; never applies when there is an MCC.
_BANK_FEES = re.compile(
    r"^(CR )?(INTERES|INTERESES|COMISION)\b|^MORA$|^PROTECCION POR\b|^ITBIS\b"
    r"|^CARGO (COBERTURA|PARCIAL|RENOVACION|SOBREGIRO|POR)\b"
)
# Only unmistakable merchants whose MCC is misleading: they beat the MCC.
_KEYWORD_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), category)
    for pattern, category in (
        (r"\bUBER EATS\b|\bPEDIDOS ?YA\b|\bRAPPI\b|\bHUGO APP\b", DELIVERY),
        (r"\bUBER (TRIP|RIDES)\b|\bUBR PENDING\b|\bCABIFY\b|\bINDRIVE\b", TRANSPORT),
        (r"^(AMZN|AMAZON)\b|\bALIEXPRESS\b|\bTEMU\b|\bSHEIN\b|\bEBAY\b", ONLINE),
        (r"\bSPOTIFY\b|\bNETFLIX\b|\bYOUTUBE|\bOPENAI\b|\bCHATGPT\b|\bANTHROPIC\b", SUBSCRIPTIONS),
        (r"^(DOMEX|BM CARGO|ALDEAMO|MAILBOXES)\b", COURIER),
    )
)
# Generic words: only when neither the MCC nor the learned merchant decides.
_FALLBACK_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), category)
    for pattern, category in (
        (r"\bREST\b|\bRESTAURANT|\bPIZZ|\bSUSHI\b|\bBURGER|\bCAFE\b|\bGRILL\b", RESTAURANTS),
        (r"\bPEAJE", TRANSPORT),
        (r"^(SIGMA|SIG SMARTSHOP|TOTALENERGIES|TOTAL|SHELL|TEXACO|ESSO|ISLA|PUMA)\b", VEHICLE),
        (r"\bDISNEY\b|\bHBO\b|\bCLAUDE\b|^GOOGLE\b|^APPLE COM\b", SUBSCRIPTIONS),
        (r"^LUBRI|\bAUTO ?PARTS?\b|\bGOMERA\b", VEHICLE),
        (r"^(ELECTRODOM|INNOVACENTRO|IKEA|PLAZA LAMA HOGAR)", HOME),
        (r"\bLIQUOR|^(WAL MART|WALMART|WM SUPERCENTER)\b", GROCERIES),
        (r"^ROSS\b", SHOPPING),
        (r"^MICROSOFT\b", SUBSCRIPTIONS),
        (r"^AMERICAN (AIR|\d)", TRAVEL),
    )
)
# Variants of the same merchant that are better seen together.
_MERCHANT_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), name)
    for pattern, name in (
        (r"^(AMZN|AMAZON)\b", "AMAZON"),
        (r"^UBER EATS\b", "UBER EATS"),
        (r"^(UBER (TRIP|RIDES)|UBR PENDING)\b", "UBER VIAJES"),  # spanish-data
        (r"^PEDIDOS ?YA\b", "PEDIDOS YA"),
        (r"^(WAL MART|WALMART|WM SUPERCENTER)\b", "WALMART"),
    )
)
# Bank account debits, in order. Whatever none recognizes is a transfer to third parties
# (card payments and transfers between own accounts are detected in `transfers`).
_BANK_DEBIT_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), category)
    for pattern, category in (
        (r"\b(IMPUESTOS?|RETEN\w*|DGII)\b", GOVERNMENT),
        (r"^(COMISION|CARGO)\b|\bCOMISION(ES)?\b", BANK_FEES),
        (_BANK_FEES.pattern, BANK_FEES),
        (r"\bBANCASEGURO\b|\bSEGUROS?\b", INSURANCE),
        (r"\b(RETIRO|CAJERO|ATM)\b|^(COD )?CASH\b|\bCOD CASH\b", CASH),
        (r"^AUT PAGO\b|\bPRESTAMOS?\b", LOANS),
    )
)
# Bank account credits, in order; anything else is `OTHER_INCOME`. A reimbursement from the
# insurer is negative `HEALTH`: it reduces spending like a card refund.
_BANK_CREDIT_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), category)
    for pattern, category in (
        (r"\bNOMINAS?\b", SALARY),
        (r"\b(MAPFRE|SENASA|PALIC)\b", HEALTH),
        # HUMANO and UNIVERSAL are also names of other companies: they require ARS or SEGURO.
        (r"^(?=.*\b(HUMANO|UNIVERSAL)\b)(?=.*\b(ARS|SEGUROS?)\b)", HEALTH),
        # A reimbursement comes from the insurer only if it says so (not a travel-expense one).
        (r"^(?=.*\bREEMBOLSO\b)(?=.*\b(HUMANO|UNIVERSAL|ARS|SEGUROS?|SALUD)\b)", HEALTH),
    )
)
_REFUND_PREFIX = re.compile(r"^(DEV|DEVOLUCION) (?=\S)")

# Bank merchant key (`bank_merchant_key`).
_BANK_KEY_WORDS = 3
_COUNTERPART_WORDS = 2
_REVERSAL_WORD = "DEV"
_ACCOUNT_DIGITS = 6  # an account number has at least 6 digits
# Particles (those of `transfers._PARTICLES` and a few more): they tell nobody apart.
_STOPWORDS = frozenset({"DE", "DEL", "LA", "LAS", "LOS", "EL", "Y", "EN", "AL", "POR", "PARA"})
# Months (abbreviated and full): they change every month in the text of the same payment.
_MONTHS = frozenset(
    [
        "ENE",
        "FEB",
        "MAR",
        "ABR",
        "MAY",
        "JUN",
        "JUL",
        "AGO",
        "SEP",
        "SEPT",
        "OCT",
        "NOV",
        "DIC",
        "ENERO",
        "FEBRERO",
        "MARZO",
        "ABRIL",
        "MAYO",
        "JUNIO",
        "JULIO",
        "AGOSTO",
        "SEPTIEMBRE",
        "SETIEMBRE",
        "OCTUBRE",
        "NOVIEMBRE",
        "DICIEMBRE",
    ]
)
# Channel, displayed name (None: the channel's text) and whether the counterpart is the account
# number (True) or the name (False).
_Channel = tuple[re.Pattern[str], str | None, bool]
_PREVIOUS_CHANNELS: tuple[_Channel, ...] = (
    (re.compile(r"^MB (A|DESDE)\b"), None, True),
    (re.compile(r"^TOKE (A DE|A|DE)\b"), None, False),  # "TOKE a/de" arrives as "TOKE A DE"
    (re.compile(r"^LBTR( IB VIA LBTR)?\b"), "LBTR", False),
    (re.compile(r"^AUT PAGO\b"), None, True),
)
# The channels from before Banreservas (`_PREVIOUS_CHANNELS`) give the previous key
# (`previous_bank_key`): rules and marks stored with it remain valid.
_BANK_CHANNELS: tuple[_Channel, ...] = (
    *_PREVIOUS_CHANNELS,
    # Banreservas: the counterpart is on the lines below the row. "A" and "DE" tell sent from
    # received; a bare "TRANSFERENCIA" carries no counterpart.
    (re.compile(r"^TRANSFERENCIA (A|DE)\b"), None, False),
    (re.compile(r"^PAGOS AL INSTANTE BCRD (A|DE)\b"), None, False),
)
_PAYMENT = re.compile(r"^PAGO\b|\bSU PAGO\b")
# Card credits the bank gives away (promotions, cashback, bonuses): they are income.
# "BONO" only as an explicit credit ("CR BONO"): "BONO SPA" is a merchant.
_PROMOTION = re.compile(
    r"\bPROMOCION(ES)?\b|\bCASH ?BACK\b|\bREEMBOLSO PROMO|\b(CR|CREDITO) BONO\b"
)


def clean(description: str) -> str:
    """Comparable text: no accents, upper case, no leading reference or punctuation."""
    text = re.sub(r"[^0-9A-Z]+", " ", normalize(description).upper())
    text = re.sub(r"(?<=[A-Z])(?=\d)|(?<=\d)(?=[A-Z])", " ", text)  # "AMERICAN0012" -> 2 words
    words = text.split()
    while words and words[0].isdigit() and len(words[0]) >= 6:
        words.pop(0)
    return " ".join(words)


def is_payment(description: str) -> bool:
    """A card payment is neither spending nor a refund: it moves money between your accounts."""
    return _PAYMENT.search(clean(description)) is not None


def is_promotion(description: str) -> bool:
    """A promotion, cashback or bonus credit: money coming in, not a refund."""
    return _PROMOTION.search(clean(description)) is not None


def merchant_key(description: str) -> str:
    """First words of the merchant, without numbers, to group its variants."""
    text = _REFUND_PREFIX.sub("", clean(description))
    for pattern, name in _MERCHANT_ALIASES:
        if pattern.search(text):
            return name
    words = [word for word in text.split() if not word.isdigit()]
    return " ".join(words[:_KEY_WORDS]) or _NO_DESCRIPTION


def bank_merchant_key(description: str) -> str:
    """Counterpart of a bank account transaction, to group its variants.

    On a bank, `merchant_key` (two words) gives the channel ("MB A", "LBTR IB") or glues the
    amounts ("TRNFUSD9,999.99..."). Here:
    - a known channel (`_BANK_CHANNELS`) comes with its counterpart: the account number or
      up to two words of the name, depending on the channel;
    - a reversal ("DEV ...") is "DEV" plus the first word after it: its reference changes
      every time;
    - anything else, up to three words without numbers (or years), months, single letters
      or particles.
    Stable from one month to the next for the same counterpart (amounts, dates and references
    left out).
    """
    return _bank_key(description, _BANK_CHANNELS)


def previous_bank_key(description: str) -> str:
    """The key `bank_merchant_key` gave before the Banreservas channels.

    Used to look up merchant rules and recurring marks stored earlier, when there is none
    with the current key ("TRANSFERENCIA A X" used to be "TRANSFERENCIA X").
    """
    return _bank_key(description, _PREVIOUS_CHANNELS)


def _bank_key(description: str, channels: tuple[_Channel, ...]) -> str:
    words = clean(description).split()
    if words and words[0] == _REVERSAL_WORD:
        rest = _plain_words(words[1:])
        return " ".join((_REVERSAL_WORD, *rest[:1]))
    text = " ".join(words)
    for pattern, label, prefer_number in channels:
        found = pattern.match(text)
        if found is not None:
            counterpart = _counterpart(text[found.end() :].split(), prefer_number)
            return " ".join((label or found.group(0), *counterpart)).strip()
    return " ".join(_plain_words(words)[:_BANK_KEY_WORDS]) or _NO_DESCRIPTION


def _counterpart(words: list[str], prefer_number: bool) -> tuple[str, ...]:
    """Account number or up to two words of the name; if the preferred one is missing, the
    other.

    The number has at least 6 digits; the name is the words after it (or all of them, without
    a number), without particles or single letters: "MARIA DE LA CRUZ" is MARIA CRUZ.
    """
    number = next((w for w in words if w.isdigit() and len(w) >= _ACCOUNT_DIGITS), None)
    after = words[words.index(number) + 1 :] if number is not None else words
    names = tuple(_name_words(after))[:_COUNTERPART_WORDS]
    if prefer_number:
        return (number,) if number is not None else names
    return names or ((number,) if number is not None else ())


def _name_words(words: Iterable[str]) -> list[str]:
    return [w for w in words if w.isalpha() and len(w) > 1 and w not in _STOPWORDS]


def _plain_words(words: Iterable[str]) -> list[str]:
    """Words of a generic merchant: like a name, and without months (years are numbers)."""
    return [w for w in _name_words(words) if w not in _MONTHS]


def is_reversal(description: str) -> bool:
    """Reversal of a bank transaction: the text starts with the word "DEV"."""
    words = clean(description).split()
    return bool(words) and words[0] == _REVERSAL_WORD


def category_for_mcc(mcc: str | None) -> str | None:
    if not mcc or not mcc.isdigit():
        return None
    if mcc in _MCC_TABLE:
        return _MCC_TABLE[mcc]
    code = int(mcc)
    return next((name for low, high, name in _MCC_RANGES if low <= code <= high), None)


def categorize(description: str, mcc: str | None, learned: Mapping[str, str]) -> str:
    text = _REFUND_PREFIX.sub("", clean(description))
    if mcc is None and _BANK_FEES.search(text):
        return BANK_FEES
    found = _first_match(_KEYWORD_RULES, text) or category_for_mcc(mcc)
    found = found or learned.get(merchant_key(text))
    return found or _first_match(_FALLBACK_RULES, text) or OTHER


def categorize_bank(description: str, direction: str) -> str:
    """Category of a bank account transaction.

    Own transfers and card payments are detected separately (`transfers`). A credit follows
    the credit rules or is `OTHER_INCOME`. A debit follows the debit rules or is a transfer to
    third parties: it is not spending unless the user corrects it.
    """
    text = clean(description)
    if direction == CREDIT:
        if is_reversal(text):
            # Without its debit (see `reversals`): the category the debit it cancels would have
            # (a commission, a tax...) or, if no rule recognizes it, it reduces the transfers out.
            rest = text.partition(" ")[2]
            return _first_match(_BANK_DEBIT_RULES, rest) or THIRD_PARTY
        return _first_match(_BANK_CREDIT_RULES, text) or OTHER_INCOME
    return _first_match(_BANK_DEBIT_RULES, text) or THIRD_PARTY


def _first_match(rules: tuple[tuple[re.Pattern[str], str], ...], text: str) -> str | None:
    return next((category for pattern, category in rules if pattern.search(text)), None)


def learn_merchants(items: Iterable[tuple[str, str | None]]) -> dict[str, str]:
    """Most frequent category of each merchant among the transactions that carry an MCC."""
    seen: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for description, mcc in items:
        category = category_for_mcc(mcc)
        if category is not None:
            seen[merchant_key(description)][category] += 1
    return {key: counts.most_common(1)[0][0] for key, counts in seen.items()}
