"""The "DHTB" container found around Unisoc loader/boot/kernel partition images.

Layout observed on the code partitions of a UMS9117 firmware (FDL1, FDL2,
BOOT0, BOOT1, KernelImg, UserImg), little endian::

    0x000  char[4]  magic        "DHTB"
    0x004  u32      version      1
    0x030  u32      payload_len
    0x200  ...      payload      payload_len bytes

Every other header byte (0x08..0x2F, 0x34..0x1FF) is zero in those images, and
``payload_len == file_size - 0x200``.  Other Unisoc generations with secure
boot may store a digest/signature in the header; this module neither
computes nor checks one, and does not preserve unknown header bytes beyond
what :func:`parse` returns.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"DHTB"
HEADER_SIZE = 0x200
_OFF_VERSION = 4
_OFF_LEN = 0x30


class DhtbError(ValueError):
    """The input is not a valid DHTB image."""


@dataclass
class DhtbInfo:
    version: int
    payload_len: int
    file_size: int
    header_clean: bool  # all header bytes outside the known fields are zero

    @property
    def exact(self) -> bool:
        """True if the file is exactly header + payload (no trailing bytes)."""
        return HEADER_SIZE + self.payload_len == self.file_size


def parse(data: bytes) -> DhtbInfo:
    if len(data) < HEADER_SIZE or data[:4] != MAGIC:
        raise DhtbError("not a DHTB image (missing magic)")
    (version,) = struct.unpack_from("<I", data, _OFF_VERSION)
    (plen,) = struct.unpack_from("<I", data, _OFF_LEN)
    if HEADER_SIZE + plen > len(data):
        raise DhtbError(
            f"payload_len {plen} exceeds the file ({len(data) - HEADER_SIZE} bytes of payload)"
        )
    scratch = bytearray(data[:HEADER_SIZE])
    scratch[0:8] = b"\0" * 8
    scratch[_OFF_LEN : _OFF_LEN + 4] = b"\0" * 4
    return DhtbInfo(version, plen, len(data), not any(scratch))


def strip(data: bytes) -> bytes:
    """Return the payload of a DHTB image."""
    info = parse(data)
    return data[HEADER_SIZE : HEADER_SIZE + info.payload_len]


def pack(payload: bytes, version: int = 1, pad_to: int | None = None) -> bytes:
    """Wrap ``payload`` in a DHTB header.

    ``pad_to`` zero-pads the *payload* (and records the padded length) so the
    result keeps a stock image's size.
    """
    if pad_to is not None and pad_to > len(payload):
        payload = payload + b"\0" * (pad_to - len(payload))
    hdr = bytearray(HEADER_SIZE)
    hdr[0:4] = MAGIC
    struct.pack_into("<I", hdr, _OFF_VERSION, version)
    struct.pack_into("<I", hdr, _OFF_LEN, len(payload))
    return bytes(hdr) + payload
