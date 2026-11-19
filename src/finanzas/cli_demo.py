"""Comandos del modo demo (ver README, «Demo pública»).

    finanzas demo [--puerto N] [--datos DIR] [--host-publico H] [--cookie-insegura] ...
    finanzas opiniones [--json] [--uso] [--datos DIR]

`demo` sirve la demo pública: datos inventados, una copia de la base por visitante. Nunca usa la
carpeta de datos reales, Gmail ni el keyring. Con `FINANZAS_MODO=demo` solo funcionan estos dos
comandos (y `board`, que arranca la demo): un servidor de la demo no puede tocar nada real.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from finanzas import config

MODE_ENV = "FINANZAS_MODO"
DIR_ENV = "FINANZAS_DEMO_DIR"
DEFAULT_DIR = "~/finanzas-demo"
DEFAULT_PORT = 8600
RESERVED_PORTS = (8500, 8501)  # 8501 es el del board local


def demo_mode() -> bool:
    return os.environ.get(MODE_ENV, "").strip().lower() == "demo"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _demo_dir(text: str | None) -> Path:
    return Path(text or _env(DIR_ENV, DEFAULT_DIR)).expanduser().resolve()


def add_commands(commands: Any) -> None:
    """Agrega `demo` y `opiniones` a los subcomandos de `finanzas`."""
    demo = commands.add_parser("demo", help="sirve la demo pública con datos inventados")
    # Los valores por omisión numéricos van como texto: argparse los convierte con `type` solo
    # al usar `demo`, así una variable de entorno mal escrita no rompe los demás comandos.
    demo.add_argument(
        "--puerto",
        type=int,
        default=_env("FINANZAS_DEMO_PUERTO", str(DEFAULT_PORT)),
        help=f"puerto ($FINANZAS_DEMO_PUERTO; {DEFAULT_PORT})",
    )
    demo.add_argument("--datos", help=f"carpeta de la demo (${DIR_ENV}; {DEFAULT_DIR})")
    demo.add_argument(
        "--escuchar",
        default=_env("FINANZAS_DEMO_ESCUCHAR", "127.0.0.1"),
        help="dirección donde escucha (127.0.0.1; 0.0.0.0 dentro de un contenedor)",
    )
    demo.add_argument(
        "--host-publico",
        default=_env("FINANZAS_DEMO_HOST", "demo.michelito.app"),
        help="el host con que llegan los visitantes (además de loopback)",
    )
    demo.add_argument(
        "--cookie-insegura",
        action="store_true",
        default=_env("FINANZAS_DEMO_COOKIE_INSEGURA", "") == "1",
        help="cookie sin Secure: solo para probar por http en la máquina",
    )
    demo.add_argument("--repo", default=_env("FINANZAS_DEMO_REPO", ""), help="enlace al repo")
    demo.add_argument(
        "--proxy-confiable",
        action="append",
        default=[p for p in _env("FINANZAS_DEMO_PROXIES", "").split(",") if p.strip()],
        metavar="IP_O_RED",
        help="proxy (Caddy) del que se cree X-Forwarded-For; se repite. Sin él, se ignora",
    )
    demo.add_argument(
        "--copias-por-ip",
        type=int,
        default=_env("FINANZAS_DEMO_COPIAS_POR_IP", "3"),
        help="copias nuevas por IP al día (3)",
    )
    demo.add_argument(
        "--copias-max",
        type=int,
        default=_env("FINANZAS_DEMO_COPIAS_MAX", "200"),
        help="copias vivas a la vez (200)",
    )
    demo.set_defaults(handler=cmd_demo)

    opinions = commands.add_parser("opiniones", help="muestra las opiniones de la demo")
    opinions.add_argument("--json", action="store_true", help="en JSON")
    opinions.add_argument("--uso", action="store_true", help="los contadores de uso por día")
    opinions.add_argument("--datos", help=f"carpeta de la demo (${DIR_ENV}; {DEFAULT_DIR})")
    opinions.set_defaults(handler=cmd_opiniones)


def _check_dir(directory: Path, paths: config.Paths) -> str | None:
    """Motivo para no usar esa carpeta: la demo nunca se mezcla con los datos reales (ni con la
    carpeta configurada ni con la de omisión, `~/finanzas-data`)."""
    for root in (paths.root, Path(config.DEFAULT_DATA_DIR)):
        real = root.expanduser().resolve()
        if directory == real or directory.is_relative_to(real) or real.is_relative_to(directory):
            return f"la carpeta de la demo no puede ser ni contener la de datos reales ({real})"
    return None


def _exposed_without_proxy(args: argparse.Namespace) -> bool:
    return args.escuchar in ("0.0.0.0", "::", "") and not args.proxy_confiable


def cmd_demo(args: argparse.Namespace, paths: config.Paths) -> int:
    started = time.perf_counter()
    from finanzas.cli import STATIC_DIR  # el mismo build de la interfaz que el board

    if args.puerto in RESERVED_PORTS:
        print(f"El puerto {args.puerto} es del board local: elige otro.", file=sys.stderr)
        return 2
    directory = _demo_dir(args.datos)
    problem = _check_dir(directory, paths)
    if problem:
        print(f"Error: {problem}", file=sys.stderr)
        return 2
    if not (STATIC_DIR / "index.html").is_file():
        print("Falta compilar la interfaz: cd frontend && npm ci && npm run build", file=sys.stderr)
        return 1
    import uvicorn

    from finanzas.demo.app import Settings, create_demo_app
    from finanzas.demo.copias import Limits

    if _exposed_without_proxy(args):
        print(
            "Aviso: escucha en todas las interfaces sin --proxy-confiable. Detrás de un proxy "
            "(Caddy) todos los visitantes compartirían el cupo de su IP; si hay uno, indícalo.",
            file=sys.stderr,
        )
    config.ensure_private_dir(directory)
    settings = Settings(
        data=directory,
        public_host=args.host_publico,
        secure_cookie=not args.cookie_insegura,
        repo=args.repo,
        limits=Limits(per_ip=args.copias_por_ip, max_live=args.copias_max),
        proxies=tuple(args.proxy_confiable),
    )
    app = create_demo_app(settings, STATIC_DIR)
    print(f"Plantilla generada en {app.state.template_seconds:.2f} s")
    print(f"Lista en {time.perf_counter() - started:.2f} s desde el comando")
    print(f"Demo en http://{args.escuchar}:{args.puerto} (host público {args.host_publico})")
    with suppress(KeyboardInterrupt):
        uvicorn.run(
            app,
            host=args.escuchar,
            port=args.puerto,
            log_level="warning",
            proxy_headers=False,  # la IP del visitante la decide `demo.red`, no uvicorn
        )
    app.state.maintenance.stop()  # vuelca los conteos que quedaban en memoria
    return 0


def cmd_opiniones(args: argparse.Namespace, paths: config.Paths) -> int:
    from finanzas.demo import opiniones

    directory = _demo_dir(args.datos)
    path = directory / opiniones.FILENAME
    if not path.is_file():
        print(f"No hay opiniones todavía ({path} no existe).", file=sys.stderr)
        return 1
    feedback = opiniones.Feedback(path)
    if args.uso:
        rows = feedback.usage()
        if args.json:
            print(json.dumps(rows, indent=2))
        for row in [] if args.json else rows:
            key = opiniones.printable(str(row["clave"]))
            print(f"{row['dia']}  {row['tipo']:<7} {key:<22} {row['conteo']}")
        return 0
    found = feedback.opinions()
    if args.json:
        # ensure_ascii: los controles (también los bidi) salen escapados, no actúan.
        print(json.dumps([opiniones.as_dict(o) for o in found], indent=2))
        return 0
    if not found:
        print("No hay opiniones todavía.")
    for opinion in found:
        context = " · ".join(
            str(part)
            for part in (
                opinion.pagina,
                f"{opinion.ancho}px" if opinion.ancho else None,
                f"v{opinion.version}" if opinion.version else None,
                f"ref={opinion.ref}" if opinion.ref else None,
                opinion.correo,
            )
            if part
        )
        # Lo escribió un visitante: sus caracteres de control se muestran, no actúan.
        print(f"#{opinion.id} {opinion.creada}  {opiniones.printable(context)}")
        print(f"{opiniones.printable(opinion.texto)}\n")
    return 0
