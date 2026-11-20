"""Synthetic statement PDFs, built from the made-up pages of `tests.samples`.

Each word of a sample page is written at its own position in Courier (5 points per character, the
pitch `tests.layout` uses), so `pdf.read_pages` gives back the same words and the parsers read the
PDF exactly like the sample. With `password`, the PDF is encrypted with the standard security
handler (RC4, 128-bit, revision 3), so the hosted upload can be tested with locked files.

    uv run python -m tests.synthetic_pdf --out DIR    # writes the e2e set (see `E2E_SET`)

Nothing here comes from a real statement: only `tests.samples`.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import zlib
from collections.abc import Sequence
from pathlib import Path

from michelito.parsers.common import Page
from tests import samples

FONT_SIZE = 5.0 / 0.6  # Courier is 600/1000 em wide: 5 points per character
PAGE_WIDTH = 612.0
MIN_HEIGHT = 792.0
MARGIN = 40.0
# pdfminer puts a character's box from (baseline + descent) to (baseline + descent + size);
# Courier's descent is 157/1000 em below the baseline.
_DESCENT = 0.157 * FONT_SIZE
_PAD = bytes.fromhex("28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a")
_DOCUMENT_ID = hashlib.md5(b"michelito synthetic statement").digest()
_PERMISSIONS = -4


def _escape(text: str) -> bytes:
    raw = text.encode("cp1252")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _content(page: Page, height: float) -> bytes:
    parts = [f"BT /F1 {FONT_SIZE:.4f} Tf".encode()]
    for line in page:
        for word in line.words:
            baseline = height - MARGIN - word.top - FONT_SIZE + _DESCENT
            x = MARGIN + word.x0
            parts.append(f"1 0 0 1 {x:.3f} {baseline:.3f} Tm (".encode())
            parts[-1] += _escape(word.text) + b") Tj"
    parts.append(b"ET")
    return b"\n".join(parts)


def _rc4(key: bytes, data: bytes) -> bytes:
    box = list(range(256))
    j = 0
    for i in range(256):
        j = (j + box[i] + key[i % len(key)]) % 256
        box[i], box[j] = box[j], box[i]
    out = bytearray()
    i = j = 0
    for byte in data:
        i = (i + 1) % 256
        j = (j + box[i]) % 256
        box[i], box[j] = box[j], box[i]
        out.append(byte ^ box[(box[i] + box[j]) % 256])
    return bytes(out)


def _padded(password: str) -> bytes:
    return (password.encode("latin-1") + _PAD)[:32]


def _owner_entry(owner: str, user: str) -> bytes:
    digest = hashlib.md5(_padded(owner)).digest()
    for _ in range(50):
        digest = hashlib.md5(digest).digest()
    value = _rc4(digest, _padded(user))
    for step in range(1, 20):
        value = _rc4(bytes(b ^ step for b in digest), value)
    return value


def _file_key(user: str, owner_entry: bytes) -> bytes:
    seed = _padded(user) + owner_entry + struct.pack("<i", _PERMISSIONS) + _DOCUMENT_ID
    key = hashlib.md5(seed).digest()
    for _ in range(50):
        key = hashlib.md5(key).digest()
    return key


def _user_entry(key: bytes) -> bytes:
    value = _rc4(key, hashlib.md5(_PAD + _DOCUMENT_ID).digest())
    for step in range(1, 20):
        value = _rc4(bytes(b ^ step for b in key), value)
    return value + bytes(16)


def _object_key(key: bytes, number: int) -> bytes:
    return hashlib.md5(key + struct.pack("<i", number)[:3] + b"\x00\x00").digest()


def build(pages: Sequence[Page], password: str | None = None) -> bytes:
    """A PDF with `pages` (made-up sample pages), encrypted when `password` is given."""
    height = max(
        [MIN_HEIGHT, *(MARGIN * 2 + max((ln.words[0].top for ln in p), default=0) for p in pages)]
    )
    objects: list[bytes] = []
    first_page = 4
    kids = " ".join(f"{first_page + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>"
    )
    streams: dict[int, bytes] = {}
    for index, page in enumerate(pages):
        number = first_page + 2 * index
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH:.0f} {height:.0f}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {number + 1} 0 R >>".encode()
        )
        streams[number + 1] = _content(page, height)
        objects.append(b"")
    encrypt = None
    key = None
    if password is not None:
        owner = _owner_entry(f"owner-{password}", password)
        key = _file_key(password, owner)
        encrypt = (
            f"<< /Filter /Standard /V 2 /R 3 /Length 128 /P {_PERMISSIONS} "
            f"/O <{owner.hex()}> /U <{_user_entry(key).hex()}> >>"
        ).encode()
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        if number in streams:
            data = streams[number]
            if key is not None:
                data = _rc4(_object_key(key, number), data)
            body = f"<< /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    size = len(objects) + 1
    if encrypt is not None:
        offsets.append(len(out))
        out += f"{size} 0 obj\n".encode() + encrypt + b"\nendobj\n"
        size += 1
    xref = len(out)
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    ident = _DOCUMENT_ID.hex()
    trailer = f"<< /Size {size} /Root 1 0 R /ID [<{ident}> <{ident}>]"
    if encrypt is not None:
        trailer += f" /Encrypt {size - 1} 0 R"
    out += f"trailer\n{trailer} >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def bomb(expanded: int = 1536 * 1024 * 1024) -> bytes:
    """A one-page PDF whose content stream is tiny compressed but `expanded` bytes once inflated
    (a decompression bomb: blank space, nothing else)."""
    packer = zlib.compressobj(9)
    chunk = b" " * (16 * 1024 * 1024)
    parts = [packer.compress(chunk) for _ in range(expanded // len(chunk))]
    stream = b"".join(parts) + packer.flush()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
        f"<< /Length {len(stream)} /Filter /FlateDecode >>\nstream\n".encode()
        + stream
        + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


# The password of the locked synthetic statements (made up, like everything here).
E2E_PASSWORD = "made-up-password-123"
E2E_SET: dict[str, tuple[tuple[Page, ...], str | None]] = {
    "popular-card.pdf": (samples.POPULAR_PAGES, None),
    "bhd-card.pdf": (samples.BHD_TC_PAGES, E2E_PASSWORD),
    "bhd-savings.pdf": (samples.BHD_AHORRO_PAGES, None),
    "wrong-total.pdf": ((samples.POPULAR_DOP_WRONG_TOTAL,), None),
    "other-bank.pdf": ((samples.UNKNOWN,), None),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="folder for the synthetic PDFs")
    args = parser.parse_args()
    folder = Path(args.out)
    folder.mkdir(parents=True, exist_ok=True)
    for name, (pages, password) in E2E_SET.items():
        (folder / name).write_bytes(build(pages, password))


if __name__ == "__main__":
    main()
