"""The Spanish check: what it flags, what it lets through, and that the repository passes."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "check_spanish.py"
_SPEC = importlib.util.spec_from_file_location("check_spanish", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
cs = importlib.util.module_from_spec(_SPEC)
sys.modules["check_spanish"] = cs
_SPEC.loader.exec_module(cs)


@pytest.mark.parametrize(
    "line",
    [
        "# Suma los gastos del mes",
        "def total_gastos(rows): ...",
        "const montoTotal = 0",
        "raise ValueError('la cuenta no existe')",
        "¿Seguro?",
        "name = 'Categoría'",
    ],
)
def test_flags_spanish_words_identifiers_and_accents(line: str) -> None:
    assert cs.spanish_word(line) is not None


@pytest.mark.parametrize(
    "line",
    [
        "# Sum the month's expenses",
        "def total_expenses(rows): ...",
        "description = 'SUPERMERCADO INVENTADO PEÑA'",
        "locale = 'es-DO'",
        "the solo developer keeps a todo list",
    ],
)
def test_lets_english_and_all_caps_bank_data_through(line: str) -> None:
    assert cs.spanish_word(line) is None


def test_marked_blocks_and_lines_are_allowed() -> None:
    text = "\n".join(
        [
            "OK = 1",
            "# spanish-data: begin",
            "TOTAL = 'Total de gastos'",
            "# spanish-data: end",
            "LABEL = 'saldo al corte'  # spanish-data",
            "after = 'nada que ver'",
        ]
    )
    findings = cs.scan_text("src/michelito/parsers/x.py", text)
    assert [(f.line, f.word) for f in findings] == [(6, "nada")]


def test_ui_marker_only_counts_in_tests() -> None:
    line = "assert detail == 'mes sin datos'  # spanish-ui"
    assert cs.scan_text("tests/test_x.py", line) == []
    assert cs.scan_text("frontend/e2e/board.spec.ts", line) == []
    assert cs.scan_text("frontend/src/lib/summary.test.ts", line) == []
    assert [f.word for f in cs.scan_text("src/michelito/x.py", line)] == ["mes"]
    assert [f.word for f in cs.scan_text("frontend/src/lib/summary.ts", line)] == ["mes"]


def test_allowed_paths() -> None:
    assert cs.allowed("src/michelito/i18n/es_web.py")
    assert cs.allowed("tests/samples.py")
    assert not cs.allowed("src/michelito/web/app.py")
    assert not cs.allowed("tests/test_web_api.py")


def test_frontend_allows_only_the_es_catalog_and_the_legacy_module() -> None:
    assert cs.allowed("frontend/src/i18n/es/summary.ts")
    assert not cs.allowed("frontend/src/i18n/index.ts")
    assert not cs.allowed("frontend/src/lib/summary.ts")
    assert not cs.allowed("frontend/e2e/board.spec.ts")
    frontend = {k for k in cs.ALLOWED_PATHS if k.startswith("frontend/")}
    assert frontend == {
        "frontend/package-lock.json",
        "frontend/src/i18n/es/*",
        "frontend/src/legacy.ts",
        "frontend/src/legacy.test.ts",
    }
