"""Dominican household utility providers and prepaid top-ups (pure logic).

The same provider arrives as several merchants depending on the channel ("CLARO PAGO",
"CLARO IBANKING", "CLARO WB"...). Inside the Utilities category, `recurring` gathers those
merchants into one series per provider: here is the fixed list (by prefix of the merchant key,
already normalized: uppercase without accents or punctuation) and the top-up rule (top-ups are
nobody's bill).

What is not on the list is joined by hand with "Join with..." (`recurring_marks.set_union`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from michelito.analysis.categories import clean

# A provider's series key: never clashes with a merchant key (those never contain ":").
KEY_PREFIX = "provider:"


@dataclass(frozen=True)
class Provider:
    id: str
    name: str  # the display name
    pattern: re.Pattern[str]  # matched against the start of the merchant key

    @property
    def key(self) -> str:
        return f"{KEY_PREFIX}{self.id}"


def make_provider(id_: str, name: str, prefix: str) -> Provider:
    """A provider recognized by `prefix` (a regular expression) at the start of the key."""
    return Provider(id_, name, re.compile(rf"^(?:{prefix})\b"))


# Public company names (nobody's data). Order does not matter: the prefixes never overlap.
PROVIDERS: tuple[Provider, ...] = (
    # Phone, cable and internet.
    make_provider("claro", "Claro", r"CLARO|CODETEL"),
    make_provider("altice", "Altice", r"ALTICE|ORANGE DOMINICANA"),
    make_provider("wind", "Wind", r"WIND(?: TELECOM)?"),
    make_provider("viva", "Viva", r"VIVA"),
    make_provider("sky", "Sky", r"SKY(?: DOMINICANA)?"),
    make_provider("tricom", "Tricom", r"TRICOM"),
    make_provider("aster", "Aster", r"ASTER"),
    # Electricity.
    make_provider("edeeste", "Edeeste", r"EDE ?ESTE"),
    make_provider("edesur", "Edesur", r"EDE ?SUR"),
    make_provider("edenorte", "Edenorte", r"EDE ?NORTE"),
    make_provider("cepm", "CEPM", r"CEPM"),
    # Water.
    make_provider("caasd", "CAASD", r"CAASD"),
    make_provider("coraasan", "CORAASAN", r"CORAASAN"),
    make_provider("coraamoca", "CORAAMOCA", r"CORAAMOCA"),
    make_provider("coraapplata", "CORAAPPLATA", r"CORAAPPLATA"),
    make_provider("inapa", "INAPA", r"INAPA"),
)

# Prepaid top-ups: "RECAR" (as banks abbreviate it), "RECARGA(S)", "RECARGAR" and
# "TOPUP"/"TOP UP" as a word, in the already normalized description. They are neither the
# provider's bill nor recurring; they still count as an expense in their category.
RECHARGE = re.compile(r"\b(?:RECAR|RECARG(?:A|AS|AR)|TOP ?UPS?)\b")  # spanish-data


# What follows the provider's name in a bill payment: the channel or the service. With another
# word after it ("CLARO AGORA", "CLARO CAC", "VIVA AEROBUS", "SKY TIENDA FICTICIA",
# "ASTER CAFETERIA FICTICIA") it is not the bill: it is a purchase at a provider's store or
# center, or another merchant with the same prefix. The bare key ("CLARO") is also the bill.
# Words as they appear in Dominican bank descriptions.
# spanish-data: begin
CHANNEL_WORDS = frozenset(
    {
        "PAGO",
        "PAGOS",
        "P",
        "IBANKING",
        "IB",
        "WB",
        "WEB",
        "ONLINE",
        "APP",
        "DOMINICANA",
        "FIJO",
        "MOVIL",
        "FACTURA",
        "SERVICIO",
        "SERVICIOS",
        "INTERNET",
        "TV",
        "CABLE",
        "POSTPAGO",
        "RESIDENCIAL",
        "TELECOM",
        "DEBITO",
        "AUTOMATICO",
    }
)
# spanish-data: end


def _match(merchant: str) -> tuple[Provider, str] | None:
    """The provider whose prefix opens the key, and what is left after the prefix."""
    text = clean(merchant)
    for provider in PROVIDERS:
        found = provider.pattern.search(text)
        if found is not None:
            return provider, text[found.end() :].strip()
    return None


def provider_of(merchant: str) -> Provider | None:
    """The listed provider of a payment of its bill: the key starts with its name and is
    followed by nothing or by a word of `CHANNEL_WORDS`."""
    found = _match(merchant)
    if found is None:
        return None
    provider, rest = found
    return provider if not rest or rest.split()[0] in CHANNEL_WORDS else None


def store_of(merchant: str) -> Provider | None:
    """The provider whose name opens the key without it being a bill payment (a store or a
    service center: "CLARO AGORA"), or None."""
    found = _match(merchant)
    if found is None or provider_of(merchant) is not None:
        return None
    return found[0]


def by_key(key: str) -> Provider | None:
    return next((p for p in PROVIDERS if p.key == key), None)


def is_provider_key(key: str) -> bool:
    return key.startswith(KEY_PREFIX)


def is_recharge(description: str, merchant: str = "") -> bool:
    return any(RECHARGE.search(clean(text)) for text in (description, merchant) if text)


def display_name(key: str) -> str:
    """A series key's display name: the provider's, or the merchant key."""
    found = by_key(key)
    return key if found is None else found.name
