"""Paths, Gmail sources and project constants."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from michelito import legacy

DATA_DIR_ENV = "MICHELITO_DATA_DIR"
# The user's time zone: "today" (scheduled cash occurrences, the 7-day rules, the date ranges)
# is the local date there, whatever the server's clock says.
TIMEZONE_ENV = "MICHELITO_TIMEZONE"
DEFAULT_TIMEZONE = "America/Santo_Domingo"


def local_today(now: datetime | None = None) -> date:
    """Today in the user's zone (`TIMEZONE_ENV`, by default Santo Domingo); an unknown zone
    falls back to the default one."""
    name = os.environ.get(TIMEZONE_ENV) or DEFAULT_TIMEZONE
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    moment = now or datetime.now(UTC)
    return moment.astimezone(zone).date()


DEFAULT_DATA_DIR = "~/michelito-data"
DATABASE_FILE = "michelito.db"
HOLDERS_FILE = "holders.txt"
SOURCES_FILE = "sources.toml"

# From this date on, phase 1 commits to having everything parsed and validated.
COMMIT_FROM = date(2024, 1, 1)
# Days without a new statement before warning that something did not arrive.
OVERDUE_DAYS = 45
# Window for listing emails that arrived without an attachment (notices).
NOTICE_LOOKBACK_DAYS = 60


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def database(self) -> Path:
        """`michelito.db`; an install from before the rename keeps its `finanzas.db` while
        there is no `michelito.db` next to it."""
        return _current_or_legacy(self.root, DATABASE_FILE, legacy.DATABASE_FILE)

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def holders(self) -> Path:
        """The account holders, one per line; it lives only in the data folder (an install
        from before the rename keeps its old file, `legacy.HOLDERS_FILE`, while there is no
        `holders.txt`)."""
        return _current_or_legacy(self.root, HOLDERS_FILE, legacy.HOLDERS_FILE)

    @property
    def sources(self) -> Path:
        """The user's own senders (optional); without this file `DEFAULT_SOURCES` is used. An
        install from before the rename keeps its old file (`legacy.SOURCES_FILE`) while there is no
        `sources.toml` (read with its old keys translated, see `michelito.sources`)."""
        return _current_or_legacy(self.root, SOURCES_FILE, legacy.SOURCES_FILE)


def _current_or_legacy(root: Path, name: str, legacy_name: str) -> Path:
    """`root / name`, or the pre-rename `root / legacy_name` when only that one exists."""
    current = root / name
    previous = root / legacy_name
    if not current.exists() and previous.exists():
        return previous
    return current


@dataclass(frozen=True)
class Source:
    """A sender of account statements and which of its attachments to save."""

    name: str
    query: str
    extensions: tuple[str, ...]
    interpret: bool = True  # False: archived without trying to parse it
    # True: bank alerts (one email per movement, see `michelito.alerts`): parsed in memory, only
    # their fields are stored and nothing is written to raw/; `extensions` is not used.
    alerts: bool = False


# Default senders: the ones `sync` uses when there is no `sources.toml` in the data folder (see
# `sources.example.toml` and `michelito.sources`). The Gmail queries match the banks' Spanish
# sender addresses and subjects.
# spanish-data: begin
DEFAULT_SOURCES: tuple[Source, ...] = (
    Source("popular", "from:estados@popularenlinea.com", (".pdf",)),
    Source(
        "bhd",
        "from:servicios@bhd.com.do subject:(estado OR estados) subject:cuenta",
        (".pdf",),
    ),
    Source(
        "afp_reservas",
        "from:estadoscta@afpreservas.com.do",
        (".pdf", ".jpg", ".jpeg"),
        interpret=False,
    ),
    Source("afp_siembra", "from:estadodecuenta@afpsiembra.com", (".pdf",), interpret=False),
    Source("afp_crecer", "from:info@afpcrecer.com.do subject:cuenta", (".pdf",), interpret=False),
    Source(
        "popular_alerts",
        'from:notificaciones@popularenlinea.com subject:"Notificación de Consumo"',
        (),
        alerts=True,
    ),
)
# spanish-data: end


def archive_only(sources: Iterable[Source]) -> frozenset[str]:
    """The sources saved in the raw archive without being parsed (the AFPs in phase 1)."""
    return frozenset(s.name for s in sources if not s.interpret)


ARCHIVE_ONLY = archive_only(DEFAULT_SOURCES)


def find_source(name: str, sources: Iterable[Source] = DEFAULT_SOURCES) -> Source:
    for source in sources:
        if source.name == name:
            return source
    raise KeyError(f"unknown source: {name}")


def default_paths() -> Paths:
    """The data folder: the environment variable if set; otherwise `~/michelito-data`, or the
    pre-rename `~/finanzas-data` when only that one exists."""
    chosen = os.environ.get(DATA_DIR_ENV)
    if chosen:
        return Paths(Path(chosen).expanduser())
    current = Path(DEFAULT_DATA_DIR).expanduser()
    previous = Path(legacy.DATA_DIR).expanduser()
    if not current.exists() and previous.exists():
        return Paths(previous)
    return Paths(current)


def ensure_private_dir(path: Path) -> Path:
    """Create the folder (if missing) and make it accessible only to the user."""
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path
