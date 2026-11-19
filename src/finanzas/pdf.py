"""Lectura de PDFs (con o sin clave) a líneas de palabras con posición.

El PDF se abre en memoria; la versión descifrada nunca se escribe a disco.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pdfplumber

from finanzas.parsers.common import Page, Word, group_lines


def read_pages(path: Path, password: str) -> tuple[Page, ...]:
    with pdfplumber.open(path, password=password) as document:
        return tuple(group_lines(_words(page)) for page in document.pages)


def _words(page: Any) -> list[Word]:
    return [
        Word(str(w["text"]), float(w["x0"]), float(w["x1"]), float(w["top"]))
        for w in page.extract_words()
    ]
