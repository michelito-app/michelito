"""Detección de transferencias entre las cuentas del usuario.

Una transferencia mueve dinero entre cuentas propias: no es gasto ni ingreso. Se detecta,
en este orden, por:
1. Pago recibido por una tarjeta (ya es "Pago de tarjeta").
2. Un débito bancario de igual moneda y monto que ese pago, con pocos días de diferencia.
3. Un débito bancario cuyo texto habla de pagar una tarjeta ("PAGO … TC"); sirve cuando el
   monto no coincide, como una tarjeta en US$ pagada desde una cuenta en RD$.
4. Un movimiento bancario que nombra a un titular (el banco corta los nombres: ver
   `_names`), el número completo de otra cuenta propia (registrada o escrita en
   titulares.txt; con o sin ceros delante), los últimos 4 dígitos de otra cuenta propia o
   dice "cuenta propia". En una reversión ("DEV …") solo el titular o "cuenta propia": sus
   dígitos son la referencia.

Solo propone la categoría por defecto; las correcciones del usuario siempre ganan.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from finanzas.analysis import categories
from finanzas.analysis.accounts import BANK_KINDS, AccountInfo

if TYPE_CHECKING:
    from finanzas.analysis.spending import Movement

# Días de diferencia tolerados entre el pago de la tarjeta y el débito en el banco.
PAYMENT_MATCH_DAYS = 5

_CREDIT_CARD = "credit_card"
_NUMBER_DIGITS = 4  # los últimos 4 dígitos de una cuenta, como palabra entera
_FULL_NUMBER_DIGITS = 6  # un número completo tiene al menos 6 dígitos
_PREFIX_WORDS = 2  # palabras del titular que bastan cuando el banco corta el nombre
_MIN_CUT = 3  # letras mínimas de una palabra cortada que sigue a una sola palabra entera
_MIN_MID_CUT = 2  # letras mínimas de un corte que no está al final del texto
# Palabras cortas de nombres que en mitad del texto no se toman por un corte.
_PARTICLES = frozenset({"DE", "DEL", "LA", "LAS", "LOS", "Y"})
# Una línea de titulares.txt con solo dígitos y separadores es un número de cuenta propia.
_NUMBER_LINE = re.compile(r"[\d\s.\-/]+")
_OWN_ACCOUNT_WORDING = re.compile(r"\b(CUENTA|CTA) PROPIA\b")
_CARD_PAYMENT_WORDING = re.compile(r"\bPAGO\b.*\b(TC|TDC|TARJETA)\b")

_CARD_LAST4 = """
SELECT a.key, c.last4 FROM cards c JOIN accounts a ON a.id = c.account_id
"""


@dataclass(frozen=True)
class Holders:
    """Lo que dice titulares.txt: nombres (normalizados) y números de cuentas propias."""

    names: tuple[str, ...] = ()
    numbers: tuple[int, ...] = ()  # sin ceros delante: se comparan como enteros


def as_holders(holders: Iterable[str] | Holders) -> Holders:
    """Acepta también una lista de nombres sola (como antes de los números)."""
    if isinstance(holders, Holders):
        return holders
    return Holders(names=tuple(holders))


def load_holders(path: Path) -> Holders:
    """Titulares del archivo, uno por línea; sin archivo (o ilegible), ninguno.

    Una línea con solo dígitos y separadores ("000-123456-7") es el número de una cuenta
    propia si tiene al menos 6 dígitos; con menos se ignora. Las demás son nombres.
    """
    if not path.is_file():
        return Holders()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return Holders()
    names: list[str] = []
    numbers: list[int] = []
    for line in lines:
        stripped = line.strip()
        if stripped and _NUMBER_LINE.fullmatch(stripped):
            digits = re.sub(r"\D", "", line)
            if len(digits) >= _FULL_NUMBER_DIGITS:
                numbers.append(int(digits))
        elif name := categories.clean(line):
            names.append(name)
    return Holders(tuple(dict.fromkeys(names)), tuple(dict.fromkeys(numbers)))


def last4_by_card_account(conn: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    """Últimos 4 dígitos de cada plástico guardado, por clave de cuenta."""
    found: dict[str, list[str]] = {}
    for key, last4 in conn.execute(_CARD_LAST4):
        found.setdefault(key, []).append(last4)
    return {key: tuple(values) for key, values in found.items()}


def detect_transfers(
    movements: Sequence[Movement],
    accounts: Sequence[AccountInfo],
    holders: Iterable[str] | Holders,
    *,
    card_last4: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, str]:
    """Huella -> categoría de transferencia de los movimientos que parecen serlo.

    `holders`: nombres de titulares o `Holders` (nombres y números de titulares.txt).
    `card_last4` aporta los dígitos de las tarjetas (las claves de tarjeta no los traen).
    """
    listed = as_holders(holders)
    kinds = {info.key: info.kind for info in accounts}
    found: dict[str, str] = {}
    payments = [m for m in movements if _is_card_payment(m, kinds)]
    found.update((m.fingerprint, categories.CARD_PAYMENT) for m in payments)
    for debit in _paired_debits(movements, payments, kinds):
        found[debit.fingerprint] = categories.CARD_PAYMENT
    numbers = _numbers_by_account(accounts, card_last4 or {})
    full = _full_numbers(accounts)
    names = [name for name in (categories.clean(h) for h in listed.names) if name]
    for item in movements:
        if item.fingerprint not in found:
            category = _by_wording(item, kinds)
            if category is None and _is_bank_row(item, kinds):
                category = _by_ownership(item, names, numbers, full, listed.numbers)
            if category:
                found[item.fingerprint] = category
    return found


def _is_card_payment(item: Movement, kinds: Mapping[str, str]) -> bool:
    return (
        kinds.get(item.account) == _CREDIT_CARD
        and item.amount < 0
        and item.original_ref == categories.CARD_PAYMENT
    )


def _is_bank_row(item: Movement, kinds: Mapping[str, str]) -> bool:
    """Movimiento de una cuenta bancaria (no de tarjeta): solo ahí rigen las reglas de titular."""
    return kinds.get(item.account, "") in BANK_KINDS


def _is_bank_debit(item: Movement, kinds: Mapping[str, str]) -> bool:
    return item.amount > 0 and _is_bank_row(item, kinds)


def _paired_debits(
    movements: Sequence[Movement], payments: Sequence[Movement], kinds: Mapping[str, str]
) -> list[Movement]:
    """Débitos bancarios con su pago de tarjeta: uno a uno, el más cercano en fecha primero."""
    free = list(payments)
    window = timedelta(days=PAYMENT_MATCH_DAYS)
    paired = []
    for debit in sorted((m for m in movements if _is_bank_debit(m, kinds)), key=_by_day):
        near = [
            p
            for p in free
            if p.currency == debit.currency
            and -p.amount == debit.amount
            and abs(p.day - debit.day) <= window
        ]
        if near:
            free.remove(min(near, key=lambda p: (abs(p.day - debit.day), p.day)))
            paired.append(debit)
    return paired


def _by_day(item: Movement) -> tuple[object, str]:
    return (item.day, item.fingerprint)


def _by_wording(item: Movement, kinds: Mapping[str, str]) -> str | None:
    if _is_bank_debit(item, kinds) and _CARD_PAYMENT_WORDING.search(
        categories.clean(item.description)
    ):
        return categories.CARD_PAYMENT
    return None


def _by_ownership(
    item: Movement,
    holders: Sequence[str],
    numbers: Mapping[str, frozenset[str]],
    full: Mapping[str, int],
    listed: Sequence[int] = (),
) -> str | None:
    text = categories.clean(item.description)
    words = text.split()
    if _OWN_ACCOUNT_WORDING.search(text) or any(_names(words, h.split()) for h in holders):
        return categories.OWN_TRANSFER
    if item.amount < 0 and categories.is_reversal(text):
        return None  # los dígitos de una reversión son su referencia, no una cuenta
    tokens = set(words)
    for key, digits in numbers.items():
        if key != item.account and tokens & digits:
            return categories.OWN_TRANSFER
    long_tokens = {
        int(t) for t in re.findall(r"\d+", item.description) if len(t) >= _FULL_NUMBER_DIGITS
    }
    if any(key != item.account and value in long_tokens for key, value in full.items()):
        return categories.OWN_TRANSFER
    # Un número de titulares.txt que es el de la propia cuenta del movimiento no cuenta.
    mine = full.get(item.account)
    if any(value != mine and value in long_tokens for value in listed):
        return categories.OWN_TRANSFER
    return None


def _names(words: Sequence[str], holder: Sequence[str]) -> bool:
    """La descripción nombra al titular, completo o cortado por el banco, en cualquier lugar.

    El banco corta el nombre donde se acaba el campo, y a veces sigue otro campo
    ("… FULANO DE TA BANCO BHD …"). Desde cualquier palabra, se cuentan las palabras del
    titular que aparecen enteras y seguidas (`m`); vale si:
    - aparecen todas;
    - `m >= 2` y ahí termina el texto ("… FULANO DE");
    - `m >= 2` y la palabra siguiente es el comienzo de la que sigue en el titular
      ("MARIA PEREZ LO BANCO" por MARIA PEREZ LOPEZ), aunque detrás venga más texto;
    - `m == 1` y la siguiente es el comienzo de la segunda, de al menos 3 letras
      ("MARIA PER BANCO").
    En mitad del texto, el corte no puede ser una partícula ni una sola letra (`_is_cut`).
    Una palabra entera distinta corta la coincidencia: "MARIA PEREZ INVENTADAS" no es
    MARIA PEREZ INVENTADA, y "MARIA PEREZ GOMEZ" (otra persona con el mismo nombre y
    apellido) no es MARIA PEREZ LOPEZ. Un titular de una sola palabra tiene que aparecer
    entero.
    """
    size = len(holder)
    for start in range(len(words)):
        matched = 0
        while (
            matched < size
            and start + matched < len(words)
            and words[start + matched] == holder[matched]
        ):
            matched += 1
        if matched == size:
            return True
        if matched == 0:
            continue
        following = words[start + matched] if start + matched < len(words) else None
        if following is None:
            if matched >= _PREFIX_WORDS:
                return True
            continue
        last = start + matched == len(words) - 1
        if holder[matched].startswith(following) and _is_cut(following, matched, last):
            return True
    return False


def _is_cut(word: str, matched: int, last: bool) -> bool:
    """`word` puede ser el corte de la palabra que sigue del titular tras `matched` enteras.

    Al final del texto vale cualquier comienzo (tras 2 palabras enteras). En mitad del texto,
    una partícula ("DE", "LA"…) o una sola letra es más probablemente otra palabra que un
    corte: "JUAN PEREZ DE LA CRUZ" no es JUAN PEREZ DELGADO.
    """
    if not last and (word in _PARTICLES or len(word) < _MIN_MID_CUT):
        return False
    return matched >= _PREFIX_WORDS or len(word) >= _MIN_CUT


def _numbers_by_account(
    accounts: Sequence[AccountInfo], card_last4: Mapping[str, Sequence[str]]
) -> dict[str, frozenset[str]]:
    """Últimos 4 dígitos de cada cuenta, de su clave y de sus tarjetas.

    Se compara el último grupo de 4 dígitos como palabra entera: un fragmento de número
    ("001234567") no coincide a propósito, por falsos positivos; el número completo de la
    cuenta se compara aparte (`_full_numbers`).
    """
    numbers: dict[str, frozenset[str]] = {}
    for info in accounts:
        groups = [*re.findall(r"\d+", info.key), *card_last4.get(info.key, ())]
        digits = {g[-_NUMBER_DIGITS:] for g in groups if len(g) >= _NUMBER_DIGITS}
        if digits:
            numbers[info.key] = frozenset(digits)
    return numbers


def _full_numbers(accounts: Sequence[AccountInfo]) -> dict[str, int]:
    """Número completo de cada cuenta bancaria (los dígitos de su clave, sin ceros delante).

    Las tarjetas no tienen número en la clave; una cuenta con menos de 6 dígitos tampoco
    cuenta, porque un número tan corto aparece en cualquier referencia.
    """
    found: dict[str, int] = {}
    for info in accounts:
        digits = "".join(re.findall(r"\d", info.key.partition(":")[2].partition(":")[2]))
        if info.kind in BANK_KINDS and len(digits) >= _FULL_NUMBER_DIGITS:
            found[info.key] = int(digits)
    return found
