"""Registro de parsers: cada uno reconoce y lee un tipo de estado de cuenta."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from finanzas.parsers import (
    banreservas_cuenta,
    bhd_ahorro,
    bhd_tc,
    popular_cuenta,
    popular_historico,
    popular_tc,
    popular_web,
)
from finanzas.parsers.common import Page, Statement


class StatementParser(Protocol):
    NAME: str

    def matches(self, pages: tuple[Page, ...]) -> bool: ...

    def parse(self, pages: tuple[Page, ...]) -> Statement: ...


# Un parser cuyo PDF trae varios estados seguidos expone además `split(pages)`, que lo corta
# en tramos de páginas; `parse` interpreta un tramo (ver `ingest`). Puede exponer también
# `label(pages)`: el corte de un tramo que `parse` no pudo leer, si se encuentra.
Splitter = Callable[[tuple[Page, ...]], tuple[tuple[Page, ...], ...]]
Labeler = Callable[[tuple[Page, ...]], str | None]


PARSERS: tuple[StatementParser, ...] = (
    popular_tc,
    bhd_tc,
    bhd_ahorro,
    popular_cuenta,
    popular_historico,
    popular_web,
    banreservas_cuenta,
)  # type: ignore[assignment]


def detect(pages: tuple[Page, ...]) -> StatementParser | None:
    return next((parser for parser in PARSERS if parser.matches(pages)), None)


def splitter(parser: StatementParser) -> Splitter | None:
    """`split` del parser si su PDF trae varios estados; None si trae uno."""
    found: Splitter | None = getattr(parser, "split", None)
    return found


def labeler(parser: StatementParser) -> Labeler | None:
    """`label` del parser (etiqueta de un tramo que no se pudo interpretar), si la tiene."""
    found: Labeler | None = getattr(parser, "label", None)
    return found
