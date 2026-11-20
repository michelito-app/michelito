from pathlib import Path

import pytest

from michelito import config, legacy
from michelito.config import DEFAULT_SOURCES, Source
from michelito.sources import SourcesError, archived_names, load_sources

EXAMPLE = Path(__file__).resolve().parent.parent / "sources.example.toml"

# The sources as they were hard-coded in config.py before they could be configured: without
# sources.toml, `sync` must keep asking for exactly this. The queries match the real senders'
# Spanish subjects.
# spanish-data: begin
BEFORE = (
    ("popular", "from:estados@popularenlinea.com", (".pdf",), True),
    (
        "bhd",
        "from:servicios@bhd.com.do subject:(estado OR estados) subject:cuenta",
        (".pdf",),
        True,
    ),
    ("afp_reservas", "from:estadoscta@afpreservas.com.do", (".pdf", ".jpg", ".jpeg"), False),
    ("afp_siembra", "from:estadodecuenta@afpsiembra.com", (".pdf",), False),
    ("afp_crecer", "from:info@afpcrecer.com.do subject:cuenta", (".pdf",), False),
)
# spanish-data: end

CUSTOM = """
[[source]]
name = "bank"
query = "from:statements@bank.example"
extensions = [".pdf", ".jpg"]

[[source]]
name = "afp-x"
query = "from:afp@afp.example"
extensions = [".pdf"]
parse = false
"""
# The same file as an install from before the English rename wrote it (`legacy.SOURCES_FILE`),
# with its Spanish table and key names (`legacy.SOURCES_TABLE`, `legacy.SOURCE_KEYS`).
# spanish-data: begin
LEGACY_CUSTOM = """
[[fuente]]
nombre = "bank"
consulta = "from:statements@bank.example"
extensiones = [".pdf", ".jpg"]

[[fuente]]
nombre = "afp-x"
consulta = "from:afp@afp.example"
extensiones = [".pdf"]
interpretar = false
"""
# spanish-data: end
CUSTOM_SOURCES = (
    Source("bank", "from:statements@bank.example", (".pdf", ".jpg")),
    Source("afp-x", "from:afp@afp.example", (".pdf",), interpret=False),
)


def test_defaults_are_the_sources_sync_always_used() -> None:
    statements = tuple(s for s in DEFAULT_SOURCES if not s.alerts)
    assert tuple((s.name, s.query, s.extensions, s.interpret) for s in statements) == BEFORE
    # Live sync adds Popular's purchase alerts, parsed in memory (nothing saved to raw/).
    assert [(s.name, s.extensions) for s in DEFAULT_SOURCES if s.alerts] == [("popular_alerts", ())]
    archive_only = {"afp_reservas", "afp_siembra", "afp_crecer"}  # spanish-data: sender names
    assert frozenset(archive_only) == config.ARCHIVE_ONLY


def test_without_user_file_uses_the_defaults(tmp_path: Path) -> None:
    assert load_sources(tmp_path / "sources.toml") is DEFAULT_SOURCES


def test_the_example_file_is_exactly_the_defaults() -> None:
    assert load_sources(EXAMPLE) == DEFAULT_SOURCES


def test_user_file_replaces_the_defaults(tmp_path: Path) -> None:
    path = tmp_path / "sources.toml"
    path.write_text(CUSTOM)
    loaded = load_sources(path)
    assert loaded == CUSTOM_SOURCES
    assert config.archive_only(loaded) == {"afp-x"}
    assert config.find_source("bank", loaded).query == "from:statements@bank.example"
    with pytest.raises(KeyError):
        config.find_source("popular", loaded)


def test_user_file_path_lives_in_the_data_dir(tmp_path: Path) -> None:
    assert config.Paths(tmp_path).sources == tmp_path / "sources.toml"


def test_legacy_file_is_read_with_its_old_keys_while_there_is_no_new_one(tmp_path: Path) -> None:
    legacy_file = tmp_path / legacy.SOURCES_FILE
    legacy_file.write_text(LEGACY_CUSTOM)
    paths = config.Paths(tmp_path)
    assert paths.sources == legacy_file
    assert load_sources(paths.sources) == CUSTOM_SOURCES
    (tmp_path / "sources.toml").write_text(CUSTOM.replace('"bank"', '"other"'))
    assert paths.sources == tmp_path / "sources.toml"
    assert load_sources(paths.sources)[0].name == "other"


def test_legacy_file_errors_are_still_reported(tmp_path: Path) -> None:
    legacy_file = tmp_path / legacy.SOURCES_FILE
    legacy_file.write_text('[[fuente]]\nnombre = "bank"\nclave = 1\n')  # spanish-data
    with pytest.raises(SourcesError, match="unknown keys"):
        load_sources(legacy_file)


def test_holders_file_falls_back_to_the_legacy_name(tmp_path: Path) -> None:
    paths = config.Paths(tmp_path)
    assert paths.holders == tmp_path / "holders.txt"
    (tmp_path / legacy.HOLDERS_FILE).write_text("Maria Perez Inventada\n")
    assert paths.holders == tmp_path / legacy.HOLDERS_FILE
    (tmp_path / "holders.txt").write_text("Maria Perez Inventada\n")
    assert paths.holders == tmp_path / "holders.txt"


def _entry(**fields: str) -> str:
    base = {
        "name": '"bank"',
        "query": '"from:x@bank.example"',
        "extensions": '[".pdf"]',
    }
    base.update(fields)
    body = "\n".join(f"{key} = {value}" for key, value in base.items() if value != "")
    return f"[[source]]\n{body}\n"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("this is not toml = = ", "could not be read"),
        ("", "there is no"),
        ("source = []", "there is no"),
        ("other = 1\n" + _entry(), "unknown keys"),
        (_entry(name='"../outside"'), "'name'"),
        (_entry(name='"With Spaces"'), "'name'"),
        (_entry(name=""), "'name'"),
        (_entry(name='"bank\\n"'), "'name'"),
        (_entry(name='"imported"'), "reserved"),
        (_entry(name=f'"{legacy.IMPORT_FOLDER}"'), "reserved"),
        (_entry(name=f'"{legacy.IMPORT_SOURCE}"'), "reserved"),
        (_entry(query='"  "'), "'query'"),
        (_entry(query=""), "'query'"),
        (_entry(extensions="[]"), "'extensions'"),
        (_entry(extensions='["pdf"]'), "'extensions'"),
        (_entry(extensions='[".PDF"]'), "'extensions'"),
        (_entry(extensions='[".pdf\\n"]'), "'extensions'"),
        (_entry(extensions='".pdf"'), "'extensions'"),
        (_entry(parse='"no"'), "'parse'"),
        (_entry(key="1"), "unknown keys"),
        (_entry() + _entry(), "repeated"),
    ],
)
def test_invalid_user_file_is_an_error_not_a_silent_fallback(
    tmp_path: Path, text: str, message: str
) -> None:
    path = tmp_path / "sources.toml"
    path.write_text(text)
    with pytest.raises(SourcesError, match=message):
        load_sources(path)


def test_default_archive_only_sources_stay_archived_unless_redefined() -> None:
    bank = Source("bank", "from:x@bank.example", (".pdf",))

    own_afp = Source("afp-x", "from:afp@afp.example", (".pdf",), interpret=False)
    assert archived_names(DEFAULT_SOURCES) == config.ARCHIVE_ONLY
    assert archived_names((bank, own_afp)) == config.ARCHIVE_ONLY | {"afp-x"}
    parsed_afp = Source("afp_crecer", "from:info@afp.example", (".pdf",))
    assert archived_names((bank, parsed_afp)) == {"afp_reservas", "afp_siembra"}  # spanish-data
