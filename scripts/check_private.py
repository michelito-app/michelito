"""Fails if the repository tree has anything shaped like personal data.

Usage: `uv run python scripts/check_private.py [ROOT]` (by default, this repository's root).
It checks the files git would include (tracked ones and new ones that are not ignored) and
looks for:

- card, account, national ID or phone numbers: 9 digits or more, contiguous or in groups joined
  by "-" or "." (accounts `XXX-XXXXXX-X`, national IDs `XXX-XXXXXXX-X`, cards with dots), even
  when glued to letters (`Statement<number>.pdf`); cards printed in space-separated groups
  (4-4-4-4, AMEX 4-6-5) if they pass Luhn; and Dominican phone numbers (809/829/849) in any
  format. Numbers with an obviously made-up shape are let through (`looks_invented`);
- the last 4 digits of a card or account ("···NNNN", "*NNNN", "XXXX NNNN", "…NNNN",
  "•••• NNNN", and the Spanish "ending in NNNN" that statements print) that are not in
  `INVENTED_LAST4`;
- emails from any domain that is not in `ALLOWED_EMAIL_DOMAINS`;
- paths of a user's home folder: Linux and macOS (`/home/<user>`, `/Users/<user>`), root's,
  Windows' (under `C:` and `Users`) and `~user` followed by a slash.

It does not detect names of people, merchants or amounts: that is still a manual review.

Exceptions are explicit and have a reason: `ALLOWED_FILES` (only the number search is skipped;
paths and emails are still checked), `ALLOWED_NUMBERS`, `INVENTED_LAST4` and
`ALLOWED_EMAIL_DOMAINS`. Before adding one, confirm the value is made up; if it is real,
replace it with a made-up one. The report never prints the value it found (CI logs are
public): only file, line, column and kind. Exits with 1 if it found anything.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# Files where numbers are not searched (paths and emails are), with the reason.
ALLOWED_FILES: dict[str, str] = {
    "uv.lock": "checksums and sizes of PyPI packages",
    "frontend/package-lock.json": "checksums of npm packages",
    "LICENSE": "official text of the AGPL-3.0",
    "tests/fixtures/schema_v17.sql": "hex fingerprints of synthetic rows (tests/samples.py)",
    "tests/fixtures/schema_v17_expected.json": "hex fingerprints of the same synthetic rows",
    "tests/fixtures/schema_v18_shared.sql": "hex fingerprints of synthetic rows (tests/samples.py)",
    "tests/fixtures/schema_v18_shared_expected.json": "hex fingerprints of the same synthetic rows",
}

# Long numbers that belong to nobody, with the reason.
ALLOWED_NUMBERS: dict[str, str] = {
    "1792005355": "Unix timestamp of a test email (tests/test_gmail.py)",
    "1792005355000": "the same timestamp in milliseconds (tests/test_gmail.py)",
    "0099887766": "made-up own account in holders.txt (tests/test_transfers.py)",
    "0088001234568": "made-up LBTR account (tests/test_transfers.py)",
    "880012345670": "fragment of a made-up account (tests/test_transfers.py)",
    "0007001234567": "made-up account (tests/test_transfers.py)",
    "2026012345": "made-up payroll reference (tests/test_investments.py)",
    "00000000667": "made-up reference (tests/test_investments.py)",
    "0088001234567": "made-up LBTR account (tests/test_categories.py)",
    "0088009999999": "made-up LBTR account (tests/test_categories.py)",
    "88001234567": "made-up LBTR account (tests/test_categories.py)",
    "7001234567": "made-up reference (tests/test_categories.py)",
    "0012345678901": "made-up plane ticket (tests/test_categories.py)",
    "100200300": "made-up savings account (frontend tests)",
    "400500600": "made-up checking account (frontend tests)",
    "555666777": "made-up digital account (tests/samples.py)",
}

# Made-up last 4 digits used by the tests and the examples.
INVENTED_LAST4: frozenset[str] = frozenset(
    {"0000", "0300", "0600", "1111", "1234", "4242", "4567", "5151", "7770", "9991", "9999"}
)

# Email domains that may appear: the ones reserved for examples, GitHub's private address, the
# public senders of the banks and pension funds (config.DEFAULT_SOURCES) and the license's.
# A subdomain of one of these is fine too.
ALLOWED_EMAIL_DOMAINS: frozenset[str] = frozenset(
    {
        "example.com",
        "example.org",
        "example.net",
        "example",  # reserved TLD: bank.example
        "ejemplo.com",  # spanish-data: marker domain of the synthetic statements (tests/samples.py)
        "users.noreply.github.com",
        "popularenlinea.com",
        "bhd.com.do",
        "afpreservas.com.do",
        "afpsiembra.com",
        "afpcrecer.com.do",
        "gnu.org",
        "fsf.org",
        "auth.michelito.app",  # the project's own sender for sign-in codes (hosted mode)
    }
)

# 9 digits or more, contiguous or in groups joined by "-" or "."; only the boundary with another
# digit counts, so `Statement<number>.pdf` or `acct_<number>` are seen too.
_JOINED = re.compile(r"(?<![\d.-])\d+(?:[.-]\d+)*(?![\d]|[.-]\d)")
# Cards printed with spaces: 4-4-4-4 and AMEX 4-6-5 (confirmed with Luhn).
_SPACED_CARD = re.compile(r"(?<!\d)(?<!\d )(?:\d{4}(?: \d{4}){3}|\d{4} \d{6} \d{5})(?! ?\d)")
_DR_PHONE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?(?:809|829|849)\)?[ .-]?(\d{3})[ .-]?\d{4}(?!\d)")
_FICTION_PHONE = re.compile(r"1?(?:809|829|849)555\d{4}")  # 809-555-0000 and the like
_ID_CARD = re.compile(r"(?<!\d)\d{3}-\d{7}-\d(?!\d)")  # Dominican national ID
_DECIMAL = re.compile(r"\d+\.\d{2}")  # an amount with cents is not an account
# A commit sha (40 hex) or a sha256 digest (64 hex) in lowercase: GitHub actions and Docker
# images are pinned this way, and their runs of digits belong to nobody.
_HEX_DIGEST = re.compile(r"(?<![0-9A-Za-z])(?:[0-9a-f]{64}|[0-9a-f]{40})(?![0-9A-Za-z])")
_MIN_DIGITS = 9
# An amount in cents (`total_cents: 127449012`) is not an account.
_CENTS_BEFORE = re.compile(r"cents[\"']?\s*[:=]\s*$")
# spanish-data: begin ("terminada en": "ending in", as statements print it)
_LAST4 = re.compile(
    r"(?:···|…|•+ ?|\*+|[xX]{4}[ -]?|termina(?:da|do)? en )(\d{4})(?!\d)", re.IGNORECASE
)
# spanish-data: end
_EMAIL = re.compile(r"[\w.+-]+@((?:[\w-]+\.)+[a-z]{2,}|[\w-]+\.example)\b", re.IGNORECASE)
_HOME = re.compile(
    r"/(?:home|Users)/(?!<)[A-Za-z0-9._-]+|/(?:root)/|[A-Za-z]:\\+(?:Users)\\+"
    r"|(?<![\w/])~[A-Za-z][\w.-]*/"
)
_ASCENDING = "01234567890123456789"
_DESCENDING = _ASCENDING[::-1]
_DATE = re.compile(r"^(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])$")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    column: int
    kind: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.column}: {self.kind}"


def looks_invented(digits: str) -> bool:
    """Does it have a shape nobody would use as a real number?

    A single repeated digit, a staircase (123456789, 987654321), a YYYYMMDD date, or a number
    that, without its zeros, has 2 digits or fewer, is a repeated digit or a staircase
    (0000000066, 0000000000013, 1200000)."""
    if digits in ALLOWED_NUMBERS or _DATE.match(digits):
        return True
    if len(digits.replace("0", "")) <= 2:
        return True
    for candidate in (digits, digits.replace("0", "")):
        if len(set(candidate)) == 1:
            return True
        if candidate in _ASCENDING or candidate in _DESCENDING:
            return True
    return False


def luhn_valid(digits: str) -> bool:
    """The checksum of card numbers (every card passes it)."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char) * (2 if index % 2 else 1)
        total += value - 9 if value > 9 else value
    return total % 10 == 0


def _kind(digits: str) -> str:
    return "card-like number" if 13 <= len(digits) <= 19 else "account-like number"


def _numbers(line: str) -> Iterator[tuple[int, int, str]]:
    """(start, end, kind) of each suspicious number in the line."""
    for match in _DR_PHONE.finditer(line):
        if match.group(1) != "555":  # 555: the exchange of fictional phone numbers
            yield match.start(), match.end(), "phone number"
    for match in _ID_CARD.finditer(line):
        if not looks_invented(match.group().replace("-", "")):
            yield match.start(), match.end(), "national ID"
    for match in _SPACED_CARD.finditer(line):
        digits = match.group().replace(" ", "")
        if luhn_valid(digits) and not looks_invented(digits):
            yield match.start(), match.end(), "card-like number"
    digests = [m.span() for m in _HEX_DIGEST.finditer(line)]
    for match in _JOINED.finditer(line):
        if any(a <= match.start() and match.end() <= b for a, b in digests):
            continue
        text = match.group()
        digits = re.sub(r"\D", "", text)
        if len(digits) < _MIN_DIGITS or _DECIMAL.fullmatch(text):
            continue
        if looks_invented(digits) or _CENTS_BEFORE.search(line[: match.start()]):
            continue
        if _FICTION_PHONE.fullmatch(digits):
            continue
        yield match.start(), match.end(), _kind(digits)


def _email_allowed(domain: str) -> bool:
    domain = domain.lower()
    return any(domain == d or domain.endswith("." + d) for d in ALLOWED_EMAIL_DOMAINS)


def scan_text(path: str, text: str, *, numbers: bool = True) -> Iterator[Finding]:
    for number, line in enumerate(text.splitlines(), start=1):
        if numbers:
            seen: list[tuple[int, int]] = []
            for start, end, kind in _numbers(line):
                if any(start < b and a < end for a, b in seen):
                    continue  # already reported by a more precise pattern
                seen.append((start, end))
                yield Finding(path, number, start + 1, kind)
            for match in _LAST4.finditer(line):
                if match.group(1) not in INVENTED_LAST4:
                    yield Finding(path, number, match.start() + 1, "last 4 digits")
        for match in _EMAIL.finditer(line):
            if not _email_allowed(match.group(1)):
                yield Finding(path, number, match.start() + 1, "email")
        for match in _HOME.finditer(line):
            yield Finding(path, number, match.start() + 1, "user home folder path")


def repository_files(root: Path) -> list[str]:
    """What git would publish: what is tracked and what is new and not ignored."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    ).stdout.decode()
    return sorted({name for name in listed.split("\0") if name})


def scan(root: Path, files: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for name in files:
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(Finding(name, 0, 0, "binary file: review it by hand or remove it"))
            continue
        findings.extend(scan_text(name, text, numbers=name not in ALLOWED_FILES))
    return findings


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent
    files = repository_files(root)
    findings = scan(root, files)
    for finding in findings:
        print(finding)
    if findings:
        print(
            f"\n{len(findings)} possible personal data. Replace them with made-up values or, if "
            "they already are, add them to the allowlists in scripts/check_private.py with a "
            "reason.",
            file=sys.stderr,
        )
        return 1
    print(f"No personal data in sight ({len(files)} files).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
