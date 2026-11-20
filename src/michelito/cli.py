"""Command line.

    michelito auth [--client-secrets FILE]   authorize Gmail (read-only)
    michelito secret pdf-password            save the PDFs' password
    michelito sync [--notify] [--retry]      download, parse and report
    michelito extract [--source NAME]        only download
    michelito parse [--retry]                only parse what is pending
    michelito import [--currency C] PDF...   import statements downloaded by hand
    michelito report                         only show the coverage
    michelito spending [--months N]          spending summary in the terminal
    michelito board [--port N]               local web board on 127.0.0.1
    michelito rates [--set YYYY-MM VALUE]    BCRD monthly dollar rate, or a rate by hand
    michelito analysis YYYY-MM [--accounts K]     the month's dossier, to analyze with Claude Code
    michelito insight save|show|delete YYYY-MM    the month's saved analysis
    michelito log [--json] [--since DATE]         the changes made from the board
    michelito new [--json] [--mark-reviewed]      transactions not reviewed yet
    michelito demo [--port N] [--data DIR]        public demo with made-up data
    michelito feedback [--json] [--usage]         the demo's feedback and usage
    michelito hosted [--port N] [--data DIR]      hosted mode: accounts and email sign-in
    michelito invite EMAIL [--data DIR]           invite one email to hosted mode
    michelito rotate-master-key --new PATH        re-wrap hosted data keys under a new master key
    michelito export-account --out FILE           the local database, to import into hosted mode
    michelito import-account --email E --from F   a hosted account from that export (server)
    michelito verify-import --months M1,M2,M3     figures to compare the local and hosted data
    michelito backup | restore | ops-check        hosted backups (R2), restore, failure email
    michelito alert-check [EML...]                a bank alert's structure (stdin; no values)

`sync` and `report` exit with code 1 if there are alerts, 2 if a secret is missing.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from collections import Counter
from collections.abc import Sequence
from contextlib import closing, suppress
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from michelito import (
    cli_demo,
    cli_hosted,
    cli_insights,
    cli_log,
    cli_ops,
    config,
    db,
    extract,
    importer,
    ingest,
    migrations_v19,
    pdf,
    report,
    sources,
    vault,
)
from michelito.alerts import inspect as alert_inspect
from michelito.analysis import bcrd, rates, spending, transfers
from michelito.analysis import report as spending_report
from michelito.gmail import authorize, build_client
from michelito.i18n import t
from michelito.parsers import popular_web
from michelito.web.accounts import DuePayment, account_views, due_text, upcoming_payments


def main(argv: Sequence[str] | None = None) -> int:
    os.umask(0o077)  # everything created (folders, database, journal) is for the user only
    args = _parser().parse_args(argv)
    paths = config.default_paths()
    if cli_demo.demo_mode():
        return _demo_only(args, paths)
    if cli_ops.hosted_mode() and not getattr(args, "server", False):
        print(f"With {cli_ops.MODE_ENV}=hosted only the server commands work.", file=sys.stderr)
        return 2
    try:
        return args.handler(args, paths)
    except (vault.MissingSecretError, sources.SourcesError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except migrations_v19.MigrationMismatch as exc:
        print(t("core.migration_mismatch", detail=str(exc)), file=sys.stderr)
        return 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="michelito", description="Account statements to SQLite")
    commands = parser.add_subparsers(required=True)

    auth = commands.add_parser("auth", help="authorize read-only access to Gmail")
    auth.add_argument(
        "--client-secrets", type=Path, help="the OAuth client JSON; only needed the first time"
    )
    auth.set_defaults(handler=_cmd_auth)

    secret = commands.add_parser("secret", help="save a secret in the keyring")
    secret.add_argument("name", choices=(vault.PDF_PASSWORD,))
    secret.set_defaults(handler=_cmd_secret)

    sync = commands.add_parser("sync", help="download, parse and report")
    sync.add_argument("--notify", action="store_true", help="desktop notification when done")
    sync.add_argument("--retry", action="store_true", help="retry failed documents")
    sync.set_defaults(handler=_cmd_sync)

    extract_cmd = commands.add_parser("extract", help="only download from Gmail")
    extract_cmd.add_argument(
        "--source", metavar="NAME", help="only this source (from sources.toml or the defaults)"
    )
    extract_cmd.set_defaults(handler=_cmd_extract)

    parse = commands.add_parser("parse", help="only parse the pending documents")
    parse.add_argument("--retry", action="store_true", help="retry failed documents")
    parse.set_defaults(handler=_cmd_parse)

    import_cmd = commands.add_parser("import", help="import PDF statements downloaded by hand")
    import_cmd.add_argument(
        "--currency",
        type=str.upper,
        choices=popular_web.CURRENCIES,
        help='currency of the portal printouts (they print a bare "$"); remembered for the account',
    )
    import_cmd.add_argument("pdfs", nargs="+", type=Path, metavar="PDF")
    import_cmd.set_defaults(handler=_cmd_import)

    commands.add_parser("report", help="show the coverage").set_defaults(handler=_cmd_report)

    spending_cmd = commands.add_parser("spending", help="spending summary in the terminal")
    spending_cmd.add_argument(
        "--months", type=_positive_int, default=12, help="complete months to analyze (12)"
    )
    spending_cmd.set_defaults(handler=_cmd_spending)

    board = commands.add_parser("board", help="interactive board in the browser (local)")
    board.add_argument(
        "--port", type=_positive_int, default=BOARD_PORT, help=f"local port ({BOARD_PORT})"
    )
    board.add_argument("--no-browser", action="store_true", help="do not open the browser on start")
    board.set_defaults(handler=_cmd_board)

    rates_cmd = commands.add_parser(
        "rates", help="import the BCRD monthly dollar rate or set a rate"
    )
    rates_cmd.add_argument(
        "--set",
        action=_FixRate,
        nargs=2,
        metavar=("YYYY-MM", "VALUE"),
        help="set a month's rate (RD$ per US$) by hand",
    )
    rates_cmd.set_defaults(handler=_cmd_rates)
    alert_check = commands.add_parser(
        "alert-check",
        help="check bank alert emails (.eml or stdin) against the parsers; prints no values",
    )
    alert_check.add_argument("files", nargs="*", metavar="EML", help="'-' or none: stdin")
    alert_check.set_defaults(handler=_cmd_alert_check)
    cli_insights.add_commands(commands)
    cli_log.add_commands(commands)
    cli_demo.add_commands(commands)
    cli_hosted.add_commands(commands)
    cli_ops.add_commands(commands)
    return parser


def _demo_only(args: argparse.Namespace, paths: config.Paths) -> int:
    """With `MICHELITO_MODE=demo` only the demo and its feedback run; `board` starts the demo."""
    if args.handler is _cmd_board:
        # Without --port, `board` brings the local board's 8501: the demo's default is used.
        port = [] if args.port == BOARD_PORT else ["--port", str(args.port)]
        demo = _parser().parse_args(["demo", *port])
        return cli_demo.cmd_demo(demo, paths)
    if args.handler in (cli_demo.cmd_demo, cli_demo.cmd_feedback):
        return args.handler(args, paths)
    print(f"With {cli_demo.MODE_ENV}=demo only 'demo' and 'feedback' work.", file=sys.stderr)
    return 2


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be an integer greater than zero")
    return value


def _month_arg(text: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", text):
        raise argparse.ArgumentTypeError(f"invalid month '{text}'; use YYYY-MM")
    return text


def _positive_decimal(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"invalid value '{text}'") from None
    if not value.is_finite() or value <= 0:
        raise argparse.ArgumentTypeError("the rate must be a number greater than zero")
    return value


class _FixRate(argparse.Action):
    """Validate `--set YYYY-MM VALUE` while parsing the arguments."""

    def __call__(self, parser, namespace, values, option_string=None):  # noqa: ANN001, ANN204
        try:
            fixed = (_month_arg(values[0]), _positive_decimal(values[1]))
        except argparse.ArgumentTypeError as exc:
            parser.error(f"argument {option_string}: {exc}")
        setattr(namespace, self.dest, fixed)


_month_name = cli_insights.month_name


def _cmd_alert_check(args: argparse.Namespace, paths: config.Paths) -> int:
    """In memory only: opens no database and saves nothing."""
    return alert_inspect.main(args.files)


def _cmd_auth(args: argparse.Namespace, paths: config.Paths) -> int:
    """Authorize Gmail. The first time it reads the client JSON and saves it in the keyring;
    later runs (the token of an app in testing mode expires after 7 days) reuse it."""
    if args.client_secrets is None:
        client_text = vault.get_secret(vault.GMAIL_CLIENT)
    else:
        source: Path = args.client_secrets.expanduser()
        if not source.is_file():
            print(
                f"Error: {source} does not exist. Download the OAuth client JSON "
                "(Desktop app type) from Google Cloud and pass its real path; "
                "the steps are in README.md.",
                file=sys.stderr,
            )
            return 1
        client_text = source.read_text()
    try:
        client_config = json.loads(client_text)
    except json.JSONDecodeError:
        print("Error: the client configuration is not valid JSON.", file=sys.stderr)
        return 1
    vault.set_secret(vault.GMAIL_TOKEN, authorize(client_config))
    if args.client_secrets is not None:
        vault.set_secret(vault.GMAIL_CLIENT, client_text)
        print(f"Authorization saved in the keyring. You can now delete {args.client_secrets}")
    else:
        print("Authorization renewed.")
    return 0


def _cmd_secret(args: argparse.Namespace, paths: config.Paths) -> int:
    value = getpass.getpass(f"Value for {args.name}: ")
    if not value:
        print("Empty value; nothing was saved.", file=sys.stderr)
        return 1
    vault.set_secret(args.name, value)
    print("Saved in the keyring.")
    return 0


def _cmd_extract(args: argparse.Namespace, paths: config.Paths) -> int:
    for stats in _run_extract(paths, args.source):
        print(_format_extract(stats))
    return 0


def _cmd_parse(args: argparse.Namespace, paths: config.Paths) -> int:
    print(_format_parse(_run_parse(paths, args.retry)))
    return 0


# Import outcomes that leave nothing to look at.
_IMPORT_OK = frozenset({"parsed", "duplicate"})
# A file already registered with these statuses is parsed again when imported again.
_REPROCESS = frozenset({"pending", *ingest.RETRYABLE})


def _cmd_import(args: argparse.Namespace, paths: config.Paths) -> int:
    """Copy each PDF to the raw archive, register it and parse it; carry on with the rest
    even if one fails. A file already registered that could not be parsed is retried.
    Exit with 1 if any was neither saved nor a duplicate."""
    password = vault.get_secret(vault.PDF_PASSWORD)
    failed = False
    with closing(_open_db(paths)) as conn:
        for source in args.pdfs:
            try:
                registered = importer.register(conn, source, paths.raw, datetime.now(UTC))
            except (importer.ImportRejected, OSError) as exc:
                print(f"Error: {report.clean(str(exc))}", file=sys.stderr)
                failed = True
                continue
            status, label, notes = _import_outcome(conn, password, registered, args.currency)
            # A PDF with several statements can get in with a failed part: that is a failure too.
            missing = db.failed_parts(conn, registered.document_id)
            failed = failed or status not in _IMPORT_OK or missing > 0
            suffix = f" ({report.clean('; '.join(notes))})" if notes else ""
            print(f"{report.clean(source.name)}: {label}{suffix}")
    return 1 if failed else 0


def _import_outcome(
    conn: sqlite3.Connection,
    password: str,
    registered: importer.Registered,
    currency: str | None = None,
) -> tuple[str, str, list[str]]:
    """Parse the document: the newly registered one, or a known one left unparsed (again, in
    case there is a parser now). Return status, text and notes."""
    status = _document(conn, registered.document_id)["status"]
    partial = db.failed_parts(conn, registered.document_id) > 0
    retry = not registered.new and (status in _REPROCESS or partial)
    before = db.account_currencies(conn)
    if registered.new or retry:
        ingest.process_documents(
            conn,
            password,
            pdf.read_pages,
            retry=retry,
            only=(registered.document_id,),
            printout_currency=currency,
        )
    row = _document(conn, registered.document_id)
    # A PDF with several statements always explains how many got in and which ones failed.
    shown = row["status"] != "parsed" or _has_parts(conn, registered.document_id)
    detail = row["detail"] if shown and row["detail"] else None
    notes = [detail] if detail else []
    if currency is not None and row["parser"] and row["parser"] != db.PRINTOUT_PARSER:
        notes.append(f"--currency does not apply to {row['parser']}")
    notes.extend(_currency_changes(before, db.account_currencies(conn)))
    if registered.new:
        return row["status"], row["status"], notes
    if retry:
        return row["status"], row["status"], ["already imported, reprocessed", *notes]
    kept = ["--currency does not change what is already saved"] if currency is not None else []
    return row["status"], "already imported", [f"status: {row['status']}", *kept]


def _currency_changes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """A note when `--currency` sets or changes an account's remembered currency."""
    return [
        f"account currency: {before[key]} → {value}"
        if key in before
        else f"account currency: {value}"
        for key, value in sorted(after.items())
        if before.get(key) != value
    ]


def _has_parts(conn: sqlite3.Connection, document_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM document_parts WHERE document_id = ? LIMIT 1", (document_id,)
    ).fetchone()
    return row is not None


def _document(conn: sqlite3.Connection, document_id: int) -> sqlite3.Row:
    return conn.execute(
        "SELECT status, detail, parser FROM documents WHERE id = ?", (document_id,)
    ).fetchone()


def _cmd_report(args: argparse.Namespace, paths: config.Paths) -> int:
    result = _run_report(paths)
    print(result.text)
    return 1 if result.alerts else 0


def _cmd_spending(args: argparse.Namespace, paths: config.Paths) -> int:
    with closing(_open_db(paths)) as conn:
        movements = spending.load_movements(conn, transfers.load_holders(paths.holders))
        through = spending.complete_through(conn)
        first = spending.first_full_month(conn)
    print(spending_report.to_text(spending_report.build(movements, through, args.months, first)))
    return 0


def _cmd_rates(args: argparse.Namespace, paths: config.Paths) -> int:
    if args.set:
        month, value = args.set
        with closing(_open_db(paths)) as conn, conn:
            rates.set_manual(conn, month, value)
        print(f"Rate for {_month_name(month)} set to {value.quantize(Decimal('0.0001'))}")
        return 0
    try:
        values = bcrd.parse_monthly_averages(bcrd.fetch())
    except (OSError, ValueError) as exc:
        print(
            f"Error: could not import the BCRD rate ({exc}). "
            "Use `michelito rates --set YYYY-MM VALUE` to set it by hand.",
            file=sys.stderr,
        )
        return 1
    with closing(_open_db(paths)) as conn, conn:
        saved = rates.store_bcrd(conn, values)
        stored = rates.load(conn)
    last = max(values, default=None)
    suffix = f" (latest: {_month_name(last)} {stored[last].value:.4f})" if last else ""
    print(f"BCRD rates: {saved} months saved{suffix}")
    return 0


STATIC_DIR = Path(__file__).parent / "web" / "static"
BOARD_PORT = 8501
BOARD_STARTUP_SECONDS = 30.0


def _open_when_ready(url: str, port: int) -> None:
    """Open the browser once the port accepts connections; give up after a while."""
    deadline = time.monotonic() + BOARD_STARTUP_SECONDS
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.2)


def _cmd_board(args: argparse.Namespace, paths: config.Paths) -> int:
    if not (STATIC_DIR / "index.html").is_file():
        print("The interface is not built: cd frontend && npm ci && npm run build", file=sys.stderr)
        return 1
    import uvicorn  # only the board needs the web server

    from michelito.web.app import create_app

    config.ensure_private_dir(paths.root)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Board at {url} · Ctrl+C to close it")
    if not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(url, args.port), daemon=True).start()
    app = create_app(paths.database, STATIC_DIR, holders_path=paths.holders)
    with suppress(KeyboardInterrupt):
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def _cmd_sync(args: argparse.Namespace, paths: config.Paths) -> int:
    print("Download:")
    for stats in _run_extract(paths, None):
        print(f"  {_format_extract(stats)}")
    outcome = _run_parse(paths, args.retry)
    print(f"Parsing: {_format_parse(outcome)}\n")
    result = _run_report(paths)
    print(result.text)
    payments = _safe_due_payments(paths)
    if payments:
        print("\nPayments to avoid interest:")
        for payment in payments:
            print(f"  {due_text(payment)}")
    if args.notify:
        _notify(
            f"{outcome['parsed']} statements validated; {len(result.alerts)} alerts",
            bool(result.alerts),
        )
        for payment in payments:
            _notify(due_text(payment), False)
    return 1 if result.alerts else 0


def _open_db(paths: config.Paths):  # noqa: ANN202 - returns sqlite3.Connection
    config.ensure_private_dir(paths.root)
    return db.connect(paths.database)


def _run_extract(paths: config.Paths, source_name: str | None) -> list[extract.ExtractStats]:
    chosen = _chosen_sources(paths, source_name)  # before Gmail: a bad file does not connect
    client = build_client(
        vault.get_secret(vault.GMAIL_TOKEN),
        lambda token: vault.set_secret(vault.GMAIL_TOKEN, token),
    )
    with closing(_open_db(paths)) as conn:
        raw = config.ensure_private_dir(paths.raw)
        return [extract.extract_source(conn, client, source, raw) for source in chosen]


def _chosen_sources(paths: config.Paths, source_name: str | None) -> list[config.Source]:
    """The sources to download: every configured one, or the requested one if it exists."""
    configured = sources.load_sources(paths.sources)
    if source_name is None:
        return list(configured)
    try:
        return [config.find_source(source_name, configured)]
    except KeyError:
        names = ", ".join(s.name for s in configured)
        raise sources.SourcesError(
            f"unknown source: {source_name}; the configured ones are: {names}"
        ) from None


def _run_parse(paths: config.Paths, retry: bool) -> Counter[str]:
    archived = sources.archived_names(sources.load_sources(paths.sources))
    password = vault.get_secret(vault.PDF_PASSWORD)
    with closing(_open_db(paths)) as conn:
        return ingest.process_documents(
            conn, password, pdf.read_pages, retry=retry, archive_only=archived
        )


def _run_report(paths: config.Paths) -> report.Report:
    with closing(_open_db(paths)) as conn:
        return report.build_report(conn, date.today())


def _safe_due_payments(paths: config.Paths) -> list[DuePayment]:
    """The pending payments are an extra: if they fail, sync warns and carries on."""
    try:
        return _run_due_payments(paths)
    except Exception as error:  # noqa: BLE001 - the notice must never break sync
        print(f"Could not compute the pending payments: {error}", file=sys.stderr)
        return []


def _run_due_payments(paths: config.Paths) -> list[DuePayment]:
    today = date.today()
    with closing(_open_db(paths)) as conn:
        return upcoming_payments(account_views(conn, today), today)


def _format_extract(stats: extract.ExtractStats) -> str:
    return (
        f"{stats.source}: {stats.new_messages} new messages, "
        f"{stats.saved_files} files, {stats.duplicates} duplicates"
    )


def _format_parse(outcome: Counter[str]) -> str:
    if not outcome:
        return "nothing pending"
    return ", ".join(f"{status}: {count}" for status, count in sorted(outcome.items()))


def _notify(summary: str, urgent: bool) -> None:
    binary = shutil.which("notify-send")
    if binary is None:
        return
    urgency = "critical" if urgent else "normal"
    subprocess.run([binary, "--urgency", urgency, "Michelito", summary], check=False)
