"""Read, extract, repack and compare Unisoc/Spreadtrum ``.pac`` archives.

Layout (little endian), matching the public ``unpac`` tool from
https://github.com/ilyakurdyukov/spreadtrum_flash::

    header, 2124 bytes
      0x000  u16[24]   pac_version   UTF-16LE, NUL terminated
      0x030  u32       pac_size      length of the whole file
      0x034  u16[256]  fw_name       UTF-16LE
      0x234  u16[256]  fw_version    UTF-16LE
      0x434  u32       file_count
      0x438  u32       dir_offset    always 2124 (the table follows the header)
      0x43C  ...       unknown / alias strings (kept verbatim)
      0x844  u32       magic         0xFFFAFFFA
      0x848  u16       head_crc      CRC-16/ARC of header[0:0x848]
      0x84A  u16       data_crc      CRC-16/ARC of file[2124:pac_size]

    file table, file_count entries of 2580 bytes, starting at dir_offset
      0x000  u32       struct_size   2580
      0x004  u16[256]  id            e.g. "FDL", "BOOT1", "KernelImg"
      0x204  u16[256]  name          file name inside the firmware package
      0x5FC  u32       size_high
      0x600  u32       offset_high
      0x604  u32       size
      0x608  u32       type          0 operation, 1 file, 2 xml, 0x101 FDL
      0x60C  u32       flash_use
      0x610  u32       offset        payload offset (low 32 bits)
      0x614  u32       omit_flag
      0x618  u32       addr_num
      0x61C  u32[5]    addr          flash/partition ids
      0x630  u32[249]  unknown

Entries with ``size == 0`` or ``offset == 0`` have no payload (they are
"operations" such as erase steps, or empty partitions).
"""

from __future__ import annotations

import hashlib
import os
import re
import struct
from dataclasses import dataclass, field
from typing import Iterable, Mapping

PAC_MAGIC = 0xFFFAFFFA
HEADER_SIZE = 2124
ENTRY_SIZE = 2580
MAX_FILES = 1 << 10

_OFF_PAC_SIZE = 0x30
_OFF_FILE_COUNT = 0x434
_OFF_DIR_OFFSET = 0x438
_OFF_MAGIC = 0x844
_OFF_HEAD_CRC = 0x848
_OFF_DATA_CRC = 0x84A

_CHUNK = 1 << 20


class PacError(ValueError):
    """The input is not a well-formed PAC archive."""


def _make_crc_table() -> list[int]:
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ (0xA001 if c & 1 else 0)
        table.append(c)
    return table


_CRC_TABLE = _make_crc_table()


def crc16(data: bytes, crc: int = 0) -> int:
    """CRC-16/ARC (reflected, poly 0xA001, init 0), as used by unpac."""
    table = _CRC_TABLE
    for b in data:
        crc = (crc >> 8) ^ table[(crc ^ b) & 0xFF]
    return crc


def _utf16(buf: bytes, off: int, length: int) -> str:
    return buf[off : off + length].decode("utf-16le", errors="replace").split("\0")[0]


@dataclass
class PacEntry:
    """One row of the file table."""

    index: int
    file_id: str
    file_name: str
    size: int
    offset: int
    type: int
    flash_use: int
    omit_flag: int
    addrs: tuple[int, ...]
    raw: bytes = field(repr=False)  # the original 2580 bytes, kept for repacking

    @property
    def has_payload(self) -> bool:
        return self.size > 0 and self.offset > 0

    @classmethod
    def parse(cls, index: int, raw: bytes) -> "PacEntry":
        (struct_size,) = struct.unpack_from("<I", raw, 0)
        if struct_size != ENTRY_SIZE:
            raise PacError(f"entry {index}: unexpected struct size {struct_size}")
        size_hi, off_hi, size, typ, flash_use, off, omit, addr_num = struct.unpack_from(
            "<8I", raw, 0x5FC
        )
        addrs = struct.unpack_from("<5I", raw, 0x61C)[: min(addr_num, 5)]
        return cls(
            index=index,
            file_id=_utf16(raw, 4, 512),
            file_name=_utf16(raw, 0x204, 512),
            size=size_hi << 32 | size,
            offset=off_hi << 32 | off,
            type=typ,
            flash_use=flash_use,
            omit_flag=omit,
            addrs=tuple(addrs),
            raw=bytes(raw),
        )

    def with_payload(self, size: int, offset: int) -> bytes:
        """The raw entry with size/offset fields rewritten."""
        raw = bytearray(self.raw)
        struct.pack_into("<I", raw, 0x5FC, size >> 32)
        struct.pack_into("<I", raw, 0x600, offset >> 32)
        struct.pack_into("<I", raw, 0x604, size & 0xFFFFFFFF)
        struct.pack_into("<I", raw, 0x610, offset & 0xFFFFFFFF)
        return bytes(raw)


class Pac:
    """A parsed PAC archive (the payloads stay on disk)."""

    def __init__(self, path: str | os.PathLike):
        self.path = os.fspath(path)
        self.file_size = os.path.getsize(self.path)
        with open(self.path, "rb") as fh:
            head = fh.read(HEADER_SIZE)
            if len(head) < HEADER_SIZE:
                raise PacError("file shorter than the PAC header")
            (magic,) = struct.unpack_from("<I", head, _OFF_MAGIC)
            if magic != PAC_MAGIC:
                raise PacError(
                    f"bad PAC magic 0x{magic:08x} (expected 0x{PAC_MAGIC:08x})"
                )
            (count,) = struct.unpack_from("<I", head, _OFF_FILE_COUNT)
            (dir_off,) = struct.unpack_from("<I", head, _OFF_DIR_OFFSET)
            if dir_off != HEADER_SIZE:
                raise PacError(f"unexpected directory offset {dir_off}")
            if count >= MAX_FILES:
                raise PacError(f"too many files ({count})")
            table = fh.read(count * ENTRY_SIZE)
            if len(table) < count * ENTRY_SIZE:
                raise PacError("file table truncated")
        self.header_raw = head
        self.entries = [
            PacEntry.parse(i, table[i * ENTRY_SIZE : (i + 1) * ENTRY_SIZE])
            for i in range(count)
        ]
        for e in self.entries:
            if e.has_payload and e.offset + e.size > self.file_size:
                raise PacError(
                    f"entry {e.file_id!r} lies outside the file "
                    f"(offset {e.offset} + size {e.size} > {self.file_size})"
                )

    # -- header fields -------------------------------------------------
    @property
    def version(self) -> str:
        return _utf16(self.header_raw, 0, 48)

    @property
    def pac_size(self) -> int:
        return struct.unpack_from("<I", self.header_raw, _OFF_PAC_SIZE)[0]

    @property
    def product(self) -> str:
        return _utf16(self.header_raw, 0x34, 512)

    @property
    def firmware(self) -> str:
        return _utf16(self.header_raw, 0x234, 512)

    @property
    def head_crc(self) -> int:
        return struct.unpack_from("<H", self.header_raw, _OFF_HEAD_CRC)[0]

    @property
    def data_crc(self) -> int:
        return struct.unpack_from("<H", self.header_raw, _OFF_DATA_CRC)[0]

    def payloads(self) -> list[PacEntry]:
        return [e for e in self.entries if e.has_payload]

    # -- payload access ------------------------------------------------
    def iter_payload(self, entry: PacEntry) -> Iterable[bytes]:
        with open(self.path, "rb") as fh:
            fh.seek(entry.offset)
            remaining = entry.size
            while remaining:
                chunk = fh.read(min(_CHUNK, remaining))
                if not chunk:
                    raise PacError(f"unexpected EOF reading {entry.file_id!r}")
                remaining -= len(chunk)
                yield chunk

    def read_payload(self, entry: PacEntry) -> bytes:
        return b"".join(self.iter_payload(entry))

    def sha256(self, entry: PacEntry) -> str:
        h = hashlib.sha256()
        for chunk in self.iter_payload(entry):
            h.update(chunk)
        return h.hexdigest()

    # -- checks --------------------------------------------------------
    def compute_crcs(self) -> tuple[int, int]:
        """Return (head_crc, data_crc) as recomputed from the file."""
        head = crc16(self.header_raw[:_OFF_HEAD_CRC])
        data = 0
        with open(self.path, "rb") as fh:
            fh.seek(HEADER_SIZE)
            remaining = max(self.pac_size - HEADER_SIZE, 0)
            while remaining:
                chunk = fh.read(min(_CHUNK, remaining))
                if not chunk:
                    break
                data = crc16(chunk, data)
                remaining -= len(chunk)
        return head, data

    # -- extraction ----------------------------------------------------
    def extract(self, dest: str | os.PathLike, only: Iterable[str] = ()) -> list[str]:
        """Write each payload to ``dest/<id>_<name>``; returns the paths.

        Several entries can share a file name (e.g. two different IDs that
        both point at ``EXEC_KERNEL_IMAGE.bin``), so the ID is always part of
        the output name.  Path separators in names are neutralised.
        """
        dest = os.fspath(dest)
        os.makedirs(dest, exist_ok=True)
        only = set(only)
        written = []
        for e in self.payloads():
            if only and e.file_id not in only and e.file_name not in only:
                continue
            out = os.path.join(dest, extracted_name(e))
            with open(out, "wb") as dst:
                for chunk in self.iter_payload(e):
                    dst.write(chunk)
            written.append(out)
        return written


def extracted_name(entry: PacEntry) -> str:
    base = entry.file_name or f"entry{entry.index}"
    name = f"{entry.file_id}_{base}" if entry.file_id else base
    name = re.sub(r"[\\/:\x00-\x1f]", "_", name)
    return name.lstrip(".") or f"entry{entry.index}"


# -- repack ------------------------------------------------------------
def repack(
    src: str | os.PathLike,
    dst: str | os.PathLike,
    replacements: Mapping[str, str | os.PathLike | bytes] | None = None,
) -> Pac:
    """Rewrite ``src`` to ``dst``, optionally replacing payloads by file ID.

    Payloads are laid out back to back in their original order, starting at
    the original first payload offset.  Header, table and unknown fields are
    preserved; sizes, offsets, ``pac_size``, ``head_crc`` and ``data_crc``
    are recomputed.  With no replacements the output is byte-identical to the
    input for archives whose payloads are already contiguous (verified for a
    real firmware, see README); archives with padding between payloads are
    compacted.
    """
    replacements = dict(replacements or {})
    src_pac = Pac(src)
    ids = {e.file_id for e in src_pac.payloads()}
    unknown = sorted(set(replacements) - ids)
    if unknown:
        raise PacError(f"no payload with ID(s): {', '.join(unknown)}")

    order = sorted(src_pac.payloads(), key=lambda e: e.offset)
    if not order:
        raise PacError("archive has no payloads")
    cursor = order[0].offset

    table = bytearray(b"".join(e.raw for e in src_pac.entries))
    sources: list[tuple[PacEntry, bytes | None]] = []
    for e in order:
        rep = replacements.get(e.file_id)
        if rep is None:
            size, data = e.size, None
        else:
            if isinstance(rep, (bytes, bytearray)):
                data = bytes(rep)
            else:
                with open(rep, "rb") as fh:
                    data = fh.read()
            size = len(data)
        table[e.index * ENTRY_SIZE : (e.index + 1) * ENTRY_SIZE] = e.with_payload(
            size, cursor
        )
        sources.append((e, data))
        cursor += size
    total = cursor
    if total > 0xFFFFFFFF:
        raise PacError("pac_size does not fit in 32 bits")

    head = bytearray(src_pac.header_raw)
    struct.pack_into("<I", head, _OFF_PAC_SIZE, total)

    # data_crc covers everything after the header up to pac_size, including
    # any bytes between the table and the first payload.
    data_crc = crc16(bytes(table))
    gap = order[0].offset - HEADER_SIZE - len(table)
    with open(src_pac.path, "rb") as fh:
        gap_bytes = b""
        if gap > 0:
            fh.seek(HEADER_SIZE + len(table))
            gap_bytes = fh.read(gap)
    data_crc = crc16(gap_bytes, data_crc)
    for e, data in sources:
        if data is not None:
            data_crc = crc16(data, data_crc)
        else:
            for chunk in src_pac.iter_payload(e):
                data_crc = crc16(chunk, data_crc)
    struct.pack_into("<H", head, _OFF_DATA_CRC, data_crc)
    struct.pack_into("<H", head, _OFF_HEAD_CRC, 0)
    struct.pack_into("<H", head, _OFF_HEAD_CRC, crc16(bytes(head[:_OFF_HEAD_CRC])))

    tmp = os.fspath(dst)
    with open(tmp, "wb") as out:
        out.write(head)
        out.write(table)
        out.write(gap_bytes)
        for e, data in sources:
            if data is not None:
                out.write(data)
            else:
                for chunk in src_pac.iter_payload(e):
                    out.write(chunk)
    return Pac(dst)


# -- diff --------------------------------------------------------------
@dataclass
class Change:
    file_id: str
    kind: str  # "added", "removed", "size", "content", "meta"
    detail: str = ""


def diff(a: Pac, b: Pac) -> tuple[list[Change], int]:
    """Compare two archives by file ID; returns (changes, identical_count)."""
    ea = {e.file_id: e for e in a.payloads()}
    eb = {e.file_id: e for e in b.payloads()}
    changes: list[Change] = []
    same = 0
    for fid in sorted(set(ea) | set(eb)):
        x, y = ea.get(fid), eb.get(fid)
        if x is None or y is None:
            changes.append(Change(fid, "added" if x is None else "removed"))
        elif x.size != y.size:
            changes.append(Change(fid, "size", f"{x.size} -> {y.size}"))
        else:
            da, db = a.sha256(x), b.sha256(y)
            if da != db:
                changes.append(Change(fid, "content", f"{da[:16]} -> {db[:16]}"))
            elif (x.file_name, x.type, x.addrs) != (y.file_name, y.type, y.addrs):
                changes.append(Change(fid, "meta", "name/type/addr differ"))
            else:
                same += 1
    for label, fa, fb in (
        ("version", a.version, b.version),
        ("product", a.product, b.product),
        ("firmware", a.firmware, b.firmware),
    ):
        if fa != fb:
            changes.append(Change("<header>", "meta", f"{label}: {fa!r} -> {fb!r}"))
    return changes, same
