import json
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from finanzas import db
from finanzas.config import Source
from finanzas.extract import MAX_ATTACHMENT_BYTES, extract_source, safe_filename
from finanzas.gmail import AttachmentRef
from tests.fakes import FakeClient, make_message

SOURCE = Source("banco", "from:estados@banco.example", (".pdf", ".jpg"))


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


def _documents(conn) -> list[tuple[str, str]]:
    return [
        (r["filename"], r["status"]) for r in conn.execute("SELECT * FROM documents ORDER BY id")
    ]


def test_saves_wanted_attachments_privately(conn, tmp_path: Path) -> None:
    client = FakeClient(
        make_message("m1", {"estado.pdf": b"%PDF-1", "logo.png": b"png", "resumen.jpg": b"jpg"})
    )
    stats = extract_source(conn, client, SOURCE, tmp_path)
    assert (stats.new_messages, stats.saved_files, stats.duplicates) == (1, 2, 0)
    assert _documents(conn) == [("estado.pdf", "pending"), ("resumen.jpg", "archived")]
    folder = tmp_path / "banco" / "2026-01" / "m1"
    pdf = folder / "estado.pdf"
    assert pdf.read_bytes() == b"%PDF-1"
    assert stat.S_IMODE(pdf.stat().st_mode) == 0o600
    assert not (folder / "logo.png").exists()
    metadata = json.loads((folder / "message.json").read_text())
    assert metadata["subject"] == "Estado de cuenta"


def test_is_idempotent(conn, tmp_path: Path) -> None:
    client = FakeClient(make_message("m1", {"estado.pdf": b"%PDF-1"}))
    extract_source(conn, client, SOURCE, tmp_path)
    second = extract_source(conn, client, SOURCE, tmp_path)
    assert (second.new_messages, second.saved_files) == (0, 0)
    assert client.fetched == ["m1"]
    assert len(_documents(conn)) == 1


def test_marks_identical_files_as_duplicates(conn, tmp_path: Path) -> None:
    client = FakeClient(
        make_message("m1", {"estado.pdf": b"%PDF-same"}),
        make_message("m2", {"copia.pdf": b"%PDF-same"}),
    )
    stats = extract_source(conn, client, SOURCE, tmp_path)
    assert stats.duplicates == 1
    assert _documents(conn) == [("estado.pdf", "pending"), ("copia.pdf", "duplicate")]


def test_records_notices_without_attachments(conn, tmp_path: Path) -> None:
    client = FakeClient(make_message("m1", {}, subject="Ya están disponibles tus estados"))
    stats = extract_source(conn, client, SOURCE, tmp_path)
    assert (stats.new_messages, stats.saved_files) == (1, 0)
    row = conn.execute("SELECT attachments_saved, subject FROM gmail_messages").fetchone()
    assert tuple(row) == (0, "Ya están disponibles tus estados")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("09FD0000_20261026.pdf", "09FD0000_20261026.pdf"),
        ("../../etc/passwd", "passwd"),
        ("estado de cuenta (1).pdf", "estado_de_cuenta_1_.pdf"),
        ("...", "adjunto"),
    ],
)
def test_safe_filename(name: str, expected: str) -> None:
    assert safe_filename(name) == expected


def test_same_named_attachments_are_both_kept(conn, tmp_path: Path) -> None:
    message, payloads = make_message("m1", {"a b.pdf": b"%PDF-uno"})
    twin = AttachmentRef("a_b.pdf", "m1-twin", 9)
    message = replace(message, attachments=(*message.attachments, twin))
    client = FakeClient((message, {**payloads, "m1-twin": b"%PDF-dos"}))
    stats = extract_source(conn, client, SOURCE, tmp_path)
    assert stats.saved_files == 2
    folder = tmp_path / "banco" / "2026-01" / "m1"
    assert (folder / "a_b.pdf").read_bytes() == b"%PDF-uno"
    assert (folder / "1_a_b.pdf").read_bytes() == b"%PDF-dos"


def test_oversized_attachment_is_recorded_but_not_downloaded(conn, tmp_path: Path) -> None:
    message, _ = make_message("m1", {})
    huge = AttachmentRef("enorme.pdf", "m1-huge", MAX_ATTACHMENT_BYTES + 1)
    client = FakeClient((replace(message, attachments=(huge,)), {}))
    stats = extract_source(conn, client, SOURCE, tmp_path)
    assert stats.saved_files == 0
    assert _documents(conn) == [("enorme.pdf", "error")]
    assert not (tmp_path / "banco" / "2026-01" / "m1" / "enorme.pdf").exists()


def test_rejects_message_ids_that_could_escape_the_folder(conn, tmp_path: Path) -> None:
    client = FakeClient(make_message("../fuera", {"estado.pdf": b"%PDF"}))
    with pytest.raises(ValueError, match="ID de mensaje"):
        extract_source(conn, client, SOURCE, tmp_path)
