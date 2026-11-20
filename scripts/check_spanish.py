#!/usr/bin/env python3
"""Fail when Spanish shows up outside the places where it is allowed.

The codebase is English-only. Spanish is allowed only in:

- the Spanish backend and UI catalogs (``src/michelito/i18n/es_*.py``,
  ``frontend/src/i18n/es/``),
- synthetic data that imitates Dominican bank statements (``tests/samples.py``, fixtures written
  by the pre-rename release, and blocks marked in the source, see below),
- the modules that name pre-rename identifiers (``src/michelito/legacy.py`` and
  ``frontend/src/legacy.ts``).

Inside any other file, Spanish data (a bank literal a parser must match, a merchant name, a
synthetic statement line) is allowed only between ``spanish-data: begin`` and
``spanish-data: end`` markers, or on a line that ends with a ``spanish-data`` marker comment.
In test files (``tests/``, ``frontend/e2e/`` and ``frontend/src/**/*.test.ts``) a line may also end
with a ``spanish-ui`` marker: it asserts Spanish text the app shows (output of the catalog) where
going through the catalog is not possible.

The heuristic: a line is Spanish when it has a Spanish-only letter or punctuation mark
(accents, ñ, ¿, ¡) or a word from ``SPANISH_WORDS``, after splitting identifiers on ``_``,
``-`` and camelCase. Words written in ALL CAPS are ignored: bank descriptions look like that.

    uv run python scripts/check_spanish.py            # every tracked file
    uv run python scripts/check_spanish.py FILE...    # only these files

Exits 1 when something is found, printing ``path:line: word``.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Path globs (relative to the repository root) that may contain Spanish, with the reason.
ALLOWED_PATHS: dict[str, str] = {
    "src/michelito/i18n/es_*.py": "Spanish catalog",
    "src/michelito/legacy.py": "pre-rename identifiers, isolated on purpose",
    "frontend/src/legacy.ts": "pre-rename identifiers (old paths, parameters, storage), isolated",
    "frontend/src/legacy.test.ts": "tests of the pre-rename identifiers",
    "tests/samples.py": "synthetic Dominican bank statements",
    "tests/fixtures/schema_v17*": "database written by the pre-rename release",
    "tests/fixtures/schema_v18_shared*": "database written by the schema 18 release (0be7009)",
    "scripts/check_spanish.py": "the Spanish word list of this check",
    "tests/test_check_spanish.py": "examples of what this check flags",
    "LICENSE": "license text",
    "uv.lock": "generated",
    "frontend/package-lock.json": "generated",
    "frontend/src/i18n/es/*": "Spanish UI catalog",
}

BINARY_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2"})

BEGIN = "spanish-data: begin"
END = "spanish-data: end"
LINE_MARK = "spanish-data"
# In tests only: a line that asserts Spanish text the app shows (the catalog's output).
UI_MARK = "spanish-ui"
TEST_PATHS = ("tests/*", "frontend/e2e/*", "frontend/src/*.test.ts")

SPANISH_LETTERS = re.compile(r"[áéíóúüñÁÉÍÓÚÜÑ¿¡]")

# Words that are clearly Spanish and not common in English code or prose. Short or ambiguous
# words (de, del, el, la, es, no, sin, solo, todo, ver, un, real…) are left out on purpose.
SPANISH_WORDS = frozenset(
    """
    ahora ahorro anual aporte aqui archivo autor aviso bitacora borrar buscar cada caja cambio
    carpeta categoria categorias clave cobro comercio comercios como compartido compartidos con
    conteo correo cuando cuenta cuentas datos debe deben desde deshacer despues donde
    entre esta estado estados estas este esto estos falta fecha fuente fuentes fuerte gasto
    gastos guardar hasta hay hogar huella huellas importar ingreso ingresos inversion inversiones
    los las mensual mes meses monto moneda movimiento movimientos nada nuevas nuevo opiniones otra
    otro otros para pero pendiente pendientes por porque presupuesto prueba pruebas puede
    puerto que recurrente recurrentes reserva reservas revisado revisar siempre sobre tambien
    tarjeta tasa tasas tiene todos transaccion transacciones una uno usuario vinculo vinculos
    mismo misma luego antes algo anos dias dia semana primera primero ultimo ultima nueva vieja
    viejo lista hacer hace queda quedan salen lleva sus pago pagos saldo corte banco titular
    titulares pesos dolar dolares ninguno ninguna cual cuales quien segun mientras aunque bien
    mejor peor varias varios mucho muchos poco pocos
    """.split()  # noqa: SIM905
)

_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")
_CAMEL = re.compile(r"[A-ZÁÉÍÓÚÜÑ]?[a-záéíóúüñ]+|[A-ZÁÉÍÓÚÜÑ]+(?![a-záéíóúüñ])")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    word: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.word}"


def allowed(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in ALLOWED_PATHS)


def is_test(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in TEST_PATHS)


def _words(line: str) -> Iterator[str]:
    for token in _WORD.findall(line):
        for part in _CAMEL.findall(token):
            if len(part) > 1 and part.isupper():
                continue  # ALL CAPS: bank-statement style data
            yield part


def spanish_word(line: str) -> str | None:
    """The first Spanish marker in `line`, or None."""
    for word in _words(line):
        if SPANISH_LETTERS.search(word) or word.lower() in SPANISH_WORDS:
            return word
    for char in ("¿", "¡"):
        if char in line:
            return char
    return None


def scan_text(path: str, text: str) -> list[Finding]:
    findings = []
    in_block = False
    for number, line in enumerate(text.splitlines(), 1):
        if BEGIN in line:
            in_block = True
            continue
        if END in line:
            in_block = False
            continue
        if in_block or LINE_MARK in line or (UI_MARK in line and is_test(path)):
            continue
        word = spanish_word(line)
        if word is not None:
            findings.append(Finding(path, number, word))
    return findings


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout
    return [name for name in out.decode().split("\0") if name]


def scan(paths: Iterable[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        rel = (
            Path(path).resolve().relative_to(ROOT).as_posix() if Path(path).is_absolute() else path
        )
        file = ROOT / rel
        if allowed(rel) or file.suffix.lower() in BINARY_SUFFIXES or not file.is_file():
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(scan_text(rel, text))
        # File names are part of the codebase too.
        word = spanish_word(rel.replace("/", " "))
        if word is not None:
            findings.append(Finding(rel, 0, f"file name: {word}"))
    return findings


def main(argv: list[str]) -> int:
    findings = scan(argv or tracked_files())
    for finding in findings:
        print(finding)
    if findings:
        print(f"{len(findings)} Spanish line(s) outside the allowed places.", file=sys.stderr)
        return 1
    print("No Spanish outside the allowed places.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
