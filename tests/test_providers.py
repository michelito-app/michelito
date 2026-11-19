"""The fixed list of providers (public company names, nobody's data): which key is a bill
payment, and which is another merchant with the same prefix or one of the provider's stores."""

import pytest

from michelito.analysis import providers


@pytest.mark.parametrize(
    ("merchant", "expected"),
    [
        ("CLARO", "claro"),
        ("CLARO PAGO", "claro"),
        ("CLARO IBANKING", "claro"),
        ("ALTICE DOMINICANA", "altice"),
        ("EDEESTE P", "edeeste"),
        ("CAASD FACTURA", "caasd"),
        ("VIVA AEROBUS", None),
        ("SKY TIENDA FICTICIA", None),
        ("ASTER CAFETERIA FICTICIA", None),
        ("CLARO AGORA", None),
        ("CLARO CAC", None),
        ("SKYFICTICIO TOURS", None),
    ],
)
def test_provider_of(merchant: str, expected: str | None) -> None:
    found = providers.provider_of(merchant)
    assert (found.id if found else None) == expected


def test_store_of_is_the_provider_prefix_without_a_channel() -> None:
    store = providers.store_of("CLARO AGORA")
    assert store is not None and store.id == "claro"
    assert providers.store_of("CLARO PAGO") is None
    assert providers.store_of("SUPERMERCADO") is None
