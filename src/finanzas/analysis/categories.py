"""Clasificación de movimientos de tarjeta en categorías de gasto.

Orden de decisión (de más a menos preciso):
1. Cargos del banco (intereses, mora, comisiones), por palabra clave.
2. Reglas por palabra clave para comercios cuyo MCC engaña (Uber Eats llega
   como restaurante, Amazon como librería).
3. El MCC (código de categoría del comercio) que imprime el Popular.
4. La categoría aprendida del mismo comercio en transacciones con MCC: el BHD
   no imprime MCC, pero muchos comercios aparecen en ambas tarjetas.
5. Reglas de respaldo por palabras genéricas ("RESTAURANT", "PEAJES"): menos
   seguras que el MCC, por eso van después.
6. "Otros".

Un crédito de tarjeta que es promoción, cashback o bono (`is_promotion`) es "Otros
ingresos"; lo decide `spending`, que sabe la dirección.

Una devolución ("DEV. AMAZON") se clasifica como el comercio que devuelve.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Literal

from finanzas.parsers.common import CREDIT, normalize

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
# Débitos bancarios a otras personas: no son gasto, pero sí restan de lo que te quedó.
THIRD_PARTY = "Transferencias a terceros"
# Créditos enlazados a un gasto compartido (`links`): devuelven parte de ese gasto, no son ingreso.
REIMBURSEMENT = "Reembolso"
# Movimientos enlazados en un cambio de divisas con terceros (`links`): ni gasto ni ingreso.
CURRENCY_EXCHANGE = "Cambio de divisas"
# Inversiones (`links`, `analysis.investments`): el aporte es dinero tuyo que sigue siendo tuyo
# (ni gasto ni resta de lo que te quedó); lo que rinde es ingreso; el capital que vuelve, no.
INVESTMENT = "Inversiones"
INVESTMENT_RETURN = "Rendimientos"
INVESTMENT_CAPITAL = "Devolución de capital"
# Caja fuerte (`analysis.cash_box`): un retiro guardado en la caja o un depósito que salió de
# ella. Es tu dinero en otro lugar: ni gasto ni ingreso, no resta de lo que te quedó.
CASH_BOX = "Caja fuerte"
# Las que solo pone su vínculo (marcar una inversión o la caja fuerte): no se eligen a mano, ni
# con una corrección ni con palabras clave. "Rendimientos" sí: un ingreso cualquiera puede serlo.
LINK_ONLY = (INVESTMENT, INVESTMENT_CAPITAL, CASH_BOX)

# Nombres viejos que pueden estar guardados en las correcciones.
_LEGACY_NAMES = {"Efectivo y transferencias": CASH}

Kind = Literal["ingreso", "gasto", "transferencia"]

# Categorías de gasto, en el orden en que se ofrecen al corregir una a mano.
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

# Todas las categorías: gastos, luego ingresos, luego transferencias.
ALL = (*EXPENSES, *INCOME, *TRANSFER)

KIND_OF: dict[str, Kind] = {
    **dict.fromkeys(EXPENSES, "gasto"),
    **dict.fromkeys(INCOME, "ingreso"),
    **dict.fromkeys(TRANSFER, "transferencia"),
}


# Identidad estable de cada categoría del sistema (`categories.builtin_key` en la base) -> su
# referencia en el análisis. La referencia es el nombre con que nació y no cambia aunque el
# usuario la renombre: la lógica compara contra estas constantes, nunca contra el nombre que
# se muestra (ver `catalog`).
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
    """Tipo de una categoría; una desconocida cuenta como gasto."""
    return KIND_OF.get(category, "gasto")


def canonical(category: str) -> str:
    """Nombre actual de una categoría guardada con un nombre anterior."""
    return _LEGACY_NAMES.get(category, category)


_NO_DESCRIPTION = "SIN DESCRIPCION"
_KEY_WORDS = 2

# Códigos MCC por categoría, separados por espacios.
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
# Rangos reservados por las marcas: aerolíneas, alquiler de autos y hoteles.
_MCC_RANGES = ((3000, 3999, TRAVEL),)

# Cargos del banco. Los nombres comunes ("MORA", "CARGO") solo con su forma exacta
# para no atrapar comercios como "MORA FICTICIA"; nunca aplica si hay MCC.
_BANK_FEES = re.compile(
    r"^(CR )?(INTERES|INTERESES|COMISION)\b|^MORA$|^PROTECCION POR\b|^ITBIS\b"
    r"|^CARGO (COBERTURA|PARCIAL|RENOVACION|SOBREGIRO|POR)\b"
)
# Solo comercios inconfundibles cuyo MCC engaña: le ganan al MCC.
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
# Palabras genéricas: solo cuando ni el MCC ni el comercio aprendido deciden.
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
# Variantes de un mismo comercio que conviene ver juntas.
_MERCHANT_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), name)
    for pattern, name in (
        (r"^(AMZN|AMAZON)\b", "AMAZON"),
        (r"^UBER EATS\b", "UBER EATS"),
        (r"^(UBER (TRIP|RIDES)|UBR PENDING)\b", "UBER VIAJES"),
        (r"^PEDIDOS ?YA\b", "PEDIDOS YA"),
        (r"^(WAL MART|WALMART|WM SUPERCENTER)\b", "WALMART"),
    )
)
# Débitos de cuentas bancarias, en orden. Lo que ninguna reconoce es una transferencia a
# terceros (los pagos de tarjeta y entre mis cuentas se detectan en `transfers`).
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
# Créditos de cuentas bancarias, en orden; lo demás es "Otros ingresos". Un reembolso de
# la aseguradora es Salud en negativo: resta del gasto como una devolución de tarjeta.
_BANK_CREDIT_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), category)
    for pattern, category in (
        (r"\bNOMINAS?\b", SALARY),
        (r"\b(MAPFRE|SENASA|PALIC)\b", HEALTH),
        # HUMANO y UNIVERSAL también son nombres de otras empresas: piden ARS o SEGURO.
        (r"^(?=.*\b(HUMANO|UNIVERSAL)\b)(?=.*\b(ARS|SEGUROS?)\b)", HEALTH),
        # Un reembolso es de la aseguradora solo si lo dice (no uno de gastos de viaje).
        (r"^(?=.*\bREEMBOLSO\b)(?=.*\b(HUMANO|UNIVERSAL|ARS|SEGUROS?|SALUD)\b)", HEALTH),
    )
)
_REFUND_PREFIX = re.compile(r"^(DEV|DEVOLUCION) (?=\S)")

# Clave de comercio bancaria (`bank_merchant_key`).
_BANK_KEY_WORDS = 3
_COUNTERPART_WORDS = 2
_REVERSAL_WORD = "DEV"
_ACCOUNT_DIGITS = 6  # un número de cuenta tiene al menos 6 dígitos
# Partículas (las de `transfers._PARTICLES` y algunas más): no distinguen a nadie.
_STOPWORDS = frozenset({"DE", "DEL", "LA", "LAS", "LOS", "EL", "Y", "EN", "AL", "POR", "PARA"})
# Meses (abreviados y completos): cambian cada mes en el texto de un mismo pago.
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
# Canal, nombre que se muestra (None: el texto del canal) y si la contraparte es el número
# de cuenta (True) o el nombre (False).
_Channel = tuple[re.Pattern[str], str | None, bool]
_PREVIOUS_CHANNELS: tuple[_Channel, ...] = (
    (re.compile(r"^MB (A|DESDE)\b"), None, True),
    (re.compile(r"^TOKE (A DE|A|DE)\b"), None, False),  # "TOKE a/de" llega como "TOKE A DE"
    (re.compile(r"^LBTR( IB VIA LBTR)?\b"), "LBTR", False),
    (re.compile(r"^AUT PAGO\b"), None, True),
)
# Los canales de antes de Banreservas (`_PREVIOUS_CHANNELS`) dan la clave anterior
# (`previous_bank_key`): las reglas y marcas guardadas con ella siguen valiendo.
_BANK_CHANNELS: tuple[_Channel, ...] = (
    *_PREVIOUS_CHANNELS,
    # Banreservas: la contraparte va en los renglones debajo de la fila. "A" y "DE" separan
    # lo enviado de lo recibido; una "TRANSFERENCIA" sola no trae contraparte.
    (re.compile(r"^TRANSFERENCIA (A|DE)\b"), None, False),
    (re.compile(r"^PAGOS AL INSTANTE BCRD (A|DE)\b"), None, False),
)
_PAYMENT = re.compile(r"^PAGO\b|\bSU PAGO\b")
# Créditos de la tarjeta que regala el banco (promociones, cashback, bonos): son ingreso.
# "BONO" solo como crédito explícito ("CR BONO"): "BONO SPA" es un comercio.
_PROMOTION = re.compile(
    r"\bPROMOCION(ES)?\b|\bCASH ?BACK\b|\bREEMBOLSO PROMO|\b(CR|CREDITO) BONO\b"
)


def clean(description: str) -> str:
    """Texto comparable: sin acentos, en mayúsculas, sin referencia inicial ni signos."""
    text = re.sub(r"[^0-9A-Z]+", " ", normalize(description).upper())
    text = re.sub(r"(?<=[A-Z])(?=\d)|(?<=\d)(?=[A-Z])", " ", text)  # "AMERICAN0012" -> 2 palabras
    words = text.split()
    while words and words[0].isdigit() and len(words[0]) >= 6:
        words.pop(0)
    return " ".join(words)


def is_payment(description: str) -> bool:
    """Un pago a la tarjeta no es gasto ni devolución: mueve dinero entre tus cuentas."""
    return _PAYMENT.search(clean(description)) is not None


def is_promotion(description: str) -> bool:
    """Un crédito de promoción, cashback o bono: dinero que entra, no una devolución."""
    return _PROMOTION.search(clean(description)) is not None


def merchant_key(description: str) -> str:
    """Primeras palabras del comercio, sin números, para agrupar sus variantes."""
    text = _REFUND_PREFIX.sub("", clean(description))
    for pattern, name in _MERCHANT_ALIASES:
        if pattern.search(text):
            return name
    words = [word for word in text.split() if not word.isdigit()]
    return " ".join(words[:_KEY_WORDS]) or _NO_DESCRIPTION


def bank_merchant_key(description: str) -> str:
    """Contraparte de un movimiento de cuenta bancaria, para agrupar sus variantes.

    `merchant_key` (dos palabras) da en un banco el canal ("MB A", "LBTR IB") o pega los
    montos ("TRNFUSD9,999.99…"). Aquí:
    - un canal conocido (`_BANK_CHANNELS`) va con su contraparte: el número de cuenta o
      hasta dos palabras del nombre, según el canal;
    - una reversión ("DEV …") es "DEV" y la primera palabra que sigue: su referencia cambia
      cada vez;
    - lo demás, hasta tres palabras sin números (ni años), meses, letras sueltas ni
      partículas.
    Estable de un mes a otro para la misma contraparte (montos, fechas y referencias fuera).
    """
    return _bank_key(description, _BANK_CHANNELS)


def previous_bank_key(description: str) -> str:
    """La clave que daba `bank_merchant_key` antes de los canales de Banreservas.

    Con ella se buscan las reglas de comercio y las marcas de recurrentes guardadas antes,
    cuando no hay una con la clave actual ("TRANSFERENCIA A X" era "TRANSFERENCIA X").
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
    """Número de cuenta o hasta dos palabras del nombre; si falta lo preferido, lo otro.

    El número tiene al menos 6 dígitos; el nombre son las palabras que le siguen (o todas,
    sin número), sin partículas ni letras sueltas: "MARIA DE LA CRUZ" es MARIA CRUZ.
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
    """Palabras de un comercio genérico: como un nombre, y sin meses (los años son números)."""
    return [w for w in _name_words(words) if w not in _MONTHS]


def is_reversal(description: str) -> bool:
    """Reversión de un movimiento bancario: el texto empieza con la palabra "DEV"."""
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
    """Categoría de un movimiento de cuenta bancaria.

    Las transferencias propias y los pagos de tarjeta se detectan aparte (`transfers`).
    Un crédito sigue las reglas de créditos o es "Otros ingresos". Un débito sigue las
    reglas de débitos o es una transferencia a terceros: no es gasto salvo que el usuario
    lo corrija.
    """
    text = clean(description)
    if direction == CREDIT:
        if is_reversal(text):
            # Sin su débito (ver `reversals`): la categoría que tendría el débito que anula
            # (una comisión, un impuesto…) o, si ninguna regla lo reconoce, resta de los envíos.
            rest = text.partition(" ")[2]
            return _first_match(_BANK_DEBIT_RULES, rest) or THIRD_PARTY
        return _first_match(_BANK_CREDIT_RULES, text) or OTHER_INCOME
    return _first_match(_BANK_DEBIT_RULES, text) or THIRD_PARTY


def _first_match(rules: tuple[tuple[re.Pattern[str], str], ...], text: str) -> str | None:
    return next((category for pattern, category in rules if pattern.search(text)), None)


def learn_merchants(items: Iterable[tuple[str, str | None]]) -> dict[str, str]:
    """Categoría más frecuente de cada comercio entre los movimientos que traen MCC."""
    seen: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for description, mcc in items:
        category = category_for_mcc(mcc)
        if category is not None:
            seen[merchant_key(description)][category] += 1
    return {key: counts.most_common(1)[0][0] for key, counts in seen.items()}
