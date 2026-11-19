"""Comandos del análisis con Claude Code (ver README, "Análisis del mes con Claude Code").

    finanzas analisis AAAA-MM [--cuentas k1,k2] [--formato markdown|json]
    finanzas insight guardar AAAA-MM [--archivo F] [--cuentas k1,k2]   (sin archivo: stdin)
    finanzas insight ver AAAA-MM
    finanzas insight borrar AAAA-MM

Ninguno lee el keyring: solo la base y los titulares.
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

from finanzas import config, db, dossier
from finanzas.analysis import insights, transfers
from finanzas.web.summary import month_label

FORMATS = ("markdown", "json")


def _month(text: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", text):
        raise argparse.ArgumentTypeError(f"mes inválido '{text}'; use AAAA-MM")
    return text


def _accounts(text: str) -> list[str]:
    keys = sorted({key.strip() for key in text.split(",") if key.strip()})
    if not keys:
        raise argparse.ArgumentTypeError("indique al menos una cuenta")
    return keys


def add_commands(commands: Any) -> None:
    """Agrega `analisis` e `insight` a los subcomandos de `finanzas`."""
    analisis = commands.add_parser(
        "analisis", help="imprime el dossier de un mes para analizarlo con Claude Code"
    )
    analisis.add_argument("month", type=_month, metavar="AAAA-MM")
    analisis.add_argument("--cuentas", type=_accounts, help="claves de cuentas, separadas por coma")
    analisis.add_argument("--formato", choices=FORMATS, default="markdown")
    analisis.set_defaults(handler=_cmd_analisis)

    insight = commands.add_parser("insight", help="guarda, muestra o borra el análisis de un mes")
    actions = insight.add_subparsers(required=True)
    save = actions.add_parser("guardar", help="guarda el análisis (Markdown, hasta 4000)")
    save.add_argument("month", type=_month, metavar="AAAA-MM")
    save.add_argument("--archivo", type=Path, help="archivo con el análisis; sin él, stdin")
    save.add_argument(
        "--cuentas", type=_accounts, help="las cuentas analizadas (por defecto todas)"
    )
    save.set_defaults(handler=_cmd_save)
    view = actions.add_parser("ver", help="muestra el análisis guardado")
    view.add_argument("month", type=_month, metavar="AAAA-MM")
    view.set_defaults(handler=_cmd_view)
    remove = actions.add_parser("borrar", help="borra el análisis guardado")
    remove.add_argument("month", type=_month, metavar="AAAA-MM")
    remove.set_defaults(handler=_cmd_delete)


def _open(paths: config.Paths) -> sqlite3.Connection:
    config.ensure_private_dir(paths.root)
    return db.connect(paths.database)


def _dossier(
    conn: sqlite3.Connection, paths: config.Paths, month: str, accounts: list[str] | None
) -> dossier.Dossier:
    return dossier.build(
        conn, month, accounts=accounts, holders=transfers.load_holders(paths.holders)
    )


def _fail(message: str) -> int:
    print(f"Error: {message}", file=sys.stderr)
    return 1


def _cmd_analisis(args: argparse.Namespace, paths: config.Paths) -> int:
    with closing(_open(paths)) as conn:
        try:
            built = _dossier(conn, paths, args.month, args.cuentas)
        except ValueError as exc:
            return _fail(str(exc))
        except LookupError:
            return _fail(f"{month_label(args.month)} sin datos")
    if args.formato == "json":
        body = {"huella_de_datos": built.data_hash, "datos": built.data}
        print(json.dumps(body, ensure_ascii=False, indent=2))
    else:
        print(built.markdown)
    return 0


def _read_text(source: Path | None) -> str:
    if source is None:
        if sys.stdin.isatty():
            raise ValueError(
                "falta el análisis: pásalo con --archivo F o por la entrada estándar "
                "(finanzas insight guardar AAAA-MM < analisis.md)"
            )
        return sys.stdin.read()
    if not source.is_file():
        raise ValueError(f"{source} no existe")
    return source.read_text(encoding="utf-8")


def _from_header(text: str, month: str, given: list[str] | None) -> tuple[str, list[str] | None]:
    """Quita el encabezado del dossier si vino en el análisis y toma de él las cuentas.

    ValueError si es de otro mes o sus cuentas no son las de `--cuentas`."""
    pasted = dossier.split_header(text, month)
    if not pasted.has_header:
        return text, given
    if given is not None and given != pasted.accounts:
        raise ValueError(
            "las cuentas de --cuentas no son las del dossier analizado; usa las mismas que en "
            "`finanzas analisis`"
        )
    return pasted.text, pasted.accounts


def _cmd_save(args: argparse.Namespace, paths: config.Paths) -> int:
    """Guarda el análisis con la huella del dossier de las mismas cuentas que `analisis`."""
    try:
        raw, accounts = _from_header(_read_text(args.archivo), args.month, args.cuentas)
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
            return _fail(f"{month_label(args.month)} sin datos: no hay nada que analizar")
        with conn:
            insights.save(conn, args.month, text, built.data_hash, accounts, now)
    print(f"Análisis de {month_label(args.month)} guardado ({len(text)} caracteres).")
    return 0


def _cmd_view(args: argparse.Namespace, paths: config.Paths) -> int:
    with closing(_open(paths)) as conn:
        found = insights.get(conn, args.month)
        if found is None:
            return _fail(f"No hay análisis de {month_label(args.month)}")
        try:
            current = _dossier(conn, paths, args.month, list(found.accounts or ()) or None)
            changed = current.data_hash != found.data_hash
        except (ValueError, LookupError):
            changed = True
    print(found.text)
    print(f"\n— Guardado el {found.updated_at[:10]}.", end="")
    print(" Los datos cambiaron desde este análisis." if changed else "")
    return 0


def _cmd_delete(args: argparse.Namespace, paths: config.Paths) -> int:
    with closing(_open(paths)) as conn, conn:
        removed = insights.delete(conn, args.month)
    if not removed:
        return _fail(f"No hay análisis de {month_label(args.month)}")
    print(f"Análisis de {month_label(args.month)} borrado.")
    return 0
