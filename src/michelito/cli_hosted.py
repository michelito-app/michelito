"""Hosted mode commands (see the README on hosted mode).

    michelito hosted [--port N] [--data DIR] [--mailer resend|outbox] [--insecure-cookie] ...
    michelito invite EMAIL [--data DIR] [--mailer resend|outbox]
    michelito rotate-master-key --new PATH [--data DIR] [--master-key PATH]

`hosted` serves many people, each with their own encrypted database, signed in by an email code;
it needs the master key file (`--master-key` or $MICHELITO_MASTER_KEY_FILE, outside the data
folder). `invite` is the only way in: a single-use invitation for one email, with its code by
email. `rotate-master-key` re-wraps every data key under a new master key (resumable; the server
must be stopped). None of them uses the local data folder, Gmail nor the keyring. The `outbox`
mailer writes the emails to files in `<data>/outbox/` (development only: refused when listening
beyond loopback).
"""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

from michelito import cli_demo, config

DIR_ENV = "MICHELITO_HOSTED_DIR"
PORT_ENV = "MICHELITO_HOSTED_PORT"
LISTEN_ENV = "MICHELITO_HOSTED_LISTEN"
HOST_ENV = "MICHELITO_HOSTED_HOST"
URL_ENV = "MICHELITO_HOSTED_URL"
DEMO_URL_ENV = "MICHELITO_HOSTED_DEMO_URL"
MAILER_ENV = "MICHELITO_MAILER"
FROM_ENV = "MICHELITO_MAIL_FROM"
PROXIES_ENV = "MICHELITO_HOSTED_PROXIES"
INSECURE_COOKIE_ENV = "MICHELITO_HOSTED_INSECURE_COOKIE"
MASTER_KEY_ENV = "MICHELITO_MASTER_KEY_FILE"
DEFAULT_DIR = "~/michelito-hosted"
DEFAULT_PORT = 8620
DEFAULT_FROM = "Michelito <codigo@auth.michelito.app>"
OUTBOX = "outbox"
LOOPBACK = ("127.0.0.1", "localhost", "::1")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _hosted_dir(text: str | None) -> Path:
    return Path(text or _env(DIR_ENV, DEFAULT_DIR)).expanduser().resolve()


def _mail_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data", metavar="DIR", help=f"the hosted folder (${DIR_ENV}; {DEFAULT_DIR})"
    )
    parser.add_argument(
        "--mailer",
        choices=("resend", "outbox"),
        default=_env(MAILER_ENV, "resend"),
        help="how emails go out: Resend (RESEND_API_KEY[_FILE]) or files in <data>/outbox",
    )
    parser.add_argument(
        "--mail-from", default=_env(FROM_ENV, DEFAULT_FROM), metavar="ADDRESS", help="sender"
    )
    parser.add_argument(
        "--public-url",
        default=_env(URL_ENV, ""),
        metavar="URL",
        help="the address in the emails (https://<public host>)",
    )
    parser.add_argument(
        "--public-host",
        default=_env(HOST_ENV, "michelito.app"),
        metavar="HOST",
        help="the host people arrive with (besides loopback)",
    )


def _master_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--master-key",
        metavar="PATH",
        help=f"the master key file (${MASTER_KEY_ENV}); never inside the data folder",
    )


def add_commands(commands: Any) -> None:
    """Add `hosted`, `invite` and `rotate-master-key` to the `michelito` subcommands."""
    hosted = commands.add_parser("hosted", help="serve hosted mode (accounts, email sign-in)")
    hosted.add_argument(
        "--port", type=int, default=_env(PORT_ENV, str(DEFAULT_PORT)), help=f"port ({DEFAULT_PORT})"
    )
    hosted.add_argument(
        "--listen",
        default=_env(LISTEN_ENV, "127.0.0.1"),
        metavar="ADDRESS",
        help="address to listen on (127.0.0.1; 0.0.0.0 inside a container)",
    )
    hosted.add_argument(
        "--demo-url",
        default=_env(DEMO_URL_ENV, "https://demo.michelito.app"),
        metavar="URL",
        help="the demo linked from the signed-out page",
    )
    hosted.add_argument(
        "--insecure-cookie",
        action="store_true",
        default=_env(INSECURE_COOKIE_ENV, "") == "1",
        help="cookie without Secure: only for testing over http on this machine",
    )
    hosted.add_argument(
        "--trusted-proxy",
        action="append",
        default=[p for p in _env(PROXIES_ENV, "").split(",") if p.strip()],
        metavar="IP_OR_NET",
        help="proxy (Caddy) whose X-Forwarded-For is trusted; repeatable",
    )
    _mail_options(hosted)
    _master_option(hosted)
    hosted.set_defaults(handler=cmd_hosted, server=True)

    invite = commands.add_parser("invite", help="invite one email to hosted mode")
    invite.add_argument("email")
    _mail_options(invite)
    invite.set_defaults(handler=cmd_invite, server=True)

    rotate = commands.add_parser(
        "rotate-master-key", help="re-wrap every data key under a new master key"
    )
    rotate.add_argument(
        "--new", required=True, metavar="PATH", help="the new master key file (0400)"
    )
    rotate.add_argument(
        "--data", metavar="DIR", help=f"the hosted folder (${DIR_ENV}; {DEFAULT_DIR})"
    )
    _master_option(rotate)
    rotate.set_defaults(handler=cmd_rotate, server=True)


def _prepare(args: argparse.Namespace, paths: config.Paths) -> Path | None:
    directory = _hosted_dir(args.data)
    if cli_demo._check_dir(directory, paths):
        print(
            "Error: the hosted folder can neither be nor contain the real data folder.",
            file=sys.stderr,
        )
        return None
    return config.ensure_private_dir(directory)


def _mailer(args: argparse.Namespace, directory: Path) -> Any:
    from michelito.hosted.mailer import OutboxMailer
    from michelito.hosted.resend import ResendMailer, key_from_environment

    if args.mailer == "outbox":
        return OutboxMailer(directory / OUTBOX)
    key = key_from_environment()
    if key is None:
        print("Missing RESEND_API_KEY (or RESEND_API_KEY_FILE).", file=sys.stderr)
        return None
    return ResendMailer(key, args.mail_from)


def _settings(args: argparse.Namespace, directory: Path, **extra: Any) -> Any:
    from michelito.hosted.app import Settings

    return Settings(
        data=directory, public_host=args.public_host, public_url=args.public_url, **extra
    )


def cmd_hosted(args: argparse.Namespace, paths: config.Paths) -> int:
    from michelito.cli import STATIC_DIR

    if args.port in cli_demo.RESERVED_PORTS:
        print(f"Port {args.port} belongs to the local board: pick another one.", file=sys.stderr)
        return 2
    if args.mailer == "outbox" and args.listen not in LOOPBACK:
        print("The outbox mailer is only for this machine: listen on 127.0.0.1.", file=sys.stderr)
        return 2
    if args.insecure_cookie and args.listen not in LOOPBACK:
        print("--insecure-cookie is only for this machine: listen on 127.0.0.1.", file=sys.stderr)
        return 2
    directory = _prepare(args, paths)
    if directory is None:
        return 2
    if not (STATIC_DIR / "index.html").is_file():
        print("The interface is not built: cd frontend && npm ci && npm run build", file=sys.stderr)
        return 1
    mailer = _mailer(args, directory)
    if mailer is None:
        return 2
    import uvicorn

    from michelito.hosted import ops
    from michelito.hosted.app import HostedStateError, create_hosted_app, master_key_path
    from michelito.hosted.auth import KeyStateError
    from michelito.hosted.keys import MasterKeyError
    from michelito.hosted.lock import FolderBusyError, server_lock

    settings = _settings(
        args,
        directory,
        demo_url=args.demo_url,
        secure_cookie=not args.insecure_cookie,
        proxies=tuple(args.trusted_proxy),
        master_key=master_key_path(args.master_key),
    )
    try:
        with server_lock(directory):  # no rotation (nor a second server) meanwhile
            try:
                app = create_hosted_app(settings, mailer, STATIC_DIR)
            except (MasterKeyError, KeyStateError, HostedStateError) as error:
                print(f"Error: {error}", file=sys.stderr)
                return 2
            ops.count_mail_failures(directory)  # for the daily failure email (counts only)
            if args.mailer == "outbox":
                print(f"Emails are written to {directory / OUTBOX} (nothing is sent).")
            print(
                f"Hosted mode at http://{args.listen}:{args.port} (public host {args.public_host})"
            )
            with suppress(KeyboardInterrupt):
                uvicorn.run(
                    app, host=args.listen, port=args.port, log_level="warning", proxy_headers=False
                )
            app.state.dispatcher.stop()
    except FolderBusyError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    return 0


def cmd_invite(args: argparse.Namespace, paths: config.Paths) -> int:
    from michelito.hosted.app import HostedStateError, build_service
    from michelito.hosted.auth import AuthError

    directory = _prepare(args, paths)
    if directory is None:
        return 2
    mailer = _mailer(args, directory)
    if mailer is None:
        return 2
    # An invitation opens no user database: no master key needed.
    try:
        service = build_service(
            _settings(args, directory, background_mail=False), mailer, with_master=False
        )
    except HostedStateError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    messages = {
        "email": "That does not look like an email address.",
        "member": "That email already has an account.",
        "mail": "No email can be sent today (daily cap): try again tomorrow.",
        "send": "The invitation email could not be sent (see the log); try again.",
    }
    try:
        service.invite(args.email)
    except AuthError as error:
        print(messages.get(error.kind, "Could not invite."), file=sys.stderr)
        return 1
    print("Invitation sent (single use, valid for 7 days).")
    return 0


def cmd_rotate(args: argparse.Namespace, paths: config.Paths) -> int:
    from michelito.hosted.app import master_key_path
    from michelito.hosted.keys import MasterKeyError, UnwrapError, load_master
    from michelito.hosted.lock import FolderBusyError, server_lock
    from michelito.hosted.rotation import RotationError, rotate
    from michelito.hosted.store import FILENAME, Store

    directory = _prepare(args, paths)
    if directory is None:
        return 2
    if not (directory / FILENAME).is_file():
        print(f"Error: no accounts database in {directory}.", file=sys.stderr)
        return 2
    try:
        old = load_master(master_key_path(args.master_key), directory)
        new = load_master(Path(args.new), directory)
        with server_lock(directory):  # refused while the server runs
            done = rotate(Store(directory / FILENAME), old, new)
    except UnwrapError:
        print("Error: a data key does not open with the current master key.", file=sys.stderr)
        return 1
    except (MasterKeyError, RotationError, FolderBusyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(
        f"Re-wrapped {done.rewrapped} data key(s) ({done.already} already under the new key). "
        f"Now set {MASTER_KEY_ENV} to the new file and start the server."
    )
    return 0
