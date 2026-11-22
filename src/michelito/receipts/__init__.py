"""Merchant-email readers: each one recognizes and reads one kind of receipt email.

Like the alert parsers, a reader exposes `NAME`, `matches(email)` and `parse(email)`, where
`email` is an `alerts.common.AlertEmail`; `parse` returns the email's receipts (an order
confirmation may hold several orders).
"""

from __future__ import annotations

from typing import Protocol

from michelito.alerts.common import AlertEmail
from michelito.receipts import amazon
from michelito.receipts.common import FIELDS, SUMMARY_MAX, Receipt

__all__ = [
    "FIELDS",
    "READERS",
    "SENDERS",
    "SUMMARY_MAX",
    "Receipt",
    "ReceiptReader",
    "by_name",
    "detect",
]


class ReceiptReader(Protocol):
    @property
    def NAME(self) -> str: ...  # noqa: N802 (read-only, like the readers' own field)

    def matches(self, email: AlertEmail) -> bool: ...

    def parse(self, email: AlertEmail) -> tuple[Receipt, ...]: ...


READERS: tuple[ReceiptReader, ...] = amazon.READERS
# The addresses the readers take mail from (the forwarding inbox lets only these in).
SENDERS: frozenset[str] = frozenset(reader.sender for reader in amazon.READERS)


def detect(email: AlertEmail) -> ReceiptReader | None:
    return next((reader for reader in READERS if reader.matches(email)), None)


def by_name(name: str | None) -> ReceiptReader | None:
    return next((reader for reader in READERS if name == reader.NAME), None)
