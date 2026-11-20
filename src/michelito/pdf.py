"""Reads PDFs (with or without a password) into lines of positioned words.

The PDF is opened in memory; the decrypted version is never written to disk.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect

from michelito.parsers.common import Page, Word, group_lines


def read_pages(path: Path, password: str) -> tuple[Page, ...]:
    with pdfplumber.open(path, password=password) as document:
        return tuple(group_lines(_words(page)) for page in document.pages)


def read_bytes(data: bytes, password: str) -> tuple[Page, ...]:
    """The same, from bytes already in memory (an upload): nothing is written to disk."""
    with pdfplumber.open(io.BytesIO(data), password=password) as document:
        return tuple(group_lines(_words(page)) for page in document.pages)


def wrong_password(error: BaseException) -> bool:
    """Whether opening failed because the password is missing or wrong."""
    seen: BaseException | None = error
    while seen is not None:
        if isinstance(seen, PDFPasswordIncorrect) or any(
            isinstance(arg, PDFPasswordIncorrect) for arg in seen.args
        ):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def _words(page: Any) -> list[Word]:
    return [
        Word(str(w["text"]), float(w["x0"]), float(w["x1"]), float(w["top"]))
        for w in page.extract_words()
    ]
