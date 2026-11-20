"""`Authentication-Results` (RFC 8601), parsed strictly: who vouches that the bank sent an email.

Anyone can write a From header, and anyone can add `Authentication-Results` headers of their own
below the ones the receiving provider writes. So only one header counts: the topmost one, and
only if its authserv-id is a receiver we trust (Gmail: `mx.google.com`; the caller says which,
see `AlertEmail.trusted_authserv`); otherwise nothing is trusted. Inside it:

- comments (CFWS, nested parentheses, backslash escapes) are dropped before anything is read, so
  `(dkim=pass header.d=bank)` in a comment is nothing;
- result clauses are split on ";" outside comments and quoted strings;
- a clause counts only if its method and result are exactly `dkim=pass` (or `dmarc=pass`), with
  no method version; its properties are read only from that clause;
- `header.d` / `header.i` (DKIM) and `header.from` (DMARC) must be a plain domain token (for
  `header.i`, `local@domain` or `@domain`); a quoted string or anything else makes the property
  void.

Anything malformed makes that clause (or the whole header) count for nothing: it fails closed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

MAX_HEADER = 8000  # longer headers are not read (counted as missing)
_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62})(?:\.[a-z0-9](?:[a-z0-9-]{0,62}))+")
_SPECIALS = set('();="')
_SEMI, _EQ = ";", "="


@dataclass(frozen=True)
class Verdict:
    """What the trusted receiver says: the domains with a passing DKIM signature and the
    From domains with a passing DMARC check."""

    dkim: tuple[str, ...] = ()
    dmarc_from: tuple[str, ...] = ()


NONE = Verdict()


class _Malformed(ValueError):
    pass


def _tokens(header: str) -> list[tuple[str, str]]:
    """("atom", text), ("quoted", text), (";", ";") or ("=", "="); comments and spaces are
    dropped. `_Malformed` on an unclosed comment or quoted string."""
    found: list[tuple[str, str]] = []
    i, size = 0, len(header)
    while i < size:
        char = header[i]
        if char.isspace():
            i += 1
        elif char == "(":
            depth = 0
            while i < size:
                if header[i] == "\\":
                    i += 2
                    continue
                if header[i] == "(":
                    depth += 1
                elif header[i] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            if depth != 0:
                raise _Malformed
            i += 1
        elif char == ")":
            raise _Malformed
        elif char == '"':
            text: list[str] = []
            i += 1
            while i < size and header[i] != '"':
                if header[i] == "\\" and i + 1 < size:
                    i += 1
                text.append(header[i])
                i += 1
            if i >= size:
                raise _Malformed
            found.append(("quoted", "".join(text)))
            i += 1
        elif char in (_SEMI, _EQ):
            found.append((char, char))
            i += 1
        else:
            start = i
            while i < size and not header[i].isspace() and header[i] not in _SPECIALS:
                i += 1
            found.append(("atom", header[start:i]))
    return found


def _clauses(tokens: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    parts: list[list[tuple[str, str]]] = [[]]
    for token in tokens:
        if token[0] == _SEMI:
            parts.append([])
        else:
            parts[-1].append(token)
    return parts


def authserv_id(header: str) -> str | None:
    """The header's authserv-id (lowercase), or None if it cannot be read."""
    try:
        first = _clauses(_tokens(header[:MAX_HEADER]))[0]
    except _Malformed:
        return None
    if not first or first[0][0] != "atom":
        return None
    return first[0][1].lower()


def _clause(tokens: list[tuple[str, str]]) -> tuple[str, str, dict[str, str]] | None:
    """(method, result, properties) of a resinfo clause; None if it is not well formed.
    Properties keep only atom values (`ptype.property` -> value); a quoted value is dropped."""
    if len(tokens) < 3 or [kind for kind, _ in tokens[:3]] != ["atom", _EQ, "atom"]:
        return None
    method, result = tokens[0][1].lower(), tokens[2][1].lower()
    properties: dict[str, str] = {}
    rest = tokens[3:]
    if len(rest) % 3:
        return None
    for index in range(0, len(rest), 3):
        key, equal, value = rest[index : index + 3]
        if key[0] != "atom" or equal[0] != _EQ or value[0] not in ("atom", "quoted"):
            return None
        name = key[1].lower()
        if name in properties:
            return None  # a repeated property is ambiguous: the clause counts for nothing
        if value[0] == "atom":
            properties[name] = value[1]
        else:
            properties[name] = ""  # quoted: never a domain token
    return method, result, properties


def _domain(value: str) -> str | None:
    text = value.lower().rstrip(".")
    return text if _DOMAIN.fullmatch(text) else None


def _identity_domain(value: str) -> str | None:
    """`header.i`: `local@domain` or `@domain`, the domain a plain token."""
    local, at, domain = value.rpartition("@")
    if not at or '"' in local or "\\" in local:
        return None
    return _domain(domain)


def parse(header: str) -> tuple[str | None, Verdict]:
    """(authserv-id, verdict) of one header; an unreadable header gives (None, NONE)."""
    if len(header) > MAX_HEADER:
        return None, NONE
    try:
        parts = _clauses(_tokens(header))
    except _Malformed:
        return None, NONE
    head = parts[0]
    # authserv-id, optionally followed by a numeric version, nothing else.
    if not head or head[0][0] != "atom" or len(head) > 2:  # noqa: PLR2004
        return None, NONE
    if len(head) == 2 and not (head[1][0] == "atom" and head[1][1].isdigit()):  # noqa: PLR2004
        return None, NONE
    dkim: list[str] = []
    dmarc: list[str] = []
    for tokens in parts[1:]:
        found = _clause(tokens)
        if found is None:
            continue
        method, result, properties = found
        if result != "pass":
            continue
        if method == "dkim":
            domain = (
                _domain(properties["header.d"])
                if "header.d" in properties
                else _identity_domain(properties.get("header.i", ""))
            )
            if domain is not None:
                dkim.append(domain)
        elif method == "dmarc":
            domain = _domain(properties.get("header.from", ""))
            if domain is not None:
                dmarc.append(domain)
    return head[0][1].lower(), Verdict(tuple(dkim), tuple(dmarc))


def trusted_verdict(headers: Sequence[str], trusted: Iterable[str]) -> Verdict:
    """The verdict of the topmost header, only if a trusted receiver wrote it; otherwise NONE.
    Lower headers are never read (a sender can write any of them, even one naming the trusted
    receiver), and a topmost header that does not parse is NONE too."""
    if not headers:
        return NONE
    found, verdict = parse(headers[0])
    ids = {item.lower() for item in trusted}
    return verdict if found is not None and found in ids else NONE


def covers(domain: str, wanted: str) -> bool:
    """`domain` is `wanted` or one of its subdomains."""
    return domain == wanted or domain.endswith("." + wanted)


def authenticated(verdict: Verdict, wanted: str) -> bool:
    """Both a DKIM signature and DMARC (on the From domain) pass for `wanted`."""
    target = wanted.lower()
    return any(covers(d, target) for d in verdict.dkim) and any(
        covers(d, target) for d in verdict.dmarc_from
    )
