"""The extension's icon, drawn here (the repository keeps no images): a rounded square in the
app's green with a white "M", as an RGBA PNG of any size."""

from __future__ import annotations

import struct
import zlib

GREEN = (0x1F, 0x6F, 0x5C, 255)
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)
SIZES = (16, 48, 128)
_CORNER = 0.22  # the corner radius, as a share of the side
_TOP, _BOTTOM = 0.28, 0.74  # where the letter starts and ends, as shares of the side
_STROKE = 0.055


def _inside(x: float, y: float, size: int) -> bool:
    radius = size * _CORNER
    cx = min(max(x, radius), size - radius)
    cy = min(max(y, radius), size - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius


def _letter(u: float, v: float) -> bool:
    """Whether the point (as shares of the side) is on the "M": two posts and a V between."""
    if not _TOP <= v <= _BOTTOM:
        return False
    if 0.24 <= u <= 0.34 or 0.66 <= u <= 0.76:
        return True
    depth = (v - _TOP) / 0.30
    if depth > 1:
        return False
    return abs(u - (0.29 + 0.21 * depth)) <= _STROKE or abs(u - (0.71 - 0.21 * depth)) <= _STROKE


def _pixel(x: int, y: int, size: int) -> tuple[int, int, int, int]:
    cx, cy = x + 0.5, y + 0.5
    if not _inside(cx, cy, size):
        return CLEAR
    return WHITE if _letter(cx / size, cy / size) else GREEN


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(size: int) -> bytes:
    rows = b"".join(
        b"\x00" + b"".join(bytes(_pixel(x, y, size)) for x in range(size)) for y in range(size)
    )
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(rows, 9))
        + _chunk(b"IEND", b"")
    )
