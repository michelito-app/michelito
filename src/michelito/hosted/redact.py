"""What the AI connector hides from the AI: identifiers (see `.superpowers/sdd/ai-connector.md`,
decision 4). Amounts, merchants, categories, balances and dates go through; these do not:

- **numbers that identify** (accounts, cards, contracts, references, phones): any run of five
  or more digits, also split by single spaces, dashes or slashes (and dotted phones), keeps only
  its last four (`••1234`), in values and in keys. Whole ISO days and months and day/month dates
  are left alone, and so are fields that hold the app's own ids (`KEEP_FIELDS`):
  fingerprints, which the AI needs to name a transaction back;
- **email addresses**: replaced by `[email]`; fields named like an email are dropped.

`mask` walks any decoded JSON (only strings change; numbers are amounts and ids). `unmask_key`
finds the real account key behind a masked one the AI sends back.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

KEEP_FIELDS = frozenset({"fingerprint", "fingerprints", "source_fingerprint", "color"})
DROP_FIELDS = frozenset({"email", "emails", "contact_email"})
EMAIL_MARK = "[email]"
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Kept: a whole ISO day or month (19xx or 20xx), or a day/month(/year). Masked: a dotted phone,
# or a run of five or more digits split by single spaces, dashes or slashes.
_EDGE_BEFORE = r"(?<![\d./-])"
_EDGE_AFTER = r"(?![\d./-]|\s\d)"
_ISO = r"(?:19|20)\d{2}-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?"
_SLASHED = r"(?:0?[1-9]|[12]\d|3[01])/(?:0?[1-9]|1[0-2])(?:/(?:19|20)?\d{2})?"
_NUMBERS = re.compile(
    rf"({_EDGE_BEFORE}(?:{_ISO}|{_SLASHED}){_EDGE_AFTER})"
    r"|(\d{3}\.\d{3}\.\d{4}|\d(?:[ /-]?\d){4,})"
)


def _hide_number(match: re.Match[str]) -> str:
    if match.group(1):
        return match.group(1)
    digits = re.sub(r"\D", "", match.group(2))
    return "••" + digits[-4:]


def mask_text(text: str) -> str:
    return _NUMBERS.sub(_hide_number, _EMAIL.sub(EMAIL_MARK, text))


def mask(value: Any) -> Any:
    """A copy of `value` with identifiers hidden (never changes the given value)."""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, list):
        return [mask(v) for v in value]
    if isinstance(value, dict):
        return {
            mask(k): (v if k in KEEP_FIELDS else mask(v))
            for k, v in value.items()
            if k not in DROP_FIELDS
        }
    return value


def unmask_key(given: str, keys: Iterable[str]) -> str | None:
    """The real key whose masked form is `given` (or that is `given`); None if no single one."""
    found = {k for k in keys if k == given or mask_text(k) == given}
    return next(iter(found)) if len(found) == 1 else None
