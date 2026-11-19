"""Falla si el árbol del repositorio tiene algo con forma de dato personal.

Uso: `uv run python scripts/check_private.py [RAÍZ]` (por omisión, la raíz de este repositorio).
Revisa los archivos que git incluiría (los versionados y los nuevos no ignorados) y busca:

- números de tarjeta, cuenta, cédula o teléfono: 9 dígitos o más, seguidos o en grupos unidos
  por «-» o «.» (cuentas `XXX-XXXXXX-X`, cédulas `XXX-XXXXXXX-X`, tarjetas con puntos), aunque
  estén pegados a letras (`EstadoCuenta<número>.pdf`); tarjetas impresas en grupos con
  espacios (4-4-4-4, AMEX 4-6-5) si cumplen Luhn; y teléfonos dominicanos (809/829/849) en
  cualquier formato. Se salvan los de forma obviamente inventada (`looks_invented`);
- últimos 4 dígitos de una tarjeta o cuenta («···NNNN», «*NNNN», «XXXX NNNN», «…NNNN»,
  «•••• NNNN», «terminada en NNNN») que no estén en `INVENTED_LAST4`;
- correos de cualquier dominio que no esté en `ALLOWED_EMAIL_DOMAINS`;
- rutas de una carpeta de usuario: la de Linux y macOS (`/home/<usuario>`, `/Users/<usuario>`),
  la de root, la de Windows (bajo `C:` y `Users`) y `~usuario` seguido de una barra.

No detecta nombres de personas, comercios ni montos: eso sigue siendo revisión a mano.

Las excepciones son explícitas y con motivo: `ALLOWED_FILES` (solo se salta la búsqueda de
números; rutas y correos se revisan igual), `ALLOWED_NUMBERS`, `INVENTED_LAST4` y
`ALLOWED_EMAIL_DOMAINS`. Antes de sumar una, confirma que el valor es inventado; si es real,
cámbialo por uno inventado. El informe nunca imprime el valor encontrado (los registros de CI
son públicos): solo archivo, línea, columna y tipo. Termina con 1 si encontró algo.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# Archivos donde no se buscan números (sí rutas y correos), con el motivo.
ALLOWED_FILES: dict[str, str] = {
    "uv.lock": "sumas de verificación y tamaños de paquetes de PyPI",
    "frontend/package-lock.json": "sumas de verificación de paquetes de npm",
    "LICENSE": "texto oficial de la AGPL-3.0",
}

# Números largos que no son de nadie, con el motivo.
ALLOWED_NUMBERS: dict[str, str] = {
    "1792005355": "marca de tiempo Unix de un correo de prueba (tests/test_gmail.py)",
    "1792005355000": "la misma marca de tiempo en milisegundos (tests/test_gmail.py)",
    "0099887766": "cuenta propia inventada en titulares.txt (tests/test_transfers.py)",
    "0088001234568": "cuenta LBTR inventada (tests/test_transfers.py)",
    "880012345670": "fragmento de cuenta inventada (tests/test_transfers.py)",
    "0007001234567": "cuenta inventada (tests/test_transfers.py)",
    "2026012345": "referencia de nómina inventada (tests/test_investments.py)",
    "00000000667": "referencia inventada (tests/test_investments.py)",
    "0088001234567": "cuenta LBTR inventada (tests/test_categories.py)",
    "0088009999999": "cuenta LBTR inventada (tests/test_categories.py)",
    "88001234567": "cuenta LBTR inventada (tests/test_categories.py)",
    "7001234567": "referencia inventada (tests/test_categories.py)",
    "0012345678901": "boleto aéreo inventado (tests/test_categories.py)",
    "100200300": "cuenta de ahorro inventada (pruebas del frontend)",
    "400500600": "cuenta corriente inventada (pruebas del frontend)",
    "555666777": "cuenta digital inventada (tests/samples.py)",
}

# Últimos 4 dígitos inventados que usan las pruebas y los ejemplos.
INVENTED_LAST4: frozenset[str] = frozenset(
    {"0000", "0300", "0600", "1111", "1234", "4242", "4567", "5151", "7770", "9991", "9999"}
)

# Dominios de correo que pueden aparecer: reservados para ejemplos, la dirección privada de
# GitHub, los remitentes públicos de los bancos y AFP (config.DEFAULT_SOURCES) y los de la
# licencia. Un subdominio de uno de estos también vale.
ALLOWED_EMAIL_DOMAINS: frozenset[str] = frozenset(
    {
        "example.com",
        "example.org",
        "example.net",
        "example",  # TLD reservado: banco.example
        "ejemplo.com",  # marcador de los estados sintéticos (tests/samples.py)
        "users.noreply.github.com",
        "popularenlinea.com",
        "bhd.com.do",
        "afpreservas.com.do",
        "afpsiembra.com",
        "afpcrecer.com.do",
        "gnu.org",
        "fsf.org",
    }
)

# 9 dígitos o más, seguidos o en grupos unidos por «-» o «.»; solo cuenta el límite con otro
# dígito, así que `EstadoCuenta<número>.pdf` o `acct_<número>` también se ven.
_JOINED = re.compile(r"(?<![\d.-])\d+(?:[.-]\d+)*(?![\d]|[.-]\d)")
# Tarjetas impresas con espacios: 4-4-4-4 y AMEX 4-6-5 (se confirman con Luhn).
_SPACED_CARD = re.compile(r"(?<!\d)(?<!\d )(?:\d{4}(?: \d{4}){3}|\d{4} \d{6} \d{5})(?! ?\d)")
_DR_PHONE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?(?:809|829|849)\)?[ .-]?(\d{3})[ .-]?\d{4}(?!\d)")
_FICTION_PHONE = re.compile(r"1?(?:809|829|849)555\d{4}")  # 809-555-0000 y parecidos
_ID_CARD = re.compile(r"(?<!\d)\d{3}-\d{7}-\d(?!\d)")  # cédula
_DECIMAL = re.compile(r"\d+\.\d{2}")  # un monto con centavos no es una cuenta
# Un sha de commit (40 hex) o un digest sha256 (64 hex) en minúsculas: las acciones de GitHub y
# las imágenes de Docker van fijadas así, y sus dígitos seguidos no son de nadie.
_HEX_DIGEST = re.compile(r"(?<![0-9A-Za-z])(?:[0-9a-f]{64}|[0-9a-f]{40})(?![0-9A-Za-z])")
_MIN_DIGITS = 9
# Un monto en centavos (`total_cents: 127449012`) no es una cuenta.
_CENTS_BEFORE = re.compile(r"cents[\"']?\s*[:=]\s*$")
_LAST4 = re.compile(
    r"(?:···|…|•+ ?|\*+|[xX]{4}[ -]?|termina(?:da|do)? en )(\d{4})(?!\d)", re.IGNORECASE
)
_EMAIL = re.compile(r"[\w.+-]+@((?:[\w-]+\.)+[a-z]{2,}|[\w-]+\.example)\b", re.IGNORECASE)
_HOME = re.compile(
    r"/(?:home|Users)/(?!<)[A-Za-z0-9._-]+|/(?:root)/|[A-Za-z]:\\+(?:Users)\\+"
    r"|(?<![\w/])~[A-Za-z][\w.-]*/"
)
_ASCENDING = "01234567890123456789"
_DESCENDING = _ASCENDING[::-1]
_DATE = re.compile(r"^(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])$")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    column: int
    kind: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.column}: {self.kind}"


def looks_invented(digits: str) -> bool:
    """¿Tiene una forma que nadie usaría como número real?

    Un solo dígito repetido, una escalera (123456789, 987654321), una fecha AAAAMMDD, o un
    número que, sin sus ceros, tiene 2 dígitos o menos, es un dígito repetido o una escalera
    (0000000066, 0000000000013, 1200000)."""
    if digits in ALLOWED_NUMBERS or _DATE.match(digits):
        return True
    if len(digits.replace("0", "")) <= 2:
        return True
    for candidate in (digits, digits.replace("0", "")):
        if len(set(candidate)) == 1:
            return True
        if candidate in _ASCENDING or candidate in _DESCENDING:
            return True
    return False


def luhn_valid(digits: str) -> bool:
    """La suma de control de los números de tarjeta (todas la cumplen)."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char) * (2 if index % 2 else 1)
        total += value - 9 if value > 9 else value
    return total % 10 == 0


def _kind(digits: str) -> str:
    return "número tipo tarjeta" if 13 <= len(digits) <= 19 else "número tipo cuenta"


def _numbers(line: str) -> Iterator[tuple[int, int, str]]:
    """(inicio, fin, tipo) de cada número sospechoso de la línea."""
    for match in _DR_PHONE.finditer(line):
        if match.group(1) != "555":  # 555: el intercambio de los teléfonos de ficción
            yield match.start(), match.end(), "teléfono"
    for match in _ID_CARD.finditer(line):
        if not looks_invented(match.group().replace("-", "")):
            yield match.start(), match.end(), "cédula"
    for match in _SPACED_CARD.finditer(line):
        digits = match.group().replace(" ", "")
        if luhn_valid(digits) and not looks_invented(digits):
            yield match.start(), match.end(), "número tipo tarjeta"
    digests = [m.span() for m in _HEX_DIGEST.finditer(line)]
    for match in _JOINED.finditer(line):
        if any(a <= match.start() and match.end() <= b for a, b in digests):
            continue
        text = match.group()
        digits = re.sub(r"\D", "", text)
        if len(digits) < _MIN_DIGITS or _DECIMAL.fullmatch(text):
            continue
        if looks_invented(digits) or _CENTS_BEFORE.search(line[: match.start()]):
            continue
        if _FICTION_PHONE.fullmatch(digits):
            continue
        yield match.start(), match.end(), _kind(digits)


def _email_allowed(domain: str) -> bool:
    domain = domain.lower()
    return any(domain == d or domain.endswith("." + d) for d in ALLOWED_EMAIL_DOMAINS)


def scan_text(path: str, text: str, *, numbers: bool = True) -> Iterator[Finding]:
    for number, line in enumerate(text.splitlines(), start=1):
        if numbers:
            seen: list[tuple[int, int]] = []
            for start, end, kind in _numbers(line):
                if any(start < b and a < end for a, b in seen):
                    continue  # ya informado por un patrón más preciso
                seen.append((start, end))
                yield Finding(path, number, start + 1, kind)
            for match in _LAST4.finditer(line):
                if match.group(1) not in INVENTED_LAST4:
                    yield Finding(path, number, match.start() + 1, "últimos 4 dígitos")
        for match in _EMAIL.finditer(line):
            if not _email_allowed(match.group(1)):
                yield Finding(path, number, match.start() + 1, "correo")
        for match in _HOME.finditer(line):
            yield Finding(path, number, match.start() + 1, "ruta de una carpeta de usuario")


def repository_files(root: Path) -> list[str]:
    """Lo que git publicaría: lo versionado y lo nuevo que no está ignorado."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    ).stdout.decode()
    return sorted({name for name in listed.split("\0") if name})


def scan(root: Path, files: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for name in files:
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(Finding(name, 0, 0, "archivo binario: revísalo a mano o quítalo"))
            continue
        findings.extend(scan_text(name, text, numbers=name not in ALLOWED_FILES))
    return findings


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent
    files = repository_files(root)
    findings = scan(root, files)
    for finding in findings:
        print(finding)
    if findings:
        print(
            f"\n{len(findings)} posibles datos personales. Cámbialos por inventados o, si ya lo "
            "son, súmalos a la lista de permitidos de scripts/check_private.py con su motivo.",
            file=sys.stderr,
        )
        return 1
    print(f"Sin datos personales a la vista ({len(files)} archivos).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
