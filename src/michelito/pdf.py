"""Reads PDFs (with or without a password) into lines of positioned words.

The PDF is opened in memory; the decrypted version is never written to disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pdfplumber

from michelito.parsers.common import Page, Word, group_lines


def read_pages(path: Path, password: str) -> tuple[Page, ...]:
    with pdfplumber.open(path, password=password) as document:
        return tuple(group_lines(_words(page)) for page in document.pages)


def _words(page: Any) -> list[Word]:
    return [
        Word(str(w["text"]), float(w["x0"]), float(w["x1"]), float(w["top"]))
        for w in page.extract_words()
    ]
