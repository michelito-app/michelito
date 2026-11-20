"""Operations commands for hosted mode (see the README, "Hosted deployment").

    michelito export-account --out FILE                     (the owner's machine)
    michelito import-account --email E --from FILE [--replace --confirm-replace E]
    michelito verify-import --months M1,M2,M3 [--email E] [--exact]
    michelito backup [--to DIR --keep N]                    (R2 by default)
    michelito restore (--from-r2 | --from-dir DIR) --date D --data EMPTY_DIR
    michelito ops-check [--to EMAIL]
    michelito pdf-worker --socket PATH                      (the `pdfworker` container)

`export-account` reads the local data folder; the rest work on the hosted folder and, except
`export-account`, run inside the hosted container (`MICHELITO_MODE=hosted`). None of them prints
or logs a key, a credential or a financial value; `verify-import` prints its figures (hashes by
default) to the terminal only.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

from michelito import cli_hosted, config

MODE_ENV = "MICHELITO_MODE"
OPS_EMAIL_ENV = "MICHELITO_OPS_EMAIL"
BACKUP_KEEP = 10


def hosted_mode() -> bool:
    """`MICHELITO_MODE=hosted` (the hosted container): only server commands run."""
    return os.environ.get(MODE_ENV, "").strip().lower() == "hosted"


def _months(text: str) -> list[str]:
    found = [m.strip() for m in text.split(",") if m.strip()]
    for month in found:
        if len(month) != 7 or month[4] != "-" or not (month[:4] + month[5:]).isdigit():
            raise argparse.ArgumentTypeError(f"invalid month '{month}'; use YYYY-MM")
    if not found:
        raise argparse.ArgumentTypeError("at least one month")
    return found


def _hosted_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data",
        metavar="DIR",
        help=f"the hosted folder (${cli_hosted.DIR_ENV}; ~/michelito-hosted)",
    )
    cli_hosted._master_option(parser)


def add_commands(commands: Any) -> None:
    export = commands.add_parser("export-account", help="export the local database for hosting")
    export.add_argument("--out", required=True, type=Path, metavar="FILE", help="new file (0600)")
    export.set_defaults(handler=cmd_export)

    imp = commands.add_parser("import-account", help="create a hosted account from an export")
    imp.add_argument("--email", required=True)
    imp.add_argument("--from", dest="source", required=True, type=Path, metavar="FILE")
    imp.add_argument("--replace", action="store_true", help="replace an existing account")
    imp.add_argument(
        "--confirm-replace", metavar="EMAIL", help="the same email again, to confirm --replace"
    )
    _hosted_options(imp)
    imp.set_defaults(handler=cmd_import, server=True)

    verify = commands.add_parser("verify-import", help="figures to compare local and hosted")
    verify.add_argument("--months", required=True, type=_months, metavar="M1,M2,M3")
    verify.add_argument("--email", help="the hosted account (without it: the local database)")
    verify.add_argument("--exact", action="store_true", help="the numbers instead of hashes")
    verify.add_argument(
        "--today", type=date.fromisoformat, default=None, metavar="YYYY-MM-DD", help="as of"
    )
    _hosted_options(verify)
    verify.set_defaults(handler=cmd_verify, server=True)

    backup = commands.add_parser("backup", help="back up the hosted folder (R2 by default)")
    backup.add_argument("--to", type=Path, metavar="DIR", help="a local folder instead of R2")
    backup.add_argument("--keep", type=int, default=BACKUP_KEEP, help="with --to: how many")
    backup.add_argument("--label", default="", help="with --to: a suffix (the version)")
    backup.add_argument(
        "--skip-empty", action="store_true", help="succeed when there is no accounts database"
    )
    _hosted_options(backup)
    backup.set_defaults(handler=cmd_backup, server=True)

    restore = commands.add_parser("restore", help="restore a backup onto an empty folder")
    source = restore.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-r2", action="store_true", help="from R2 (MICHELITO_R2_*)")
    source.add_argument("--from-dir", type=Path, metavar="DIR", help="from a local backup folder")
    restore.add_argument("--date", required=True, metavar="LABEL", help="YYYY-MM-DD or latest")
    _hosted_options(restore)
    restore.set_defaults(handler=cmd_restore, server=True)

    worker = commands.add_parser(
        "pdf-worker", help="read uploaded PDFs for the hosted app over a Unix socket"
    )
    worker.add_argument("--socket", required=True, type=Path, metavar="PATH")
    worker.add_argument("--slots", type=int, default=2, help="PDFs read at once (2)")
    worker.add_argument("--server-uid", type=int, help="started as root: the server's uid")
    worker.add_argument(
        "--child-uid", type=int, help="started as root: the first of --slots worker uids"
    )
    worker.add_argument("--client-gid", type=int, help="started as root: the hosted app's gid")
    worker.add_argument(
        "--children", type=Path, default=Path("/tmp/michelito-pdf-children"), metavar="DIR"
    )
    worker.set_defaults(handler=cmd_pdf_worker, server=True)

    check = commands.add_parser("ops-check", help="email the owner if something failed")
    check.add_argument(
        "--to", default=os.environ.get(OPS_EMAIL_ENV, ""), metavar="EMAIL", help="the owner"
    )
    check.add_argument(
        "--mailer",
        choices=("resend", "outbox"),
        default=os.environ.get(cli_hosted.MAILER_ENV, "resend"),
    )
    check.add_argument(
        "--mail-from", default=os.environ.get(cli_hosted.FROM_ENV, cli_hosted.DEFAULT_FROM)
    )
    _hosted_options(check)
    check.set_defaults(handler=cmd_ops_check, server=True)


def _error(message: str, code: int = 1) -> int:
    print(f"Error: {message}", file=sys.stderr)
    return code


def _master(args: argparse.Namespace, directory: Path) -> Any:
    from michelito.hosted.app import master_key_path
    from michelito.hosted.keys import load_master

    return load_master(master_key_path(args.master_key), directory)


def _hosted_dir(args: argparse.Namespace, paths: config.Paths) -> Path | None:
    return cli_hosted._prepare(args, paths)


# export-account


def _keyring_secrets() -> tuple[list[str], bool]:
    """The PDF password and Gmail token, only to check they are not in the export."""
    from michelito import vault

    found = []
    reachable = True
    for name in (vault.PDF_PASSWORD, vault.GMAIL_TOKEN):
        try:
            found.append(vault.get_secret(name))
        except vault.MissingSecretError:
            continue
        except Exception:  # noqa: BLE001 (no keyring here: the structural check still runs)
            reachable = False
    return found, reachable


def cmd_export(args: argparse.Namespace, paths: config.Paths) -> int:
    from michelito.hosted.transfer import TransferError, export_account

    found, reachable = _keyring_secrets()
    try:
        done = export_account(paths.database, args.out, paths.holders, found)
    except TransferError as error:
        return _error(str(error))
    print(f"Exported to {done.path} (0600): schema {done.schema_version}, {done.tables} tables.")
    if reachable:
        print("Checked: no keyring secret (PDF password, Gmail token) is in the file.")
    else:
        print("The keyring was not reachable: only checked that no table holds secrets.")
    print("Copy it to the server's import folder (scp), then delete it here.")
    return 0


# import-account


def cmd_import(args: argparse.Namespace, paths: config.Paths) -> int:
    from michelito.hosted.auth import normalize
    from michelito.hosted.keys import MasterKeyError
    from michelito.hosted.store import FILENAME, Store
    from michelito.hosted.transfer import PlaintextNotRemoved, TransferError, import_account

    if args.replace and normalize(args.confirm_replace or "") != normalize(args.email):
        return _error(
            "--replace deletes the existing account: confirm with --confirm-replace EMAIL", 2
        )
    directory = _hosted_dir(args, paths)
    if directory is None:
        return 2
    try:
        master = _master(args, directory)
        done = import_account(
            Store(directory / FILENAME), master, directory, args.email, args.source, args.replace
        )
    except PlaintextNotRemoved as error:
        print(
            "The account was imported, but the plaintext export was NOT removed "
            f"({error}).\nRemove it by hand now: shred -u {error.path}",
            file=sys.stderr,
        )
        return 1
    except (MasterKeyError, TransferError) as error:
        print(f"Error: {error}", file=sys.stderr)
        print(f"Nothing was imported; {args.source} was not removed.", file=sys.stderr)
        return 1
    action = "Replaced" if done.replaced else "Created"
    print(
        f"{action} the account (schema {done.schema_from} -> {done.schema_to}, {done.tables} "
        "tables): encrypted, migrated, integrity and every table's rows checked."
    )
    print(f"The plaintext export was {done.removed.note}.")
    return 0


# verify-import


def cmd_verify(args: argparse.Namespace, paths: config.Paths) -> int:
    from michelito.hosted import figures
    from michelito.web.workspace import Workspace

    if figures.refuse_file(sys.stdout):
        return _error("the figures only go to the terminal, not to a file", 2)
    today = args.today or date.today()
    if args.email:
        workspace = _hosted_workspace(args, paths)
        if workspace is None:
            return 1
    elif hosted_mode():
        return _error("in the hosted container, name the account with --email", 2)
    else:
        if not paths.database.is_file():
            return _error(f"there is no database at {paths.database}")
        workspace = Workspace(paths.database, paths.holders)
    try:
        figures.show(workspace, args.months, today, args.exact)
    except figures.FiguresError as error:
        return _error(str(error))
    return 0


def _hosted_workspace(args: argparse.Namespace, paths: config.Paths) -> Any:
    from michelito.hosted import auth, keys
    from michelito.hosted.keys import MasterKeyError
    from michelito.hosted.store import FILENAME, Store
    from michelito.web.workspace import Workspace

    directory = _hosted_dir(args, paths)
    if directory is None or not (directory / FILENAME).is_file():
        _error("no accounts database in the hosted folder")
        return None
    store = Store(directory / FILENAME)
    account = store.account_by_email(auth.normalize(args.email))
    stored = store.data_key(account.id) if account else None
    if account is None or stored is None:
        _error("that email has no account")
        return None
    try:
        key = keys.unwrap(_master(args, directory), stored.wrapped, account.id, account.folder)
    except (MasterKeyError, keys.UnwrapError) as error:
        _error(str(error))
        return None
    place = directory / auth.USERS / account.folder
    return Workspace(place / auth.DATABASE, place / auth.HOLDERS, key=key)


# backup


def cmd_backup(args: argparse.Namespace, paths: config.Paths) -> int:
    from michelito.hosted import backup, ops, s3
    from michelito.hosted.keys import MasterKeyError

    directory = _hosted_dir(args, paths)
    if directory is None:
        return 2
    from michelito.hosted.store import FILENAME

    if args.skip_empty and not (directory / FILENAME).is_file():
        print("No accounts database yet: nothing to back up.")
        return 0
    status = ops.Status(directory)
    try:
        master = _master(args, directory)
        if args.to is not None:
            target: backup.Target = backup.FolderTarget(args.to)
            label = backup.stamp_label(args.label)
            done = backup.run_backup(directory, master, target, label, prefix="")
            deleted = backup.rotate_by_count(target, args.keep)
        else:
            client = s3.Client(s3.bucket_from_environment())
            label = backup.today_label()
            done = backup.run_backup(directory, master, client, label)
            deleted = backup.rotate_by_age(client, date.fromisoformat(label))
    except (MasterKeyError, backup.BackupError, s3.S3Error) as error:
        if args.to is None:
            status.backup_failed(str(error))
        return _error(f"backup failed: {error}")
    if args.to is None:
        status.backup_succeeded(done.label)
    size = sum(e.size for e in done.entries)
    print(
        f"Backup {done.label}: {len(done.entries)} file(s), {size} bytes, each read back and "
        f"checked; {len(deleted)} old backup(s) removed."
    )
    return 0


# restore


def cmd_restore(args: argparse.Namespace, paths: config.Paths) -> int:
    from michelito.hosted import backup, restore, s3
    from michelito.hosted.keys import MasterKeyError

    directory = cli_hosted._hosted_dir(args.data)
    if cli_hosted.cli_demo._check_dir(directory, paths):
        return _error("the hosted folder can neither be nor contain the real data folder.", 2)
    try:
        from michelito.hosted.app import master_key_path
        from michelito.hosted.keys import load_master

        master = load_master(master_key_path(args.master_key), directory)
        if args.from_r2:
            target: backup.Target = s3.Client(s3.bucket_from_environment())
            prefix = backup.R2_PREFIX
        else:
            target, prefix = backup.FolderTarget(args.from_dir), ""
        done = restore.restore(target, master, directory, args.date, prefix)
    except (MasterKeyError, backup.BackupError, s3.S3Error) as error:
        return _error(f"restore failed: {error}")
    print(
        f"Restored backup {done.label} into {directory}: {done.files} file(s), {done.accounts} "
        "account(s); every database opened with its key and passed the integrity checks."
    )
    if done.older:
        print(f"Warning: {done.newest} is a newer backup than the one restored.", file=sys.stderr)
    return 0


# ops-check


def cmd_ops_check(args: argparse.Namespace, paths: config.Paths) -> int:
    from michelito.hosted import ops
    from michelito.hosted.keys import MasterKeyError
    from michelito.hosted.mailer import MailError
    from michelito.hosted.store import FILENAME, Store

    directory = _hosted_dir(args, paths)
    if directory is None:
        return 2
    store = Store(directory / FILENAME) if (directory / FILENAME).is_file() else None
    try:
        master = _master(args, directory)
    except MasterKeyError as error:
        return _error(str(error), 2)
    problems = ops.check(directory, store, master)
    if not problems:
        print("Nothing failed: no email sent.")
        return 0
    for problem in problems:
        print(f"- {problem.kind}: {problem.text}")
    if not args.to:
        return _error(f"set {OPS_EMAIL_ENV} (or --to) to be emailed", 1)
    mailer = cli_hosted._mailer(args, directory)
    if mailer is None:
        return 2
    try:
        ops.notify(mailer, args.to, problems)
    except MailError as error:
        return _error(f"the alert email could not be sent: {error}")
    print("The owner was emailed.")
    return 1


# pdf-worker


def cmd_pdf_worker(args: argparse.Namespace, paths: config.Paths) -> int:
    """The `pdfworker` container: no data folder, no keys; only the socket."""
    from michelito.hosted import pdf_socket

    ids = None
    given = (args.server_uid, args.child_uid, args.client_gid)
    if os.geteuid() == 0:
        pool = range(args.child_uid or 0, (args.child_uid or 0) + max(1, args.slots))
        if (
            None in given
            or 0 in given
            or args.server_uid in pool
            or args.client_gid in pool
            or args.server_uid == args.client_gid
        ):
            return _error(
                "as root, give distinct non-root --server-uid and --child-uid and --client-gid", 2
            )
        ids = pdf_socket.Identities(args.server_uid, args.client_gid, args.child_uid, args.children)
    elif any(v is not None for v in given):
        return _error(
            "--server-uid/--child-uid/--client-gid need the container to start as root", 2
        )
    print(f"Reading PDFs on {args.socket}", flush=True)
    pdf_socket.serve(args.socket, args.slots, ids=ids)
    return 0
