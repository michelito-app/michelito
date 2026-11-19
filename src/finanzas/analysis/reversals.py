"""Reversiones de cuentas bancarias: un crédito "DEV …" que anula un débito reciente.

Un crédito bancario cuyo texto empieza con la palabra "DEV" (`categories.is_reversal`) es la
reversión de un débito de la misma cuenta, moneda y monto hecho hasta REVERSAL_DAYS días
antes (o el mismo día). Toma la categoría final de ese débito (con las correcciones del
usuario), así los dos se anulan dentro de esa categoría: corregir solo el LBTR a "Entre mis
cuentas" basta para que su DEV no se vuelva ingreso. El emparejamiento no depende de las
correcciones (cuenta, moneda, monto y fecha). Uno a uno: cada débito anula una sola
reversión, el más cercano en fecha primero (en empate, el primero en orden de carga).
Es codicioso, por orden de reversión: con varios débitos y reversiones iguales en la misma
ventana puede no dar el emparejamiento óptimo (raro: mismo monto, cuenta y semana).

La `original_category` de una reversión emparejada es la categoría final de su débito. En
ella solo gana una corrección de esa transacción: las reglas de comercio (y las de la clave
anterior) no cuentan, porque todas las reversiones comparten clave ("DEV LBTR").

Sin su débito, la reversión queda con `categories.categorize_bank`: las reglas de débitos
sobre el texto que sigue a "DEV" (una comisión, un impuesto…, en negativo) o
"Transferencias a terceros" en negativo; ahí sí aplican las reglas de comercio.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import TYPE_CHECKING

from finanzas.analysis import categories
from finanzas.analysis.accounts import BANK_KINDS, AccountInfo

if TYPE_CHECKING:
    from finanzas.analysis.spending import Movement

REVERSAL_DAYS = 7


def pair_reversals(
    movements: Sequence[Movement], accounts: Sequence[AccountInfo]
) -> dict[str, str]:
    """Huella de cada reversión emparejada -> categoría final de su débito."""
    banks = {info.key for info in accounts if info.kind in BANK_KINDS}
    rows = [(index, m) for index, m in enumerate(movements) if m.account in banks]
    free = [(index, m) for index, m in rows if m.amount > 0]
    window = timedelta(days=REVERSAL_DAYS)
    found: dict[str, str] = {}
    credits = [(i, m) for i, m in rows if m.amount < 0 and categories.is_reversal(m.description)]
    for _, credit in sorted(credits, key=lambda pair: (pair[1].day, pair[0])):
        near = [
            (index, debit)
            for index, debit in free
            if debit.account == credit.account
            and debit.currency == credit.currency
            and debit.amount == -credit.amount
            and timedelta(0) <= credit.day - debit.day <= window
        ]
        if near:
            chosen = min(near, key=lambda pair: (credit.day - pair[1].day, pair[0]))
            free.remove(chosen)
            found[credit.fingerprint] = chosen[1].ref
    return found
