"""Sign-in by email code, sessions, step-up and invitations (the rules in `login.md`).

- **Codes**: 6 digits, 10 minutes, single use, 5 attempts in total (counted before comparing,
  so parallel guesses cannot exceed it); only the newest code of an email is ever checked (a
  new one invalidates the older ones). The emailed link keeps working. Only a keyed
  hash is stored (HMAC-SHA256 with the server's secret, over the email and the code): a copy of
  the accounts database alone does not reveal them. The same email may carry a desktop link with
  a separate 256-bit token (also stored hashed); the link puts it in the URL *fragment*, which
  never reaches the server or its logs.
- **No enumeration**: asking for a code answers the same whether or not the email has an account
  or an invitation (the limits count every email alike, and the email goes out in the
  background, see `mailer.Dispatcher`); a wrong code and an email without an account fail alike.
- **Sessions**: an opaque 256-bit token in the cookie, only its SHA-256 stored; 30 days idle,
  90 days absolute; revoking deletes the row, so it is immediate.
- **Step-up**: a verification (the sign-in itself or a new code) within the last 10 minutes.
- **Invitations**: signing up needs an unused invitation for that email; without one, no account
  is ever created.
- **Encrypted databases**: each account's database is encrypted with its own data key, stored
  only wrapped by the master key (`hosted.keys`). The key is unwrapped for each request that
  has a session of that account (`workspace`) and never kept between requests.
- **Deleting an account** destroys its wrapped key first (crypto-shredding, `delete_account`),
  then its files; a tombstoned folder left behind by a crash is removed by `remove_deleted`.

Nothing here logs or returns a code, a link token or a session token, except the session token
handed to the route that sets the cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from michelito import config, db, encrypted
from michelito.hosted import devices, keys
from michelito.hosted.guard import Guard
from michelito.hosted.keys import MasterKey
from michelito.hosted.limits import Caps, Keys
from michelito.hosted.mailer import Dispatcher, Email
from michelito.hosted.store import FOLDER, Account, Session, Store
from michelito.i18n import t
from michelito.web.workspace import Workspace

EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]+\.[^@\s]+")
EMAIL_MAX = 254
CODE = re.compile(r"\d{6}")
DATABASE = "michelito.db"
HOLDERS = "holders.txt"
USERS = "users"
DAY = 24 * 3600
SIGN_IN = ("login", "invitation")  # what the anonymous sign-in checks
STEP_UP = ("step_up",)  # only for the session that asked
SEALING = ".sealing"  # suffix of a placeholder's encrypted copy while it is being written
LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Policy:
    code_ttl: int = 10 * 60
    max_attempts: int = 5  # attempts per code, from every source together
    idle: int = 30 * DAY
    absolute: int = 90 * DAY
    step_up: int = 10 * 60
    invitation_ttl: int = 7 * DAY
    touch_every: int = 60  # how often a session's last activity is written
    known_device_ttl: int = 90 * DAY  # a known device lasts at most this
    email_link: bool = True  # the desktop link in the code email
    user_invitations: bool = False  # people inviting people: off (only the owner, by CLI)


class KeyStateError(Exception):
    """The accounts database and the master key do not match (the server must not start)."""


class AuthError(Exception):
    """Why a sign-in step failed; `kind` picks the status and the message (`routes`)."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


def normalize(email: str) -> str:
    return email.strip().lower()


def valid_email(email: str) -> bool:
    return len(email) <= EMAIL_MAX and EMAIL.fullmatch(email) is not None


def mask(email: str) -> str:
    """ "a•••@example.com": enough to recognize one's own address, not to learn someone's."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}•••@{domain}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class SignIn:
    """The sign-in service over the accounts `store`; per-user folders live under `root`."""

    def __init__(
        self,
        store: Store,
        dispatcher: Dispatcher,
        secret: bytes,
        root: Path,
        public_url: str,
        policy: Policy | None = None,
        caps: Caps | None = None,
        clock: Callable[[], float] = time.time,
        master: MasterKey | None = None,
    ) -> None:
        """`master`: the master key; without it (`michelito invite`) no account can be created
        and no database opened."""
        if len(secret) < 32:
            raise ValueError("the hosted secret must have at least 32 bytes")
        self.store = store
        self.dispatcher = dispatcher
        self._secret = secret
        self.root = root
        self.public_url = public_url.rstrip("/")
        self.policy = policy or Policy()
        caps = caps or Caps()
        self.clock = clock
        self._caps = caps
        self._guard = Guard(caps, clock)
        self._master = master

    def __repr__(self) -> str:
        return f"SignIn(root={self.root!r})"

    # Hashes.

    def _keyed(self, *parts: str) -> str:
        message = "\0".join(parts).encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def _now(self) -> int:
        return int(self.clock())

    # Known devices.

    def remember_device(self, email: str) -> str:
        """The known-device cookie for a browser that just signed in to `email`: a random
        token, of which only the hash is stored (with the account, for `known_device_ttl`). It
        names nobody and dies with sign-out-everywhere, the account's deletion or suspension."""
        account = self.store.account_by_email(normalize(email))
        if account is None:
            raise AuthError("code")
        token = secrets.token_urlsafe(32)
        now = self._now()
        expires = now + self.policy.known_device_ttl
        self.store.add_known_device(account.id, _sha256(f"device\0{token}"), now, expires)
        return token

    def knows_device(self, cookie: str | None, email: str) -> bool:
        """Whether that cookie is a live known device of the active account of `email`."""
        if not cookie or len(cookie) > 128:
            return False
        account = self.store.known_device(_sha256(f"device\0{cookie}"), self._now())
        return (
            account is not None
            and account.status == "active"
            and hmac.compare_digest(account.email, normalize(email))
        )

    # Codes.

    def request_code(self, email: str, source: Keys, trusted: bool = False) -> None:
        """Send a sign-in code if the email has an account or an open invitation; the caller
        answers the same either way. `source`: the requester's IP buckets
        (`network.quota_keys`). `trusted`: a session of that account or a known device (the
        per-email limits do not apply). `AuthError("rate")` over a visible limit, `("mail")`
        when no email can go out today."""
        email = normalize(email)
        key = self._keyed("email", email)
        if not self._guard.code_request(key, source, trusted):
            raise AuthError("rate")
        if not self.dispatcher.available():
            raise AuthError("mail")
        now = self._now()
        account = self.store.account_by_email(email)
        invited = None if account else self.store.open_invitation(email, now)
        if (account is None and invited is None) or (account and account.status != "active"):
            return
        if not self._may_send(email, key, source, now, trusted, SIGN_IN):
            return  # silently: the answer is the same, so nothing is revealed
        code, link = self._new_code(email, "login", now, now + self.policy.code_ttl)
        self.dispatcher.submit(self._code_email(email, code, link))

    def _may_send(
        self,
        email: str,
        key: str,
        source: Keys,
        now: int,
        trusted: bool,
        purposes: tuple[str, ...],
        session_id: int | None = None,
    ) -> bool:
        """The silent limits on emails actually sent (`guard.Guard.may_send`), and no second
        email while a code younger than `resend_after` is already in the inbox."""
        newest = self.store.newest_code_at(email, now, purposes, session_id)
        if newest is not None and now - newest < self._caps.resend_after:
            return False
        return self._guard.may_send(key, source, trusted)

    def _new_code(
        self,
        email: str,
        purpose: str,
        now: int,
        expires: int,
        invitation: int | None = None,
        with_link: bool = True,
        session_id: int | None = None,
    ) -> tuple[str, str | None]:
        code = f"{secrets.randbelow(10**6):06d}"
        link = secrets.token_urlsafe(32) if with_link and self.policy.email_link else None
        link_hash = self._keyed("link", link) if link else None
        code_hash = self._keyed("code", email, code)
        self.store.add_code(
            email, purpose, code_hash, link_hash, now, expires, invitation, session_id
        )
        return code, link

    def _code_email(self, email: str, code: str, link: str | None) -> Email:
        minutes = self.policy.code_ttl // 60
        extra = t("hosted.email.link", url=f"{self.public_url}/#link={link}") if link else ""
        text = t("hosted.email.code_body", code=code, minutes=minutes, link=extra)
        return Email(email, t("hosted.email.code_subject"), text)

    def _matching(
        self, email: str, code: str, purposes: tuple[str, ...], session_id: int | None = None
    ) -> int | None:
        """The id of the email's newest live code if `code` is it. The attempt is counted in
        the database **before** comparing (`store.reserve_attempt`): after `max_attempts`
        attempts from anyone, nothing is compared against that code any more."""
        candidate = self._keyed("code", email, code)
        reserved = self.store.reserve_attempt(
            email, self._now(), self.policy.max_attempts, purposes, session_id
        )
        if reserved is None:
            return None
        if not hmac.compare_digest(reserved.code_hash, candidate):
            return None
        if reserved.purpose == "invitation" and self.store.account_by_email(email) is not None:
            return None  # an invitation code only works while there is no account
        return reserved.id

    def verify(
        self,
        email: str,
        code: str,
        user_agent: str | None,
        source: Keys,
        trusted: bool = False,
    ) -> str:
        """A new session token for a right code; `AuthError("code")` otherwise, `("rate")`
        over the per-network checks or (unless `trusted`: a known device of that account) the
        email's spread-out checks this hour."""
        email = normalize(email)
        if not self._guard.check(self._keyed("email", email), source, trusted):
            raise AuthError("rate")
        if CODE.fullmatch(code) is None:
            raise AuthError("code")
        found = self._matching(email, code, SIGN_IN)  # never a step-up code
        if found is None:
            raise AuthError("code")
        return self._complete(found, email, user_agent)

    def peek_link(self, token: str, source: Keys) -> str:
        """The masked email a desktop link would sign in to, without using it (so the page can
        ask the person to confirm first, and a link planted by someone else does nothing)."""
        if not self._guard.check("", source, trusted=True):
            raise AuthError("rate")
        found = self.store.code_by_link(self._keyed("link", token), self._now())
        if found is None:
            raise AuthError("code")
        return mask(found.email)

    def verify_link(self, token: str, user_agent: str | None, source: Keys) -> tuple[str, str]:
        """Like `verify`, with the desktop link's token; returns (session token, email). Wrong
        codes do not disable it: the link only reaches the inbox and cannot be guessed."""
        if not self._guard.check("", source, trusted=True):  # the link: per network only
            raise AuthError("rate")
        found = self.store.code_by_link(self._keyed("link", token), self._now())
        if found is None:
            raise AuthError("code")
        if found.purpose == "invitation" and self.store.account_by_email(found.email):
            raise AuthError("code")
        return self._complete(found.id, found.email, user_agent), found.email

    def _complete(self, code_id: int, email: str, user_agent: str | None) -> str:
        now = self._now()
        if not self.store.use_code(code_id, now):
            raise AuthError("code")
        account = self.store.account_by_email(email)
        if account is None:
            invitation = self.store.open_invitation(email, now)
            if invitation is None:  # no invitation: never an account
                raise AuthError("code")
            account = self._create_account(email, invitation, now)
        if account.status != "active":
            raise AuthError("code")
        token = secrets.token_urlsafe(32)
        browser, system = devices.describe(user_agent)
        self.store.add_session(account.id, _sha256(token), now, browser, system)
        return token

    def _create_account(self, email: str, invitation: int, now: int) -> Account:
        master = self._require_master()
        folder = secrets.token_hex(16)
        data_key = keys.new_data_key()

        def seal(account_id: int) -> tuple[bytes, str]:
            return keys.wrap(master, data_key, account_id, folder), master.id

        try:
            account = self.store.create_account(email, folder, now, invitation, seal)
        except LookupError:
            # Two first sign-ins at once: the other one created it; this one goes on with it.
            existing = self.store.account_by_email(email)
            if existing is None:
                raise AuthError("code") from None
            return existing
        self._create_database(folder, data_key)
        return account

    def _require_master(self) -> MasterKey:
        if self._master is None:
            raise KeyStateError("no master key: this process cannot open user databases")
        return self._master

    def _place(self, folder: str) -> Path:
        if not FOLDER.fullmatch(folder):
            raise ValueError("bad folder name")
        return self.root / USERS / folder

    def _create_database(self, folder: str, data_key: bytes) -> None:
        """The account's empty database, encrypted with its data key."""
        place = config.ensure_private_dir(self._place(folder))
        db.connect(place / DATABASE, data_key).close()

    def _data_key(self, account: Account) -> bytes:
        stored = self.store.data_key(account.id)
        if stored is None:
            raise KeyStateError("an account without a data key")
        return keys.unwrap(self._require_master(), stored.wrapped, account.id, account.folder)

    # Keys at start-up: placeholders, a matching master key, deleted folders.

    def check_keys(self) -> None:
        """Refuse to serve when a data key is wrapped by another master key (an unfinished
        rotation, or the wrong key file): `KeyStateError`, naming no key."""
        master = self._require_master()
        foreign = [k for k in self.store.data_keys() if k.master_id != master.id]
        if foreign:
            raise KeyStateError(
                f"{len(foreign)} data key(s) are wrapped by another master key: finish "
                "`michelito rotate-master-key` or configure the right key file"
            )

    def seal_placeholders(self) -> int:
        """Encrypt the plain placeholder databases of batch 1 (development only: no real
        accounts had them). Each one first gets its wrapped key, then its file is replaced by
        an encrypted copy, so a crash at any point is finished by the next start. Returns how
        many files were encrypted."""
        master = self._require_master()
        now = self._now()
        for account in self.store.accounts_without_key():
            data_key = keys.new_data_key()
            wrapped = keys.wrap(master, data_key, account.id, account.folder)
            self.store.add_data_key(account.id, wrapped, master.id, now)
        sealed = 0
        for stored in self.store.data_keys():
            place = self._place(stored.folder)
            database = place / DATABASE
            if not database.is_file() or not encrypted.is_plain(database):
                continue
            data_key = keys.unwrap(master, stored.wrapped, stored.account_id, stored.folder)
            copy = place / f"{DATABASE}{SEALING}"
            copy.unlink(missing_ok=True)
            encrypted.encrypt_copy(database, copy, data_key)
            for leftover in (f"{DATABASE}-journal", f"{DATABASE}-wal", f"{DATABASE}-shm"):
                (place / leftover).unlink(missing_ok=True)
            os.replace(copy, database)
            sealed += 1
        return sealed

    def remove_deleted(self) -> int:
        """Remove the folders of deleted accounts that are still on disk (a deletion that could
        not finish removing its files: their key is already gone). Only folders with a tombstone
        are touched, never one that is merely unknown. Returns how many were removed."""
        removed = 0
        for folder in self.store.deleted_folders():
            if self._remove_folder(folder):
                removed += 1
        return removed

    def _remove_folder(self, folder: str) -> bool:
        """Remove a tombstoned folder and then its tombstone; False if it could not."""
        place = self._place(folder)
        try:
            if place.is_symlink():
                place.unlink()
            elif place.exists():
                shutil.rmtree(place)
        except OSError as error:  # the key is gone already: tried again at the next start
            LOG.warning("could not remove a deleted account's folder: %s", error.strerror)
            return False
        self.store.forget_deleted_folder(folder)
        return True

    # Sessions.

    def lookup(self, token: str | None) -> Session | None:
        """The live session of that cookie (sliding: it refreshes its last activity)."""
        if not token or len(token) > 128:
            return None
        session = self.store.session_by_token(_sha256(token))
        if session is None:
            return None
        now = self._now()
        expired = (
            now - session.created_at > self.policy.absolute
            or now - session.last_seen_at > self.policy.idle
            or session.account.status != "active"
        )
        if expired:
            self.store.delete_session(session.id)
            return None
        if now - session.last_seen_at >= self.policy.touch_every:
            self.store.touch_session(session.id, now)
        return session

    def workspace(self, session: Session) -> Workspace:
        """The session's own database (only its account's folder), with its data key just
        unwrapped (it lives as long as the request)."""
        place = self._place(session.account.folder)
        key = self._data_key(session.account)
        if not place.is_dir():
            # The account was committed but the server stopped before making its folder: the
            # key exists, so make it now (the database is created encrypted on first use).
            config.ensure_private_dir(place)
        return Workspace(place / DATABASE, place / HOLDERS, key=key)

    def delete_account(self, session: Session) -> None:
        """Delete the session's account (step-up required): its wrapped data key is destroyed
        together with the account row, in one transaction that also tombstones its folder,
        **before** any file is touched. From then on its database is unreadable on this server
        (and in backups once the older backups of `accounts.db` expire). Then its folder is
        removed; if that fails, `remove_deleted` finishes it at the next start."""
        self.require_step_up(session)
        deleted = self.store.delete_account(session.account.id, self._now())
        if deleted is not None:
            self._remove_folder(deleted.folder)

    def sign_out(self, session: Session) -> None:
        self.store.delete_session(session.id)

    def sign_out_everywhere(self, session: Session) -> int:
        self.require_step_up(session)
        return self.store.delete_sessions_of(session.account.id)

    # Step-up.

    def fresh(self, session: Session) -> bool:
        return self._now() - session.verified_at <= self.policy.step_up

    def require_step_up(self, session: Session) -> None:
        if not self.fresh(session):
            raise AuthError("step_up")

    def request_step_up(self, session: Session, source: Keys) -> None:
        """A code for the session's own email (the per-email limits never block it)."""
        email = session.account.email
        if not self._guard.code_request(self._keyed("email", email), source, trusted=True):
            raise AuthError("rate")
        if not self.dispatcher.available():
            raise AuthError("mail")
        now = self._now()
        key = self._keyed("email", email)
        if not self._may_send(email, key, source, now, True, STEP_UP, session.id):
            return  # this session's step-up code from moments ago is in the inbox
        # A step-up is confirmed in the same browser: its email carries no link. The code is
        # bound to this session: no other session nor the anonymous sign-in can use it.
        expires = now + self.policy.code_ttl
        code, _ = self._new_code(
            email, "step_up", now, expires, with_link=False, session_id=session.id
        )
        self.dispatcher.submit(self._code_email(email, code, None))

    def verify_step_up(self, session: Session, code: str, source: Keys) -> None:
        email = session.account.email
        if not self._guard.check(self._keyed("email", email), source, trusted=True):
            raise AuthError("rate")
        if CODE.fullmatch(code) is None:
            raise AuthError("code")
        found = self._matching(email, code, STEP_UP, session.id)
        if found is None or not self.store.use_code(found, self._now()):
            raise AuthError("code")
        self.store.mark_verified(session.id, self._now())

    # Invitations.

    def invite(self, email: str, invited_by: int | None = None) -> None:
        """A single-use invitation for that email, with its code by email. `AuthError("member")`
        if the email already has an account, `("mail")` if no email can go out today, `("send")`
        if it could not be sent (sending inline)."""
        email = normalize(email)
        if not valid_email(email):
            raise AuthError("email")
        if self.store.account_by_email(email) is not None:
            raise AuthError("member")
        if not self.dispatcher.available():
            raise AuthError("mail")
        now = self._now()
        expires = now + self.policy.invitation_ttl
        invitation = self.store.create_invitation(email, now, expires, invited_by)
        code, link = self._new_code(email, "invitation", now, expires, invitation)
        extra = t("hosted.email.link", url=f"{self.public_url}/#link={link}") if link else ""
        text = t(
            "hosted.email.invite_body",
            code=code,
            days=self.policy.invitation_ttl // DAY,
            url=self.public_url,
            link=extra,
        )
        if not self.dispatcher.submit(Email(email, t("hosted.email.invite_subject"), text)):
            raise AuthError("send")
