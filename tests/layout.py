"""Construye páginas sintéticas a partir de texto con columnas fijas.

Cada carácter ocupa CHAR_WIDTH puntos, así que la columna en el texto se
convierte en posición horizontal, igual que en un PDF real.
"""

from __future__ import annotations

import re
import textwrap

from finanzas.parsers.common import Page, Word, group_lines

CHAR_WIDTH = 5.0
ROW_HEIGHT = 10.0
LEFT_WIDTH = 56
CELL_WIDTH = 12


def page(*rows: str) -> Page:
    words = [
        Word(
            match.group(), match.start() * CHAR_WIDTH, match.end() * CHAR_WIDTH, index * ROW_HEIGHT
        )
        for index, text in enumerate(rows)
        for match in re.finditer(r"\S+", text)
    ]
    return group_lines(words)


def block(text: str) -> tuple[str, ...]:
    return tuple(textwrap.dedent(text).strip("\n").splitlines())


def row(left: str, *cells: str) -> str:
    """Texto a la izquierda y celdas alineadas a la derecha, como una tabla."""
    return left.ljust(LEFT_WIDTH) + "".join(cell.rjust(CELL_WIDTH) for cell in cells)


def placed(*rows: tuple[float, str]) -> Page:
    """Como `page`, pero cada renglón lleva su altura: para líneas que no van a paso fijo."""
    words = [
        Word(match.group(), match.start() * CHAR_WIDTH, match.end() * CHAR_WIDTH, top)
        for top, text in rows
        for match in re.finditer(r"\S+", text)
    ]
    return group_lines(words)
