"""Acceso a los secretos guardados en el keyring del sistema (GNOME Keyring)."""

from __future__ import annotations

import keyring

SERVICE = "finanzas"
PDF_PASSWORD = "pdf-password"
GMAIL_TOKEN = "gmail-token"
GMAIL_CLIENT = "gmail-client"

_HINTS = {
    PDF_PASSWORD: "guárdala con: finanzas secret pdf-password",
    GMAIL_TOKEN: "autoriza Gmail con: finanzas auth",
    GMAIL_CLIENT: "la primera vez corre: finanzas auth --client-secrets <archivo.json>",
}


class MissingSecretError(RuntimeError):
    """El secreto pedido no está en el keyring."""


class InsecureKeyringError(RuntimeError):
    """El backend de keyring activo guardaría los secretos en un archivo legible."""


_PLAINTEXT_MARKERS = ("keyrings.alt", "plaintext", "file")


def ensure_secure_backend(backend: object | None = None) -> None:
    """Se niega a usar backends que guardan los secretos en texto plano en disco."""
    active = backend if backend is not None else keyring.get_keyring()
    kind = f"{type(active).__module__}.{type(active).__name__}".lower()
    if any(marker in kind for marker in _PLAINTEXT_MARKERS):
        raise InsecureKeyringError(
            f"el keyring activo ({kind}) guarda secretos en texto plano; usa GNOME Keyring"
        )


def get_secret(name: str) -> str:
    ensure_secure_backend()
    value = keyring.get_password(SERVICE, name)
    if not value:
        hint = _HINTS.get(name, "guárdalo en el keyring")
        raise MissingSecretError(f"falta el secreto '{name}' en el keyring; {hint}")
    return value


def set_secret(name: str, value: str) -> None:
    ensure_secure_backend()
    keyring.set_password(SERVICE, name, value)
