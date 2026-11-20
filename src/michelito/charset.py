"""Decoding an email part's bytes without ever inserting replacement characters.

Banks declare a charset in the part's Content-Type, and some declare none or a wrong one (an
accented word sent as windows-1252 and read as UTF-8 gets a replacement character). Each
candidate is tried strictly, in order: the declared charset, UTF-8, windows-1252 and, as the
last resort that never fails, ISO-8859-1.
"""

from __future__ import annotations

import codecs
import re

_FALLBACKS = ("utf-8", "cp1252", "latin-1")
_CHARSET = re.compile(r"""charset\s*=\s*["']?([A-Za-z0-9._:-]+)""", re.IGNORECASE)


def declared(content_type: str | None) -> str | None:
    """The charset named in a Content-Type header value, if any."""
    found = _CHARSET.search(content_type or "")
    return None if found is None else found[1]


def decode(data: bytes, charset: str | None = None) -> str:
    """`data` as text: the declared charset if it decodes cleanly, else the fallbacks."""
    candidates = [charset] if charset else []
    for name in (*candidates, *_FALLBACKS):
        try:
            codecs.lookup(name)
            return data.decode(name)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("latin-1")  # unreachable: latin-1 decodes every byte
