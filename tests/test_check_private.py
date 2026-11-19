"""Pruebas de scripts/check_private.py.

Los valores «sospechosos» se arman por partes para que este archivo no los contenga literales
(si no, el propio chequeo del repositorio fallaría por ellos).
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_private", ROOT / "scripts/check_private.py")
assert _spec is not None and _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
sys.modules["check_private"] = check
_spec.loader.exec_module(check)

ACCOUNT = "7319" + "42856"  # 9 dígitos sin forma de inventado
CARD = " ".join(["4111"] + ["1111"] * 3)  # cumple Luhn, como toda tarjeta
EMAIL = "alguien" + "@" + "gmail" + ".com"
HOME = "/" + "home" + "/alguien/finanzas-data"
LAST4 = "58" + "27"
PHONE = "731" + "-" + "4285"
AMEX = "3782 8224" + "63 10005"  # número de prueba de AMEX, cumple Luhn


def kinds(text: str) -> list[str]:
    return [finding.kind for finding in check.scan_text("x.txt", text)]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (f"POPULAR Cuenta de ahorro {ACCOUNT}", "número tipo cuenta"),
        (f"tarjeta {CARD}", "número tipo tarjeta"),
        (f"tarjeta {CARD.replace(' ', '')}", "número tipo tarjeta"),
        (f"EstadoCuenta{ACCOUNT}.pdf", "número tipo cuenta"),
        (f"acct_{ACCOUNT}", "número tipo cuenta"),
        (f"{ACCOUNT}.pdf", "número tipo cuenta"),
        (f"{ACCOUNT[:3]}-{ACCOUNT[3:]}-3", "número tipo cuenta"),
        (f"{ACCOUNT[:3]}-{ACCOUNT[3:]}1-3", "cédula"),
        (f"tel 809-{PHONE}", "teléfono"),
        (f"(829) {PHONE.replace('-', ' ')}", "teléfono"),
        (f"+1 849.{PHONE.replace('-', '.')}", "teléfono"),
        (f"amex {AMEX}", "número tipo tarjeta"),
        (f"tarjeta {CARD.replace(' ', '.')}", "número tipo tarjeta"),
        (f"tarjeta {CARD.replace(' ', '-')}", "número tipo tarjeta"),
        ("VISA ···" + LAST4, "últimos 4 dígitos"),
        ("TRANSF A CUENTA ****" + LAST4, "últimos 4 dígitos"),
        ("TC *" + LAST4, "últimos 4 dígitos"),
        ("Visa …" + LAST4, "últimos 4 dígitos"),
        ("•••• " + LAST4, "últimos 4 dígitos"),
        ("tarjeta terminada en " + LAST4, "últimos 4 dígitos"),
        ("5100 XXXX XXXX " + LAST4, "últimos 4 dígitos"),
        (f"de: {EMAIL}", "correo"),
        ("de: ana" + "@" + "empresa-real.com.do", "correo"),
        (f"ruta {HOME}", "ruta de una carpeta de usuario"),
        ("/" + "root/.ssh", "ruta de una carpeta de usuario"),
        ("C:" + "\\Users\\alguien\\datos", "ruta de una carpeta de usuario"),
        ("~" + "alguien/finanzas-data", "ruta de una carpeta de usuario"),
        # Solo se salta un sha o digest entero, no un número pegado a letras hex.
        (f"ref {ACCOUNT}abc", "número tipo cuenta"),
        ("x" + "ab" * 10 + ACCOUNT + "cd" * 6, "número tipo cuenta"),
    ],
)
def test_finds_what_looks_personal(text: str, kind: str) -> None:
    assert kinds(text) == [kind]


@pytest.mark.parametrize(
    "text",
    [
        "MB a 0000000066 PEDRO INVERSOR FICTICIO",
        "CTA CTE PERSONAL INVENTADA 123456789",
        "AHORRO US$ PERS 987654321",
        "11111111111111111111111 COLMADO INVENTADO",
        "0000000000013 COMISION",
        "AUT PAGO 850000000",
        "09FD0000_20261026.pdf",
        "VISA DEMO ···4242 · MC ···5151 · Ahorro ···0300",
        "total_cents: 127449012,",
        'GROCERIES: "5411 5422 5441 5451 5462 5499 5921",',
        "Número de tarjeta 510041******9999",
        "correo@ejemplo.com · estados@banco.example · x@example.org",
        "from:estados@popularenlinea.com · 123+usuario@users.noreply.github.com",
        "~/finanzas-data o /home/<usuario>",
        "RD$ 75,260 · 1,274,490.12 · 1274490.12",
        "TELFIC RECARGA 8095550000 · 809-555-0000",
        "000-1234567-8 · 2026-01-15 · 127.0.0.1 · v0.162.7",
        "@pytest.fixture · @types/node",
        "D(100000) * 3000",
        "uses: actions/checkout@" + "3d3c42e5aac5ba805825da76410c1812" + "12345678",
        "image: caddy@sha256:" + "003a97808e781aa9f7e75cc2f43d34d" + "4610" + "99031" + "f" * 24,
    ],
)
def test_invented_values_pass(text: str) -> None:
    assert kinds(text) == []


def test_luhn() -> None:
    assert check.luhn_valid(CARD.replace(" ", ""))
    assert not check.luhn_valid(CARD.replace(" ", "")[:-1] + "2")


def test_allowed_files_skip_only_numbers_and_binaries_are_reported(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text(f"hash = {ACCOUNT}\nautor = {EMAIL}\n")
    (tmp_path / "foto.bin").write_bytes(b"\xff\xfe\x00")
    found = check.scan(tmp_path, ["uv.lock", "foto.bin"])
    assert [(f.path, f.kind.split(":")[0]) for f in found] == [
        ("uv.lock", "correo"),
        ("foto.bin", "archivo binario"),
    ]


def _git_repo(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_report_names_the_place_but_never_the_value(tmp_path: Path, capsys) -> None:
    repo = _git_repo(tmp_path / "repo")
    (repo / "nuevo.txt").write_text(f"linea\ncuenta {ACCOUNT} y {EMAIL}\n")
    (repo / ".gitignore").write_text("ignorado.txt\n")
    (repo / "ignorado.txt").write_text(ACCOUNT)
    assert check.main(["check_private.py", str(repo)]) == 1
    output = capsys.readouterr()
    assert "nuevo.txt:2:8: número tipo cuenta" in output.out
    assert "nuevo.txt:2:" in output.out and ": correo" in output.out
    assert "ignorado.txt" not in output.out
    assert ACCOUNT not in output.out + output.err
    assert "alguien" not in output.out + output.err


def test_clean_tree_passes(tmp_path: Path, capsys) -> None:
    repo = _git_repo(tmp_path / "repo")
    (repo / "ok.py").write_text("CUENTA = 'CTA CTE INVENTADA 123456789'\n")
    assert check.main(["check_private.py", str(repo)]) == 0
    assert "Sin datos personales" in capsys.readouterr().out


def test_this_repository_is_clean() -> None:
    files = check.repository_files(ROOT)
    assert [str(f) for f in check.scan(ROOT, files)] == []
