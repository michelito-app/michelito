"""Commands for the analysis with Claude Code (see the README on the month's analysis).

    michelito analysis YYYY-MM [--accounts k1,k2] [--format markdown|json]
    michelito insight save YYYY-MM [--file F] [--accounts k1,k2]   (without a file: stdin)
    michelito insight show YYYY-MM
    michelito insight delete YYYY-MM

None of them reads the keyring: only the database and the holders.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from michelito import cash_pass, config, db, dossier
from michelito.analysis import insights, transfers

FORMATS = ("markdown", "json")
MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def month_name(month: str) -> str:
    """`YYYY-MM` as "September 2026", for terminal output."""
    return f"{MONTH_NAMES[int(month[5:7]) - 1]} {month[:4]}"


def _month(text: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", text):
        raise argparse.ArgumentTypeError(f"invalid month '{text}'; use YYYY-MM")
    return text


def _accounts(text: str) -> list[str]:
    keys = sorted({key.strip() for key in text.split(",") if key.strip()})
    if not keys:
        raise argparse.ArgumentTypeError("give at least one account")
    return keys


def add_commands(commands: Any) -> None:
    """Add `analysis` and `insight` to the `michelito` subcommands."""
    analysis = commands.add_parser(
        "analysis", help="print a month's dossier to analyze it with Claude Code"
    )
    analysis.add_argument("month", type=_month, metavar="YYYY-MM")
    analysis.add_argument(
        "--accounts", type=_accounts, metavar="K1,K2", help="account keys, comma-separated"
    )
    analysis.add_argument("--format", choices=FORMATS, default="markdown")
    analysis.set_defaults(handler=_cmd_analysis)

    insight = commands.add_parser("insight", help="save, show or delete a month's analysis")
    actions = insight.add_subparsers(required=True)
    save = actions.add_parser("save", help="save the analysis (Markdown, up to 4000)")
    save.add_argument("month", type=_month, metavar="YYYY-MM")
    save.add_argument(
        "--file", type=Path, metavar="FILE", help="file with the analysis; without it, stdin"
    )
    save.add_argument(
        "--accounts",
        type=_accounts,
        metavar="K1,K2",
        help="the analyzed accounts (all by default)",
    )
    save.set_defaults(handler=_cmd_save)
    view = actions.add_parser("show", help="show the saved analysis")
    view.add_argument("month", type=_month, metavar="YYYY-MM")
    view.set_defaults(handler=_cmd_view)
    remove = actions.add_parser("delete", help="delete the saved analysis")
    remove.add_argument("month", type=_month, metavar="YYYY-MM")
    remove.set_defaults(handler=_cmd_delete)


def _open(paths: config.Paths) -> sqlite3.Connection:
    """The database, with the cash pass already run (`cash_pass`): the same figures as the
    board."""
    config.ensure_private_dir(paths.root)
    conn = db.connect(paths.database)
    cash_pass.run(conn, paths.holders)
    return conn


def _dossier(
    conn: sqlite3.Connection, paths: config.Paths, month: str, accounts: list[str] | None
) -> dossier.Dossier:
    return dossier.build(
        conn, month, accounts=accounts, holders=transfers.load_holders(paths.holders)
    )


def _fail(message: str) -> int:
    print(f"Error: {message}", file=sys.stderr)
    return 1


def _cmd_analysis(args: argparse.Namespace, paths: config.Paths) -> int:
    with closing(_open(paths)) as conn:
        try:
            built = _dossier(conn, paths, args.month, args.accounts)
        except ValueError as exc:
            return _fail(str(exc))
        except LookupError:
            return _fail(f"{month_name(args.month)} has no data")
    if args.format == "json":
        body = {"data_hash": built.data_hash, "data": built.data}
        print(json.dumps(body, ensure_ascii=False, indent=2))
    else:
        print(built.markdown)
    return 0


def _read_text(source: Path | None) -> str:
    if source is None:
        if sys.stdin.isatty():
            raise ValueError(
                "the analysis is missing: pass it with --file F or on standard input "
                "(michelito insight save YYYY-MM < analysis.md)"
            )
        return sys.stdin.read()
    if not source.is_file():
        raise ValueError(f"{source} does not exist")
    return source.read_text(encoding="utf-8")


def _from_header(text: str, month: str, given: list[str] | None) -> tuple[str, list[str] | None]:
    """Remove the dossier header if it came with the analysis and take the accounts from it.

    ValueError if it is from another month or its accounts are not the ones in `--accounts`."""
    pasted = dossier.split_header(text, month)
    if not pasted.has_header:
        return text, given
    if given is not None and given != pasted.accounts:
        raise ValueError(
            "the accounts in --accounts are not the ones of the analyzed dossier; use the same "
            "ones as in `michelito analysis`"
        )
    return pasted.text, pasted.accounts


def _cmd_save(args: argparse.Namespace, paths: config.Paths) -> int:
    """Save the analysis with the hash of the dossier for the same accounts as `analysis`."""
    try:
        raw, accounts = _from_header(_read_text(args.file), args.month, args.accounts)
        text = insights.clean_text(raw)
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        return _fail(str(exc))
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with closing(_open(paths)) as conn:
        try:
            built = _dossier(conn, paths, args.month, accounts)
        except ValueError as exc:
            return _fail(str(exc))
        except LookupError:
            return _fail(f"{month_name(args.month)} has no data: there is nothing to analyze")
        with conn:
            insights.save(conn, args.month, text, built.data_hash, accounts, now)
    print(f"Analysis for {month_name(args.month)} saved ({len(text)} characters).")
    return 0


def _cmd_view(args: argparse.Namespace, paths: config.Paths) -> int:
    with closing(_open(paths)) as conn:
        found = insights.get(conn, args.month)
        if found is None:
            return _fail(f"There is no analysis for {month_name(args.month)}")
        try:
            current = _dossier(conn, paths, args.month, list(found.accounts or ()) or None)
            changed = not insights.is_fresh(
                conn, found, current.data_hash, lambda: current.older_hashes
            )
        except (ValueError, LookupError):
            changed = True
    print(found.text)
    print(f"\n— Saved on {found.updated_at[:10]}.", end="")
    print(" The data changed since this analysis." if changed else "")
    return 0


def _cmd_delete(args: argparse.Namespace, paths: config.Paths) -> int:
    with closing(_open(paths)) as conn, conn:
        removed = insights.delete(conn, args.month)
    if not removed:
        return _fail(f"There is no analysis for {month_name(args.month)}")
    print(f"Analysis for {month_name(args.month)} deleted.")
    return 0
