"""Línea de comandos.

    finanzas auth [--client-secrets ARCHIVO] autoriza Gmail (solo lectura)
    finanzas secret pdf-password             guarda la clave de los PDFs
    finanzas sync [--notify] [--retry]       descarga, interpreta y reporta
    finanzas extract [--source NOMBRE]       solo descarga
    finanzas parse [--retry]                 solo interpreta lo pendiente
    finanzas importar [--moneda M] PDF...    importa estados descargados a mano
    finanzas report                          solo muestra la cobertura
    finanzas gastos [--meses N]              resumen de gastos en la terminal
    finanzas board [--puerto N]              board web local en 127.0.0.1
    finanzas tasas [--fijar AAAA-MM VALOR]   dólar mensual del BCRD, o una tasa a mano
    finanzas analisis AAAA-MM [--cuentas K]  dossier del mes para analizarlo con Claude Code
    finanzas insight guardar|ver|borrar AAAA-MM   el análisis guardado del mes
    finanzas bitacora [--json] [--desde FECHA]    los cambios hechos desde el board
    finanzas nuevas [--json] [--marcar-revisadas] transacciones sin revisar
    finanzas demo [--puerto N] [--datos DIR]      demo pública con datos inventados
    finanzas opiniones [--json] [--uso]           opiniones y uso de la demo

`sync` y `report` terminan con código 1 si hay alertas, 2 si falta un secreto.
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

from finanzas import (
    cli_demo,
    cli_insights,
    cli_log,
    config,
    db,
    extract,
    importer,
    ingest,
    pdf,
    report,
    sources,
    vault,
)
from finanzas.analysis import bcrd, rates, spending, transfers
from finanzas.analysis import report as spending_report
from finanzas.gmail import authorize, build_client
from finanzas.parsers import popular_web
from finanzas.web.accounts import DuePayment, account_views, due_text, upcoming_payments


def main(argv: Sequence[str] | None = None) -> int:
    os.umask(0o077)  # todo lo que se cree (carpetas, base, journal) queda solo para el usuario
    args = _parser().parse_args(argv)
    paths = config.default_paths()
    if cli_demo.demo_mode():
        return _demo_only(args, paths)
    try:
        return args.handler(args, paths)
    except (vault.MissingSecretError, sources.SourcesError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finanzas", description="Estados de cuenta a SQLite")
    commands = parser.add_subparsers(required=True)

    auth = commands.add_parser("auth", help="autoriza el acceso de solo lectura a Gmail")
    auth.add_argument(
        "--client-secrets", type=Path, help="JSON del cliente OAuth; solo hace falta la primera vez"
    )
    auth.set_defaults(handler=_cmd_auth)

    secret = commands.add_parser("secret", help="guarda un secreto en el keyring")
    secret.add_argument("name", choices=(vault.PDF_PASSWORD,))
    secret.set_defaults(handler=_cmd_secret)

    sync = commands.add_parser("sync", help="descarga, interpreta y reporta")
    sync.add_argument("--notify", action="store_true", help="aviso en el escritorio al terminar")
    sync.add_argument("--retry", action="store_true", help="reintenta documentos fallidos")
    sync.set_defaults(handler=_cmd_sync)

    extract_cmd = commands.add_parser("extract", help="solo descarga desde Gmail")
    extract_cmd.add_argument(
        "--source", metavar="NOMBRE", help="solo esta fuente (de fuentes.toml o las de omisión)"
    )
    extract_cmd.set_defaults(handler=_cmd_extract)

    parse = commands.add_parser("parse", help="solo interpreta los documentos pendientes")
    parse.add_argument("--retry", action="store_true", help="reintenta documentos fallidos")
    parse.set_defaults(handler=_cmd_parse)

    importar = commands.add_parser("importar", help="importa estados PDF descargados a mano")
    importar.add_argument(
        "--moneda",
        type=str.upper,
        choices=popular_web.CURRENCIES,
        help='moneda de las impresiones del portal (imprimen "$" a secas); se recuerda '
        "para la cuenta",
    )
    importar.add_argument("pdfs", nargs="+", type=Path, metavar="PDF")
    importar.set_defaults(handler=_cmd_importar)

    commands.add_parser("report", help="muestra la cobertura").set_defaults(handler=_cmd_report)

    gastos = commands.add_parser("gastos", help="resumen de gastos en la terminal")
    gastos.add_argument(
        "--meses", type=_positive_int, default=12, help="meses completos a analizar (12)"
    )
    gastos.set_defaults(handler=_cmd_gastos)

    board = commands.add_parser("board", help="board interactivo en el navegador (local)")
    board.add_argument(
        "--puerto", type=_positive_int, default=BOARD_PORT, help=f"puerto local ({BOARD_PORT})"
    )
    board.add_argument(
        "--sin-navegador", action="store_true", help="no abre el navegador al arrancar"
    )
    board.set_defaults(handler=_cmd_board)

    tasas = commands.add_parser("tasas", help="importa el dólar mensual del BCRD o fija una tasa")
    tasas.add_argument(
        "--fijar",
        action=_FixRate,
        nargs=2,
        metavar=("AAAA-MM", "VALOR"),
        help="fija a mano la tasa (RD$ por US$) de un mes",
    )
    tasas.set_defaults(handler=_cmd_tasas)
    cli_insights.add_commands(commands)
    cli_log.add_commands(commands)
    cli_demo.add_commands(commands)
    return parser


def _demo_only(args: argparse.Namespace, paths: config.Paths) -> int:
    """Con `FINANZAS_MODO=demo` solo corren la demo y sus opiniones; `board` arranca la demo."""
    if args.handler is _cmd_board:
        # Sin --puerto, `board` trae el 8501 del board local: se usa el de omisión de la demo.
        port = [] if args.puerto == BOARD_PORT else ["--puerto", str(args.puerto)]
        demo = _parser().parse_args(["demo", *port])
        return cli_demo.cmd_demo(demo, paths)
    if args.handler in (cli_demo.cmd_demo, cli_demo.cmd_opiniones):
        return args.handler(args, paths)
    print(f"Con {cli_demo.MODE_ENV}=demo solo funcionan «demo» y «opiniones».", file=sys.stderr)
    return 2


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("debe ser un entero mayor que cero")
    return value


def _month_arg(text: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", text):
        raise argparse.ArgumentTypeError(f"mes inválido '{text}'; use AAAA-MM")
    return text


def _positive_decimal(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"valor inválido '{text}'") from None
    if not value.is_finite() or value <= 0:
        raise argparse.ArgumentTypeError("la tasa debe ser un número mayor que cero")
    return value


class _FixRate(argparse.Action):
    """Valida `--fijar AAAA-MM VALOR` al interpretar los argumentos."""

    def __call__(self, parser, namespace, values, option_string=None):  # noqa: ANN001, ANN204
        try:
            fixed = (_month_arg(values[0]), _positive_decimal(values[1]))
        except argparse.ArgumentTypeError as exc:
            parser.error(f"argument {option_string}: {exc}")
        setattr(namespace, self.dest, fixed)


_MONTH_NAMES = (
    "Enero",
    "Febrero",
    "Marzo",
    "Abril",
    "Mayo",
    "Junio",
    "Julio",
    "Agosto",
    "Septiembre",
    "Octubre",
    "Noviembre",
    "Diciembre",
)


def _month_name(month: str) -> str:
    return f"{_MONTH_NAMES[int(month[5:7]) - 1]} {month[:4]}"


def _cmd_auth(args: argparse.Namespace, paths: config.Paths) -> int:
    """Autoriza Gmail. La primera vez lee el JSON del cliente y lo guarda en el keyring;
    las siguientes (el token de una app en modo prueba caduca a los 7 días) lo reutiliza."""
    if args.client_secrets is None:
        client_text = vault.get_secret(vault.GMAIL_CLIENT)
    else:
        source: Path = args.client_secrets.expanduser()
        if not source.is_file():
            print(
                f"Error: {source} no existe. Descarga el JSON del cliente OAuth "
                "(tipo App de escritorio) desde Google Cloud y pasa su ruta real; "
                "los pasos están en README.md.",
                file=sys.stderr,
            )
            return 1
        client_text = source.read_text()
    try:
        client_config = json.loads(client_text)
    except json.JSONDecodeError:
        print("Error: la configuración del cliente no es un JSON válido.", file=sys.stderr)
        return 1
    vault.set_secret(vault.GMAIL_TOKEN, authorize(client_config))
    if args.client_secrets is not None:
        vault.set_secret(vault.GMAIL_CLIENT, client_text)
        print(f"Autorización guardada en el keyring. Ya puedes borrar {args.client_secrets}")
    else:
        print("Autorización renovada.")
    return 0


def _cmd_secret(args: argparse.Namespace, paths: config.Paths) -> int:
    value = getpass.getpass(f"Valor para {args.name}: ")
    if not value:
        print("Valor vacío; no se guardó nada.", file=sys.stderr)
        return 1
    vault.set_secret(args.name, value)
    print("Guardado en el keyring.")
    return 0


def _cmd_extract(args: argparse.Namespace, paths: config.Paths) -> int:
    for stats in _run_extract(paths, args.source):
        print(_format_extract(stats))
    return 0


def _cmd_parse(args: argparse.Namespace, paths: config.Paths) -> int:
    print(_format_parse(_run_parse(paths, args.retry)))
    return 0


# Resultados de una importación que no dejan nada por revisar.
_IMPORT_OK = frozenset({"parsed", "duplicate"})
# Un archivo ya registrado en estos estados se vuelve a interpretar al importarlo otra vez.
_REPROCESS = frozenset({"pending", *ingest.RETRYABLE})


def _cmd_importar(args: argparse.Namespace, paths: config.Paths) -> int:
    """Copia cada PDF al archivo crudo, lo registra y lo interpreta; sigue con el resto
    aunque uno falle. Un archivo ya registrado que no se pudo interpretar se reintenta.
    Termina con 1 si alguno no quedó guardado ni era repetido."""
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
            status, label, notes = _import_outcome(conn, password, registered, args.moneda)
            # Un PDF con varios estados puede entrar con algún tramo fallido: también es fallo.
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
    """Interpreta el documento: el recién registrado, o uno ya conocido que quedó sin
    interpretar (otra vez, por si ya hay parser). Devuelve estado, texto y notas."""
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
    # Un PDF con varios estados explica siempre cuántos entraron y cuáles fallaron.
    shown = row["status"] != "parsed" or _has_parts(conn, registered.document_id)
    detail = row["detail"] if shown and row["detail"] else None
    notes = [detail] if detail else []
    if currency is not None and row["parser"] and row["parser"] != db.PRINTOUT_PARSER:
        notes.append(f"--moneda no aplica a {row['parser']}")
    notes.extend(_currency_changes(before, db.account_currencies(conn)))
    if registered.new:
        return row["status"], row["status"], notes
    if retry:
        return row["status"], row["status"], ["ya importado, reprocesado", *notes]
    kept = ["--moneda no cambia lo ya guardado"] if currency is not None else []
    return row["status"], "ya importado", [f"estado: {row['status']}", *kept]


def _currency_changes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Aviso cuando `--moneda` fija o cambia la moneda recordada de una cuenta."""
    return [
        f"moneda de la cuenta: {before[key]} → {value}"
        if key in before
        else f"moneda de la cuenta: {value}"
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


def _cmd_gastos(args: argparse.Namespace, paths: config.Paths) -> int:
    with closing(_open_db(paths)) as conn:
        movements = spending.load_movements(conn, transfers.load_holders(paths.holders))
        through = spending.complete_through(conn)
        first = spending.first_full_month(conn)
    print(spending_report.to_text(spending_report.build(movements, through, args.meses, first)))
    return 0


def _cmd_tasas(args: argparse.Namespace, paths: config.Paths) -> int:
    if args.fijar:
        month, value = args.fijar
        with closing(_open_db(paths)) as conn, conn:
            rates.set_manual(conn, month, value)
        print(f"Tasa de {_month_name(month)} fijada en {value.quantize(Decimal('0.0001'))}")
        return 0
    try:
        values = bcrd.parse_monthly_averages(bcrd.fetch())
    except (OSError, ValueError) as exc:
        print(
            f"Error: no se pudo importar la tasa del BCRD ({exc}). "
            "Use `finanzas tasas --fijar AAAA-MM VALOR` para fijarla a mano.",
            file=sys.stderr,
        )
        return 1
    with closing(_open_db(paths)) as conn, conn:
        saved = rates.store_bcrd(conn, values)
        stored = rates.load(conn)
    last = max(values, default=None)
    suffix = f" (último: {_month_name(last)} {stored[last].value:.4f})" if last else ""
    print(f"Tasas BCRD: {saved} meses guardados{suffix}")
    return 0


STATIC_DIR = Path(__file__).parent / "web" / "static"
BOARD_PORT = 8501
BOARD_STARTUP_SECONDS = 30.0


def _open_when_ready(url: str, port: int) -> None:
    """Abre el navegador cuando el puerto acepta conexiones; se rinde tras un rato."""
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
        print("Falta compilar la interfaz: cd frontend && npm ci && npm run build", file=sys.stderr)
        return 1
    import uvicorn  # solo el board necesita el servidor web

    from finanzas.web.app import create_app

    config.ensure_private_dir(paths.root)
    url = f"http://127.0.0.1:{args.puerto}"
    print(f"Board en {url} · Ctrl+C para cerrarlo")
    if not args.sin_navegador:
        threading.Thread(target=_open_when_ready, args=(url, args.puerto), daemon=True).start()
    app = create_app(paths.database, STATIC_DIR, holders_path=paths.holders)
    with suppress(KeyboardInterrupt):
        uvicorn.run(app, host="127.0.0.1", port=args.puerto, log_level="warning")
    return 0


def _cmd_sync(args: argparse.Namespace, paths: config.Paths) -> int:
    print("Descarga:")
    for stats in _run_extract(paths, None):
        print(f"  {_format_extract(stats)}")
    outcome = _run_parse(paths, args.retry)
    print(f"Interpretación: {_format_parse(outcome)}\n")
    result = _run_report(paths)
    print(result.text)
    payments = _safe_due_payments(paths)
    if payments:
        print("\nPagos para no generar intereses:")
        for payment in payments:
            print(f"  {due_text(payment)}")
    if args.notify:
        _notify(
            f"{outcome['parsed']} estados validados; {len(result.alerts)} alertas",
            bool(result.alerts),
        )
        for payment in payments:
            _notify(due_text(payment), False)
    return 1 if result.alerts else 0


def _open_db(paths: config.Paths):  # noqa: ANN202 - devuelve sqlite3.Connection
    config.ensure_private_dir(paths.root)
    return db.connect(paths.database)


def _run_extract(paths: config.Paths, source_name: str | None) -> list[extract.ExtractStats]:
    chosen = _chosen_sources(paths, source_name)  # antes de Gmail: un archivo malo no conecta
    client = build_client(
        vault.get_secret(vault.GMAIL_TOKEN),
        lambda token: vault.set_secret(vault.GMAIL_TOKEN, token),
    )
    with closing(_open_db(paths)) as conn:
        raw = config.ensure_private_dir(paths.raw)
        return [extract.extract_source(conn, client, source, raw) for source in chosen]


def _chosen_sources(paths: config.Paths, source_name: str | None) -> list[config.Source]:
    """Las fuentes a descargar: todas las configuradas, o la pedida si existe."""
    configured = sources.load_sources(paths.sources)
    if source_name is None:
        return list(configured)
    try:
        return [config.find_source(source_name, configured)]
    except KeyError:
        names = ", ".join(s.name for s in configured)
        raise sources.SourcesError(
            f"fuente desconocida: {source_name}; las configuradas son: {names}"
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
    """Los pagos pendientes son un extra: si fallan, sync avisa y sigue."""
    try:
        return _run_due_payments(paths)
    except Exception as error:  # noqa: BLE001 - el aviso nunca debe romper sync
        print(f"No se pudieron calcular los pagos pendientes: {error}", file=sys.stderr)
        return []


def _run_due_payments(paths: config.Paths) -> list[DuePayment]:
    today = date.today()
    with closing(_open_db(paths)) as conn:
        return upcoming_payments(account_views(conn, today), today)


def _format_extract(stats: extract.ExtractStats) -> str:
    return (
        f"{stats.source}: {stats.new_messages} mensajes nuevos, "
        f"{stats.saved_files} archivos, {stats.duplicates} duplicados"
    )


def _format_parse(outcome: Counter[str]) -> str:
    if not outcome:
        return "nada pendiente"
    return ", ".join(f"{status}: {count}" for status, count in sorted(outcome.items()))


def _notify(summary: str, urgent: bool) -> None:
    binary = shutil.which("notify-send")
    if binary is None:
        return
    urgency = "critical" if urgent else "normal"
    subprocess.run([binary, "--urgency", urgency, "Finanzas", summary], check=False)
