"""Access to the secrets saved in the system keyring (GNOME Keyring)."""

from __future__ import annotations

import keyring

from michelito import legacy

SERVICE = "michelito"
PDF_PASSWORD = "pdf-password"
GMAIL_TOKEN = "gmail-token"
GMAIL_CLIENT = "gmail-client"

_HINTS = {
    PDF_PASSWORD: "save it with: michelito secret pdf-password",
    GMAIL_TOKEN: "authorize Gmail with: michelito auth",
    GMAIL_CLIENT: "the first time run: michelito auth --client-secrets <file.json>",
}


class MissingSecretError(RuntimeError):
    """The requested secret is not in the keyring."""


class InsecureKeyringError(RuntimeError):
    """The active keyring backend would store the secrets in a readable file."""


_PLAINTEXT_MARKERS = ("keyrings.alt", "plaintext", "file")


def ensure_secure_backend(backend: object | None = None) -> None:
    """Refuse backends that store the secrets as plain text on disk."""
    active = backend if backend is not None else keyring.get_keyring()
    kind = f"{type(active).__module__}.{type(active).__name__}".lower()
    if any(marker in kind for marker in _PLAINTEXT_MARKERS):
        raise InsecureKeyringError(
            f"the active keyring ({kind}) stores secrets as plain text; use GNOME Keyring"
        )


def get_secret(name: str) -> str:
    ensure_secure_backend()
    # A secret saved before the rename is still read from the old service (never copied).
    value = keyring.get_password(SERVICE, name) or keyring.get_password(
        legacy.KEYRING_SERVICE, name
    )
    if not value:
        hint = _HINTS.get(name, "save it in the keyring")
        raise MissingSecretError(f"the secret '{name}' is missing from the keyring; {hint}")
    return value


def set_secret(name: str, value: str) -> None:
    ensure_secure_backend()
    keyring.set_password(SERVICE, name, value)
