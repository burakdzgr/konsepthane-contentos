"""Deterministic image dimension extraction (no external dependencies).

Parses only what the container formats guarantee: the PNG IHDR chunk,
the JPEG SOF frame header, and the WebP VP8/VP8L/VP8X chunk headers.
Anything unparseable yields honest (None, None) — dimensions are
metadata, never a gate, and nothing is ever guessed.
"""

import struct


def extract_dimensions(data: bytes, media_type: str) -> tuple[int | None, int | None]:
    try:
        if media_type == "image/png":
            return _png(data)
        if media_type == "image/jpeg":
            return _jpeg(data)
        if media_type == "image/webp":
            return _webp(data)
    except (struct.error, IndexError, ValueError):
        return (None, None)
    return (None, None)


def _png(data: bytes) -> tuple[int | None, int | None]:
    # 8-byte signature, 4-byte length, b"IHDR", then width/height (BE u32).
    if len(data) < 24 or data[12:16] != b"IHDR":
        return (None, None)
    width, height = struct.unpack(">II", data[16:24])
    return _positive(width, height)


def _jpeg(data: bytes) -> tuple[int | None, int | None]:
    # Scan markers for a start-of-frame segment (SOF0..SOF15 except the
    # DHT/DAC/RST family), which carries height then width (BE u16).
    offset = 2
    length = len(data)
    while offset + 9 < length:
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        segment_length = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[offset + 5 : offset + 9])
            return _positive(width, height)
        offset += 2 + segment_length
    return (None, None)


def _webp(data: bytes) -> tuple[int | None, int | None]:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return (None, None)
    chunk = data[12:16]
    if chunk == b"VP8X":
        # 24-bit little-endian canvas size minus one, at offsets 24/27.
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return _positive(width, height)
    if chunk == b"VP8L":
        if data[20] != 0x2F:
            return (None, None)
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return _positive(width, height)
    if chunk == b"VP8 ":
        # Lossy bitstream: frame tag (3 bytes), start code, then 14-bit sizes.
        if data[23:26] != b"\x9d\x01\x2a":
            return (None, None)
        width = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        height = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return _positive(width, height)
    return (None, None)


def _positive(width: int, height: int) -> tuple[int | None, int | None]:
    if width > 0 and height > 0:
        return (width, height)
    return (None, None)
