"""Pre-rename installs keep working: the old data folder, database file and keyring service are
read as fallbacks (never written), and stored keys translate to their new form. Every test runs
with a temporary HOME and a fake keyring."""

from __future__ import annotations

from pathlib import Path

import pytest

from michelito import config, legacy, sources, vault

CASH = legacy.CASH_FINGERPRINT_PREFIX
PROVIDER = legacy.PROVIDER_PREFIX
RECURRING, PEAK = legacy.RESERVE_KEY_PREFIXES
OLD_DATA_DIR = Path(legacy.DATA_DIR).name


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (f"{CASH}7", "cash-7"),
        (f"{CASH}x", f"{CASH}x"),  # not a cash-entry fingerprint
        ("0123456789abcdef01234567", "0123456789abcdef01234567"),
        (legacy.CASH_BOX_KEY, "manual:cash-box"),
        (f"{PROVIDER}telfic", "provider:telfic"),
        (f"{RECURRING}SEGURO HOGAR:DOP", "recurring:SEGURO HOGAR:DOP"),
        (f"{RECURRING}{PROVIDER}telfic:DOP", "recurring:provider:telfic:DOP"),
        (f"{PEAK}ENTERTAINMENT:12", "peak:ENTERTAINMENT:12"),
        ("irregular:Mascotas", "irregular:Mascotas"),
        ("cash-7", "cash-7"),
        ("provider:telfic", "provider:telfic"),
    ],
)
def test_translate_key(old: str, new: str) -> None:
    assert legacy.translate_key(old) == new
    assert legacy.translate_key(new) == new


def test_translate_series_text() -> None:
    assert legacy.translate_series_text(f"{PROVIDER}telfic · DOP") == "provider:telfic · DOP"
    assert legacy.translate_series_text(f"AGUA, {PROVIDER}luz") == "AGUA, provider:luz"
    assert legacy.translate_series_text("SEGURO HOGAR · DOP") == "SEGURO HOGAR · DOP"


def test_maps_never_reuse_an_old_value_as_a_new_one() -> None:
    for values in (
        legacy.CATEGORY_KINDS,
        legacy.REVIEW_KINDS,
        legacy.CADENCES,
        legacy.RECURRING_GROUPS,
        legacy.LOG_TARGET_TYPES,
        legacy.LOG_KINDS,
        legacy.PARSER_NAMES,
    ):
        assert not set(values) & set(values.values())
        assert len(set(values.values())) == len(values)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(config.DATA_DIR_ENV, raising=False)
    return tmp_path


def test_default_data_dir_is_the_new_one(home: Path) -> None:
    assert config.default_paths().root == home / "michelito-data"
    (home / "michelito-data").mkdir()
    (home / OLD_DATA_DIR).mkdir()
    assert config.default_paths().root == home / "michelito-data"


def test_falls_back_to_the_old_data_dir_only_when_it_is_the_only_one(home: Path) -> None:
    (home / OLD_DATA_DIR).mkdir()
    assert config.default_paths().root == home / OLD_DATA_DIR


def test_the_environment_variable_wins(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (home / OLD_DATA_DIR).mkdir()
    monkeypatch.setenv(config.DATA_DIR_ENV, str(home / "chosen"))
    assert config.default_paths().root == home / "chosen"


def test_database_file_falls_back_to_the_old_name(tmp_path: Path) -> None:
    paths = config.Paths(tmp_path)
    assert paths.database == tmp_path / "michelito.db"
    (tmp_path / legacy.DATABASE_FILE).touch()
    assert paths.database == tmp_path / legacy.DATABASE_FILE
    (tmp_path / "michelito.db").touch()
    assert paths.database == tmp_path / "michelito.db"


def test_old_import_names_stay_reserved_for_sources() -> None:
    assert {"imported", legacy.IMPORT_SOURCE, legacy.IMPORT_FOLDER} <= sources.RESERVED_NAMES


class FakeKeyring:
    def __init__(self, stored: dict[tuple[str, str], str]) -> None:
        self.stored = dict(stored)

    def get_password(self, service: str, name: str) -> str | None:
        return self.stored.get((service, name))

    def set_password(self, service: str, name: str, value: str) -> None:
        self.stored[(service, name)] = value


@pytest.fixture
def keyring(monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    fake = FakeKeyring({(legacy.KEYRING_SERVICE, vault.PDF_PASSWORD): "old-value"})
    monkeypatch.setattr(vault, "ensure_secure_backend", lambda: None)
    monkeypatch.setattr("keyring.get_password", fake.get_password)
    monkeypatch.setattr("keyring.set_password", fake.set_password)
    return fake


def test_a_secret_saved_before_the_rename_is_still_read(keyring: FakeKeyring) -> None:
    assert vault.SERVICE == "michelito"
    assert vault.get_secret(vault.PDF_PASSWORD) == "old-value"
    assert ("michelito", vault.PDF_PASSWORD) not in keyring.stored  # read, never copied


def test_the_new_service_wins_and_writes_go_only_there(keyring: FakeKeyring) -> None:
    vault.set_secret(vault.PDF_PASSWORD, "new-value")
    assert keyring.stored == {
        (legacy.KEYRING_SERVICE, vault.PDF_PASSWORD): "old-value",
        ("michelito", vault.PDF_PASSWORD): "new-value",
    }
    assert vault.get_secret(vault.PDF_PASSWORD) == "new-value"


def test_missing_in_both_services_is_an_error(keyring: FakeKeyring) -> None:
    with pytest.raises(vault.MissingSecretError):
        vault.get_secret(vault.GMAIL_TOKEN)
