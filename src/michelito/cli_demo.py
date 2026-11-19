"""Demo mode commands (see the README on the public demo).

    michelito demo [--port N] [--data DIR] [--public-host H] [--insecure-cookie] ...
    michelito feedback [--json] [--usage] [--data DIR]

`demo` serves the public demo: made-up data, one copy of the database per visitor. It never uses
the real data folder, Gmail nor the keyring. With `MICHELITO_MODE=demo` only these two commands
work (and `board`, which starts the demo): a demo server cannot touch anything real.
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

from michelito import config, legacy

MODE_ENV = "MICHELITO_MODE"
DIR_ENV = "MICHELITO_DEMO_DIR"
PORT_ENV = "MICHELITO_DEMO_PORT"
LISTEN_ENV = "MICHELITO_DEMO_LISTEN"
HOST_ENV = "MICHELITO_DEMO_HOST"
INSECURE_COOKIE_ENV = "MICHELITO_DEMO_INSECURE_COOKIE"
REPO_ENV = "MICHELITO_DEMO_REPO"
PROXIES_ENV = "MICHELITO_DEMO_PROXIES"
COPIES_PER_IP_ENV = "MICHELITO_DEMO_COPIES_PER_IP"
COPIES_MAX_ENV = "MICHELITO_DEMO_COPIES_MAX"
DEFAULT_DIR = "~/michelito-demo"
DEFAULT_PORT = 8600
RESERVED_PORTS = (8500, 8501)  # 8501 is the local board's


def demo_mode() -> bool:
    return os.environ.get(MODE_ENV, "").strip().lower() == "demo"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _demo_dir(text: str | None) -> Path:
    return Path(text or _env(DIR_ENV, DEFAULT_DIR)).expanduser().resolve()


def add_commands(commands: Any) -> None:
    """Add `demo` and `feedback` to the `michelito` subcommands."""
    demo = commands.add_parser("demo", help="serve the public demo with made-up data")
    # Numeric defaults go as text: argparse converts them with `type` only when `demo` is used,
    # so a mistyped environment variable does not break the other commands.
    demo.add_argument(
        "--port",
        type=int,
        default=_env(PORT_ENV, str(DEFAULT_PORT)),
        help=f"port (${PORT_ENV}; {DEFAULT_PORT})",
    )
    demo.add_argument(
        "--data", metavar="DIR", help=f"the demo's folder (${DIR_ENV}; {DEFAULT_DIR})"
    )
    demo.add_argument(
        "--listen",
        default=_env(LISTEN_ENV, "127.0.0.1"),
        metavar="ADDRESS",
        help="address to listen on (127.0.0.1; 0.0.0.0 inside a container)",
    )
    demo.add_argument(
        "--public-host",
        default=_env(HOST_ENV, "demo.michelito.app"),
        metavar="HOST",
        help="the host visitors arrive with (besides loopback)",
    )
    demo.add_argument(
        "--insecure-cookie",
        action="store_true",
        default=_env(INSECURE_COOKIE_ENV, "") == "1",
        help="cookie without Secure: only for testing over http on this machine",
    )
    demo.add_argument(
        "--repo", default=_env(REPO_ENV, ""), metavar="URL", help="link to the repository"
    )
    demo.add_argument(
        "--trusted-proxy",
        action="append",
        default=[p for p in _env(PROXIES_ENV, "").split(",") if p.strip()],
        metavar="IP_OR_NET",
        help="proxy (Caddy) whose X-Forwarded-For is trusted; repeatable. Without it, ignored",
    )
    demo.add_argument(
        "--copies-per-ip",
        type=int,
        default=_env(COPIES_PER_IP_ENV, "3"),
        metavar="N",
        help="new copies per IP per day (3)",
    )
    demo.add_argument(
        "--copies-max",
        type=int,
        default=_env(COPIES_MAX_ENV, "200"),
        metavar="N",
        help="live copies at a time (200)",
    )
    demo.set_defaults(handler=cmd_demo)

    feedback = commands.add_parser("feedback", help="show the demo's feedback")
    feedback.add_argument("--json", action="store_true", help="as JSON")
    feedback.add_argument("--usage", action="store_true", help="the usage counters per day")
    feedback.add_argument(
        "--data", metavar="DIR", help=f"the demo's folder (${DIR_ENV}; {DEFAULT_DIR})"
    )
    feedback.set_defaults(handler=cmd_feedback)


def _check_dir(directory: Path, paths: config.Paths) -> str | None:
    """Why that folder cannot be used: the demo never mixes with real data (the configured
    folder, the default one or the pre-rename default, `legacy.DATA_DIR`)."""
    for root in (paths.root, Path(config.DEFAULT_DATA_DIR), Path(legacy.DATA_DIR)):
        real = root.expanduser().resolve()
        if directory == real or directory.is_relative_to(real) or real.is_relative_to(directory):
            return f"the demo folder can neither be nor contain the real data folder ({real})"
    return None


def _exposed_without_proxy(args: argparse.Namespace) -> bool:
    return args.listen in ("0.0.0.0", "::", "") and not args.trusted_proxy


def cmd_demo(args: argparse.Namespace, paths: config.Paths) -> int:
    started = time.perf_counter()
    from michelito.cli import STATIC_DIR  # the same interface build as the board

    if args.port in RESERVED_PORTS:
        print(f"Port {args.port} belongs to the local board: pick another one.", file=sys.stderr)
        return 2
    directory = _demo_dir(args.data)
    problem = _check_dir(directory, paths)
    if problem:
        print(f"Error: {problem}", file=sys.stderr)
        return 2
    if not (STATIC_DIR / "index.html").is_file():
        print("The interface is not built: cd frontend && npm ci && npm run build", file=sys.stderr)
        return 1
    import uvicorn

    from michelito.demo.app import Settings, create_demo_app
    from michelito.demo.copies import Limits

    if _exposed_without_proxy(args):
        print(
            "Warning: listening on every interface without --trusted-proxy. Behind a proxy "
            "(Caddy) every visitor would share its IP's quota; if there is one, give it.",
            file=sys.stderr,
        )
    config.ensure_private_dir(directory)
    settings = Settings(
        data=directory,
        public_host=args.public_host,
        secure_cookie=not args.insecure_cookie,
        repo=args.repo,
        limits=Limits(per_ip=args.copies_per_ip, max_live=args.copies_max),
        proxies=tuple(args.trusted_proxy),
    )
    app = create_demo_app(settings, STATIC_DIR)
    print(f"Template generated in {app.state.template_seconds:.2f} s")
    print(f"Ready in {time.perf_counter() - started:.2f} s from the command")
    print(f"Demo at http://{args.listen}:{args.port} (public host {args.public_host})")
    with suppress(KeyboardInterrupt):
        uvicorn.run(
            app,
            host=args.listen,
            port=args.port,
            log_level="warning",
            proxy_headers=False,  # the visitor IP is decided by `demo.network`, not uvicorn
        )
    app.state.maintenance.stop()  # flush the counts still in memory
    return 0


def cmd_feedback(args: argparse.Namespace, paths: config.Paths) -> int:
    from michelito.demo import feedback_store

    directory = _demo_dir(args.data)
    path = directory / feedback_store.FILENAME
    if not feedback_store.exists(directory):
        print(f"No feedback yet ({path} does not exist).", file=sys.stderr)
        return 1
    feedback = feedback_store.Feedback(path)
    if args.usage:
        rows = feedback.usage()
        if args.json:
            print(json.dumps(rows, indent=2))
        for row in [] if args.json else rows:
            key = feedback_store.printable(str(row["key"]))
            print(f"{row['day']}  {row['kind']:<7} {key:<22} {row['count']}")
        return 0
    found = feedback.opinions()
    if args.json:
        # ensure_ascii: control characters (bidi ones too) come out escaped, they do not act.
        print(json.dumps([feedback_store.as_dict(o) for o in found], indent=2))
        return 0
    if not found:
        print("No feedback yet.")
    for opinion in found:
        context = " · ".join(
            str(part)
            for part in (
                opinion.page,
                f"{opinion.width}px" if opinion.width else None,
                f"v{opinion.version}" if opinion.version else None,
                f"ref={opinion.ref}" if opinion.ref else None,
                opinion.email,
            )
            if part
        )
        # A visitor wrote it: its control characters are shown, they do not act.
        print(f"#{opinion.id} {opinion.created_at}  {feedback_store.printable(context)}")
        print(f"{feedback_store.printable(opinion.text)}\n")
    return 0
