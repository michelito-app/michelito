"""Parser registry: each one recognizes and reads one kind of bank statement."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from michelito.parsers import (
    banreservas_account,
    bhd_card,
    bhd_savings,
    popular_account,
    popular_card,
    popular_history,
    popular_web,
)
from michelito.parsers.common import Page, Statement


class StatementParser(Protocol):
    NAME: str

    def matches(self, pages: tuple[Page, ...]) -> bool: ...

    def parse(self, pages: tuple[Page, ...]) -> Statement: ...


# A parser whose PDF holds several statements in a row also exposes `split(pages)`, which cuts
# it into page ranges ("parts"); `parse` parses one part (see `ingest`). It may also expose
# `label(pages)`: the closing date of a part that `parse` could not read, if it can be found.
Splitter = Callable[[tuple[Page, ...]], tuple[tuple[Page, ...], ...]]
Labeler = Callable[[tuple[Page, ...]], str | None]


PARSERS: tuple[StatementParser, ...] = (
    popular_card,
    bhd_card,
    bhd_savings,
    popular_account,
    popular_history,
    popular_web,
    banreservas_account,
)  # type: ignore[assignment]


def detect(pages: tuple[Page, ...]) -> StatementParser | None:
    return next((parser for parser in PARSERS if parser.matches(pages)), None)


def splitter(parser: StatementParser) -> Splitter | None:
    """The parser's `split` if its PDF holds several statements; None if it holds one."""
    found: Splitter | None = getattr(parser, "split", None)
    return found


def labeler(parser: StatementParser) -> Labeler | None:
    """The parser's `label` (the label of a part that could not be parsed), if it has one."""
    found: Labeler | None = getattr(parser, "label", None)
    return found
