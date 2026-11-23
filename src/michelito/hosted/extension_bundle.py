"""The browser extension as the zip Settings offers (loaded unpacked, in developer mode).

Its source is the `extension/` folder next to this module: only the files in `SUFFIXES` go in,
sorted and with a fixed date, so the same source always gives the same bytes (`bundle`, built
once per process). The manifest's public `key` fixes the extension's id wherever it is
unpacked, and with it the only origin the extension routes accept (`extension_id`). The icons
are drawn when the zip is built (`hosted.extension_icon`).
"""

from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from functools import cache
from pathlib import Path

from michelito.hosted import extension_icon

SOURCE = Path(__file__).with_name("extension")
FILENAME = "michelito-amazon.zip"
SUFFIXES = frozenset({".json", ".js", ".html", ".css"})
_DATE = (2026, 1, 1, 0, 0, 0)
_ID_LETTERS = "abcdefghijklmnop"


def extension_id(public_key: str) -> str:
    """Chrome's id for a manifest `key`: the first 128 bits of the SHA-256 of the DER public
    key, each hexadecimal digit written as a letter from a to p."""
    digest = hashlib.sha256(base64.b64decode(public_key)).hexdigest()[:32]
    return "".join(_ID_LETTERS[int(digit, 16)] for digit in digest)


def _files() -> list[Path]:
    return sorted(
        path
        for path in SOURCE.rglob("*")
        if path.is_file()
        and path.suffix in SUFFIXES
        and not any(part.startswith(".") for part in path.relative_to(SOURCE).parts)
    )


@cache
def bundle() -> bytes:
    buffer = io.BytesIO()
    entries = [(path.relative_to(SOURCE).as_posix(), path.read_bytes()) for path in _files()]
    entries += [
        (f"icons/icon{size}.png", extension_icon.png(size)) for size in extension_icon.SIZES
    ]
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(entries):
            info = zipfile.ZipInfo(name, _DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return buffer.getvalue()
