"""Synthetic PAC/DHTB builders.  Independent of the library code: they pack
the documented layout directly with struct, so tests check the parser against
the spec rather than against itself.  No real firmware is used anywhere."""

import struct

import pytest

HEADER = 2124
ENTRY = 2580


def u16s(s, n):
    raw = s.encode("utf-16le")
    return raw + b"\0" * (n - len(raw))


def crc16_arc(data, crc=0):
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def make_entry(fid, name, size, offset, typ=1, addrs=(0x80000001,), size_hi=0, off_hi=0):
    e = bytearray(ENTRY)
    struct.pack_into("<I", e, 0, ENTRY)
    e[4:516] = u16s(fid, 512)
    e[516:1028] = u16s(name, 512)
    struct.pack_into("<8I", e, 0x5FC, size_hi, off_hi, size, typ, 1, offset, 0, len(addrs))
    struct.pack_into(f"<{len(addrs)}I", e, 0x61C, *addrs)
    return bytes(e)


def make_pac(files, ops=(), version="BP_R1.0.0", product="TESTCHIP", fw="TEST_FW_1"):
    """files: list of (id, name, bytes). ops: ids of payload-less entries."""
    count = len(files) + len(ops)
    cursor = HEADER + count * ENTRY
    entries, blobs = [], []
    for fid, name, data in files:
        entries.append(make_entry(fid, name, len(data), cursor))
        blobs.append(data)
        cursor += len(data)
    for fid in ops:
        entries.append(make_entry(fid, "", 0, 0, typ=0, addrs=()))
    table = b"".join(entries)
    body = table + b"".join(blobs)
    head = bytearray(HEADER)
    head[0:48] = u16s(version, 48)
    struct.pack_into("<I", head, 0x30, HEADER + len(body))
    head[0x34:0x234] = u16s(product, 512)
    head[0x234:0x434] = u16s(fw, 512)
    struct.pack_into("<II", head, 0x434, count, HEADER)
    struct.pack_into("<I", head, 0x844, 0xFFFAFFFA)
    struct.pack_into("<H", head, 0x84A, crc16_arc(body))
    struct.pack_into("<H", head, 0x848, crc16_arc(bytes(head[:0x848])))
    return bytes(head) + body


def make_dhtb(payload, version=1):
    hdr = bytearray(0x200)
    hdr[:4] = b"DHTB"
    struct.pack_into("<I", hdr, 4, version)
    struct.pack_into("<I", hdr, 0x30, len(payload))
    return bytes(hdr) + payload


SAMPLE = [
    ("FDL", "fdl1.bin", make_dhtb(b"\x01\x02\x03" * 100)),
    ("BOOT1", "boot1.bin", make_dhtb(b"boot-code" * 50)),
    ("KernelImg", "kernel.bin", b"K" * 5000),
    ("WCN", "kernel.bin", b"W" * 777),  # same file name as KernelImg
]


@pytest.fixture
def pac_path(tmp_path):
    p = tmp_path / "sample.pac"
    p.write_bytes(make_pac(SAMPLE, ops=("EraseFS",)))
    return p
