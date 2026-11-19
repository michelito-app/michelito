import pytest

from finanzas import vault


class PlaintextKeyring:
    pass


class SecretServiceKeyring:
    pass


def test_rejects_plaintext_backends() -> None:
    with pytest.raises(vault.InsecureKeyringError):
        vault.ensure_secure_backend(PlaintextKeyring())


def test_accepts_secret_service() -> None:
    vault.ensure_secure_backend(SecretServiceKeyring())


def test_missing_secret_has_a_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vault, "ensure_secure_backend", lambda: None)
    monkeypatch.setattr("keyring.get_password", lambda service, name: None)
    with pytest.raises(vault.MissingSecretError, match="finanzas auth"):
        vault.get_secret(vault.GMAIL_TOKEN)
