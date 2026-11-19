"""Tests for scripts/check_private.py.

The "suspicious" values are built in pieces so this file does not contain them literally
(otherwise the repository's own check would fail on them).
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

ACCOUNT = "7319" + "42856"  # 9 digits without a made-up shape
CARD = " ".join(["4111"] + ["1111"] * 3)  # passes Luhn, like every card
EMAIL = "someone" + "@" + "gmail" + ".com"
HOME = "/" + "home" + "/someone/michelito-data"
LAST4 = "58" + "27"
PHONE = "731" + "-" + "4285"
AMEX = "3782 8224" + "63 10005"  # AMEX test number, passes Luhn


def kinds(text: str) -> list[str]:
    return [finding.kind for finding in check.scan_text("x.txt", text)]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (f"POPULAR savings account {ACCOUNT}", "account-like number"),
        (f"card {CARD}", "card-like number"),
        (f"card {CARD.replace(' ', '')}", "card-like number"),
        (f"Statement{ACCOUNT}.pdf", "account-like number"),
        (f"acct_{ACCOUNT}", "account-like number"),
        (f"{ACCOUNT}.pdf", "account-like number"),
        (f"{ACCOUNT[:3]}-{ACCOUNT[3:]}-3", "account-like number"),
        (f"{ACCOUNT[:3]}-{ACCOUNT[3:]}1-3", "national ID"),
        (f"tel 809-{PHONE}", "phone number"),
        (f"(829) {PHONE.replace('-', ' ')}", "phone number"),
        (f"+1 849.{PHONE.replace('-', '.')}", "phone number"),
        (f"amex {AMEX}", "card-like number"),
        (f"card {CARD.replace(' ', '.')}", "card-like number"),
        (f"card {CARD.replace(' ', '-')}", "card-like number"),
        ("VISA ···" + LAST4, "last 4 digits"),
        ("TRANSFER TO ACCOUNT ****" + LAST4, "last 4 digits"),
        ("CARD *" + LAST4, "last 4 digits"),
        ("Visa …" + LAST4, "last 4 digits"),
        ("•••• " + LAST4, "last 4 digits"),
        ("tarjeta terminada en " + LAST4, "last 4 digits"),  # spanish-data
        ("5100 XXXX XXXX " + LAST4, "last 4 digits"),
        (f"from: {EMAIL}", "email"),
        ("from: ana" + "@" + "real-company.com.do", "email"),
        (f"path {HOME}", "user home folder path"),
        ("/" + "root/.ssh", "user home folder path"),
        ("C:" + "\\Users\\someone\\data", "user home folder path"),
        ("~" + "someone/michelito-data", "user home folder path"),
        # Only a whole sha or digest is skipped, not a number glued to hex letters.
        (f"ref {ACCOUNT}abc", "account-like number"),
        ("x" + "ab" * 10 + ACCOUNT + "cd" * 6, "account-like number"),
    ],
)
def test_finds_what_looks_personal(text: str, kind: str) -> None:
    assert kinds(text) == [kind]


@pytest.mark.parametrize(
    "text",
    [
        "MB to 0000000066 PEDRO FICTIONAL INVESTOR",
        "MADE-UP PERSONAL CHECKING 123456789",
        "SAVINGS US$ PERS 987654321",
        "11111111111111111111111 MADE-UP GROCERY",
        "0000000000013 FEE",
        "AUTO PAY 850000000",
        "09FD0000_20261026.pdf",
        "VISA DEMO ···4242 · MC ···5151 · Savings ···0300",
        "total_cents: 127449012,",
        'GROCERIES: "5411 5422 5441 5451 5462 5499 5921",',
        "Card number 510041******9999",
        "mail@ejemplo.com · statements@bank.example · x@example.org",
        "from:estados@popularenlinea.com · 123+user@users.noreply.github.com",  # spanish-data
        "~/michelito-data or /home/<user>",
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
    (tmp_path / "uv.lock").write_text(f"hash = {ACCOUNT}\nauthor = {EMAIL}\n")
    (tmp_path / "photo.bin").write_bytes(b"\xff\xfe\x00")
    found = check.scan(tmp_path, ["uv.lock", "photo.bin"])
    assert [(f.path, f.kind.split(":")[0]) for f in found] == [
        ("uv.lock", "email"),
        ("photo.bin", "binary file"),
    ]


def _git_repo(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_report_names_the_place_but_never_the_value(tmp_path: Path, capsys) -> None:
    repo = _git_repo(tmp_path / "repo")
    (repo / "new.txt").write_text(f"line\nacct {ACCOUNT} and {EMAIL}\n")
    (repo / ".gitignore").write_text("ignored.txt\n")
    (repo / "ignored.txt").write_text(ACCOUNT)
    assert check.main(["check_private.py", str(repo)]) == 1
    output = capsys.readouterr()
    assert "new.txt:2:6: account-like number" in output.out
    assert "new.txt:2:" in output.out and ": email" in output.out
    assert "ignored.txt" not in output.out
    assert ACCOUNT not in output.out + output.err
    assert "someone" not in output.out + output.err


def test_clean_tree_passes(tmp_path: Path, capsys) -> None:
    repo = _git_repo(tmp_path / "repo")
    (repo / "ok.py").write_text("ACCOUNT = 'MADE-UP CHECKING 123456789'\n")
    assert check.main(["check_private.py", str(repo)]) == 0
    assert "No personal data" in capsys.readouterr().out


def test_this_repository_is_clean() -> None:
    files = check.repository_files(ROOT)
    assert [str(f) for f in check.scan(ROOT, files)] == []
