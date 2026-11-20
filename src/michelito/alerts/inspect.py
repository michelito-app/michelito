"""Check real alert emails against the parsers without saving anything or showing any value.

    uv run python -m michelito.alerts.inspect < alert.eml     # or: michelito alert-check
    uv run python -m michelito.alerts.inspect a.eml b.eml

Each message is read in memory (`alerts.from_bytes`) and the report says only its structure:
which parser recognized it, the table layout, whether each field was found and understood,
whether the status word is known and, if it failed, the data-free failure fingerprint. It never
prints an amount, a name, a merchant, a date or the card digits, and writes nothing to disk.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from michelito import alerts
from michelito.alerts.common import FIELDS, AlertParseError, failure_fingerprint

Report = dict[str, object]


def describe(raw: bytes) -> Report:
    email = alerts.from_bytes(raw, message_id="inspected")
    parser = alerts.detect(email)
    report: Report = {
        "sender_domain": email.sender_domain,
        "has_html": bool(email.html.strip()),
        "has_text": bool(email.text.strip()),
        "parser": None if parser is None else parser.NAME,
    }
    if parser is None:
        return {**report, "parsed": False, "fields": dict.fromkeys(FIELDS, False)}
    structure = getattr(parser, "structure", None)
    if structure is not None:
        layout, present, known = structure(email)
        report |= {"layout": layout, "fields": present, "status_known": known}
    try:
        parser.parse(email)
    except AlertParseError as error:
        failure = failure_fingerprint(email, parser.NAME, error)
        return {**report, "parsed": False, "failure": failure}
    return {**report, "parsed": True}


def _text(name: str, report: Report) -> str:
    lines = [f"{name}:"]
    for key, value in report.items():
        if isinstance(value, dict):
            lines.append(f"  {key}:")
            lines.extend(f"    {k}: {_word(v)}" for k, v in value.items())
        else:
            lines.append(f"  {key}: {_word(value)}")
    return "\n".join(lines)


def _word(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return "-" if value is None else str(value)


def main(argv: Sequence[str] | None = None, stdin: bytes | None = None) -> int:
    """Print the structure of each message (files, or `-`/nothing for standard input). Exit 1
    if any could not be parsed."""
    names = list(sys.argv[1:] if argv is None else argv) or ["-"]
    failed = False
    for name in names:
        if name == "-":
            raw = sys.stdin.buffer.read() if stdin is None else stdin
        else:
            raw = Path(name).read_bytes()
        report = describe(raw)
        failed = failed or not report["parsed"]
        print(_text("stdin" if name == "-" else Path(name).name, report))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
