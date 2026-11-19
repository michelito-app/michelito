"""Proveedores de servicios del hogar de RD y recargas prepago (lógica pura).

El mismo proveedor llega con varios comercios según el canal ("CLARO PAGO", "CLARO IBANKING",
"CLARO WB"…). Dentro de la categoría Servicios, `recurring` junta esos comercios en una serie
por proveedor: aquí está la lista fija (por prefijo de la clave de comercio, ya normalizada:
mayúsculas sin acentos ni signos) y la regla de las recargas, que no son la factura de nadie.

Lo que no está en la lista se junta a mano con «Unir con…» (`recurring_marks.set_union`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from finanzas.analysis.categories import clean

# Clave de serie de un proveedor: no choca con una clave de comercio (nunca lleva ":").
KEY_PREFIX = "proveedor:"


@dataclass(frozen=True)
class Provider:
    id: str
    name: str  # el nombre que se muestra
    pattern: re.Pattern[str]  # contra el inicio de la clave del comercio

    @property
    def key(self) -> str:
        return f"{KEY_PREFIX}{self.id}"


def make_provider(id_: str, name: str, prefix: str) -> Provider:
    """Un proveedor que se reconoce por `prefix` (expresión regular) al inicio de la clave."""
    return Provider(id_, name, re.compile(rf"^(?:{prefix})\b"))


# Nombres públicos de empresas (no datos de nadie). El orden no importa: los prefijos no se pisan.
PROVIDERS: tuple[Provider, ...] = (
    # Telefonía, cable e internet.
    make_provider("claro", "Claro", r"CLARO|CODETEL"),
    make_provider("altice", "Altice", r"ALTICE|ORANGE DOMINICANA"),
    make_provider("wind", "Wind", r"WIND(?: TELECOM)?"),
    make_provider("viva", "Viva", r"VIVA"),
    make_provider("sky", "Sky", r"SKY(?: DOMINICANA)?"),
    make_provider("tricom", "Tricom", r"TRICOM"),
    make_provider("aster", "Aster", r"ASTER"),
    # Electricidad.
    make_provider("edeeste", "Edeeste", r"EDE ?ESTE"),
    make_provider("edesur", "Edesur", r"EDE ?SUR"),
    make_provider("edenorte", "Edenorte", r"EDE ?NORTE"),
    make_provider("cepm", "CEPM", r"CEPM"),
    # Agua.
    make_provider("caasd", "CAASD", r"CAASD"),
    make_provider("coraasan", "CORAASAN", r"CORAASAN"),
    make_provider("coraamoca", "CORAAMOCA", r"CORAAMOCA"),
    make_provider("coraapplata", "CORAAPPLATA", r"CORAAPPLATA"),
    make_provider("inapa", "INAPA", r"INAPA"),
)

# Recargas prepago: «RECAR» (como lo abrevian los bancos), «RECARGA(S)», «RECARGAR» y
# «TOPUP»/«TOP UP» como palabra, en la descripción ya normalizada. No son la factura del
# proveedor ni un recurrente; siguen contando como gasto en su categoría.
RECHARGE = re.compile(r"\b(?:RECAR|RECARG(?:A|AS|AR)|TOP ?UPS?)\b")


# Lo que sigue al nombre del proveedor en un pago de la factura: el canal o el servicio. Con
# otra palabra detrás («CLARO AGORA», «CLARO CAC», «VIVA AEROBUS», «SKY TIENDA FICTICIA»,
# «ASTER CAFETERIA FICTICIA») no es la factura: es una compra en una tienda o centro del
# proveedor, u otro comercio con el mismo prefijo. La clave sola («CLARO») también es la factura.
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


def _match(merchant: str) -> tuple[Provider, str] | None:
    """El proveedor cuyo prefijo abre la clave y lo que queda detrás del prefijo."""
    text = clean(merchant)
    for provider in PROVIDERS:
        found = provider.pattern.search(text)
        if found is not None:
            return provider, text[found.end() :].strip()
    return None


def provider_of(merchant: str) -> Provider | None:
    """El proveedor de la lista de un pago de su factura: la clave empieza con su nombre y
    detrás no hay nada o una palabra de `CHANNEL_WORDS`."""
    found = _match(merchant)
    if found is None:
        return None
    provider, rest = found
    return provider if not rest or rest.split()[0] in CHANNEL_WORDS else None


def store_of(merchant: str) -> Provider | None:
    """El proveedor cuyo nombre abre la clave sin ser un pago de la factura (una tienda o un
    centro de atención: «CLARO AGORA»), o None."""
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
    """El nombre visible de una clave de serie: el del proveedor o la clave del comercio."""
    found = by_key(key)
    return key if found is None else found.name
