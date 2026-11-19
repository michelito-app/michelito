from pathlib import Path

import pytest

from finanzas import config
from finanzas.config import DEFAULT_SOURCES, Source
from finanzas.sources import SourcesError, archived_names, load_sources

EXAMPLE = Path(__file__).resolve().parent.parent / "fuentes.ejemplo.toml"

# Las fuentes tal como estaban fijas en config.py antes de poder configurarlas: sin
# fuentes.toml, `sync` debe seguir pidiendo exactamente esto.
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

CUSTOM = """
[[fuente]]
nombre = "banco"
consulta = "from:estados@banco.example"
extensiones = [".pdf", ".jpg"]

[[fuente]]
nombre = "afp-x"
consulta = "from:afp@afp.example"
extensiones = [".pdf"]
interpretar = false
"""


def test_defaults_are_the_sources_sync_always_used() -> None:
    assert tuple((s.name, s.query, s.extensions, s.interpret) for s in DEFAULT_SOURCES) == BEFORE
    assert frozenset({"afp_reservas", "afp_siembra", "afp_crecer"}) == config.ARCHIVE_ONLY


def test_without_user_file_uses_the_defaults(tmp_path: Path) -> None:
    assert load_sources(tmp_path / "fuentes.toml") is DEFAULT_SOURCES


def test_the_example_file_is_exactly_the_defaults() -> None:
    assert load_sources(EXAMPLE) == DEFAULT_SOURCES


def test_user_file_replaces_the_defaults(tmp_path: Path) -> None:
    path = tmp_path / "fuentes.toml"
    path.write_text(CUSTOM)
    loaded = load_sources(path)
    assert loaded == (
        Source("banco", "from:estados@banco.example", (".pdf", ".jpg")),
        Source("afp-x", "from:afp@afp.example", (".pdf",), interpret=False),
    )
    assert config.archive_only(loaded) == {"afp-x"}
    assert config.find_source("banco", loaded).query == "from:estados@banco.example"
    with pytest.raises(KeyError):
        config.find_source("popular", loaded)


def test_user_file_path_lives_in_the_data_dir(tmp_path: Path) -> None:
    assert config.Paths(tmp_path).sources == tmp_path / "fuentes.toml"


def _entry(**fields: str) -> str:
    base = {
        "nombre": '"banco"',
        "consulta": '"from:x@banco.example"',
        "extensiones": '[".pdf"]',
    }
    base.update(fields)
    body = "\n".join(f"{key} = {value}" for key, value in base.items() if value != "")
    return f"[[fuente]]\n{body}\n"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("esto no es toml = = ", "no se pudo leer"),
        ("", "no hay ninguna"),
        ("fuente = []", "no hay ninguna"),
        ("otra = 1\n" + _entry(), "claves desconocidas"),
        (_entry(nombre='"../fuera"'), "nombre"),
        (_entry(nombre='"Con Espacios"'), "nombre"),
        (_entry(nombre=""), "nombre"),
        (_entry(nombre='"banco\\n"'), "nombre"),
        (_entry(nombre='"importados"'), "reservado"),
        (_entry(nombre='"importado"'), "reservado"),
        (_entry(consulta='"  "'), "consulta"),
        (_entry(consulta=""), "consulta"),
        (_entry(extensiones="[]"), "extensiones"),
        (_entry(extensiones='["pdf"]'), "extensiones"),
        (_entry(extensiones='[".PDF"]'), "extensiones"),
        (_entry(extensiones='[".pdf\\n"]'), "extensiones"),
        (_entry(extensiones='".pdf"'), "extensiones"),
        (_entry(interpretar='"no"'), "interpretar"),
        (_entry(clave="1"), "claves desconocidas"),
        (_entry() + _entry(), "repetidos"),
    ],
)
def test_invalid_user_file_is_an_error_not_a_silent_fallback(
    tmp_path: Path, text: str, message: str
) -> None:
    path = tmp_path / "fuentes.toml"
    path.write_text(text)
    with pytest.raises(SourcesError, match=message):
        load_sources(path)


def test_default_archive_only_sources_stay_archived_unless_redefined() -> None:
    bank = Source("banco", "from:x@banco.example", (".pdf",))
    own_afp = Source("afp-x", "from:afp@afp.example", (".pdf",), interpret=False)
    assert archived_names(DEFAULT_SOURCES) == config.ARCHIVE_ONLY
    assert archived_names((bank, own_afp)) == config.ARCHIVE_ONLY | {"afp-x"}
    parsed_afp = Source("afp_crecer", "from:info@afp.example", (".pdf",))
    assert archived_names((bank, parsed_afp)) == {"afp_reservas", "afp_siembra"}
