"""Build synthetic pages from fixed-column text.

Each character takes CHAR_WIDTH points, so the column in the text becomes
the horizontal position, just like in a real PDF.
"""

from __future__ import annotations

import re
import textwrap

from michelito.parsers.common import Page, Word, group_lines

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
    """Text on the left and right-aligned cells, like a table."""
    return left.ljust(LEFT_WIDTH) + "".join(cell.rjust(CELL_WIDTH) for cell in cells)


def placed(*rows: tuple[float, str]) -> Page:
    """Like `page`, but each row carries its own height: for lines not on a fixed pitch."""
    words = [
        Word(match.group(), match.start() * CHAR_WIDTH, match.end() * CHAR_WIDTH, top)
        for top, text in rows
        for match in re.finditer(r"\S+", text)
    ]
    return group_lines(words)
