"""The backend's Spanish catalog (`michelito.i18n`)."""

from __future__ import annotations

import ast
import re
import string
from pathlib import Path

import pytest

from michelito import i18n
from michelito.i18n import t

SRC = Path(i18n.__file__).parents[1]
_KEY = re.compile(r"[a-z][a-z0-9_]*(\.[a-z0-9_]+)+")


def test_t_formats_the_parameters() -> None:
    expected = "cuentas desconocidas: a, b"  # spanish-ui
    assert t("dossier.unknown_accounts", accounts="a, b") == expected
    assert t("demo.notice").startswith("Demo con datos inventados")  # spanish-ui


def test_an_unknown_key_or_a_missing_parameter_raises() -> None:
    with pytest.raises(KeyError):
        t("no.such.key")
    with pytest.raises(KeyError):
        t("dossier.unknown_accounts")


def test_merge_rejects_a_key_defined_twice() -> None:
    merged = i18n.merge([("es_a", {"x.one": "one"}), ("es_b", {"x.two": "two"})])
    assert dict(merged) == {"x.one": "one", "x.two": "two"}
    with pytest.raises(i18n.DuplicateKey, match="x.one"):
        i18n.merge([("es_a", {"x.one": "one"}), ("es_b", {"x.one": "another"})])
    with pytest.raises(TypeError):
        merged["x.three"] = "three"  # type: ignore[index]


def test_every_catalog_module_is_discovered_with_dotted_english_keys() -> None:
    modules = sorted(p.stem for p in Path(i18n.__file__).parent.glob("es_*.py"))
    assert {"es_demo", "es_dossier"} <= set(modules)
    assert all(_KEY.fullmatch(key) for key in i18n.MESSAGES), "keys are dotted snake_case"
    for text in i18n.MESSAGES.values():
        list(string.Formatter().parse(text))  # every message is a valid format string


def _literal_keys() -> set[str]:
    """The keys passed as a literal to `t(...)` anywhere in the package."""
    found = set()
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "t"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                found.add(node.args[0].value)
    return found


def test_every_literal_key_used_in_the_code_exists() -> None:
    used = _literal_keys()
    assert used and not used - set(i18n.MESSAGES)
