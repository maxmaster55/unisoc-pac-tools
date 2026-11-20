import struct

import pytest

from unisoc_pac_tools import dhtb, elf
from unisoc_pac_tools.cli import main
from conftest import make_dhtb


def test_pack_matches_spec_layout():
    blob = dhtb.pack(b"abc", version=1)
    assert blob == make_dhtb(b"abc")
    assert blob[:4] == b"DHTB" and len(blob) == 0x203


def test_strip_roundtrip():
    payload = bytes(range(256)) * 10
    assert dhtb.strip(dhtb.pack(payload)) == payload
    info = dhtb.parse(dhtb.pack(payload))
    assert info.exact and info.header_clean and info.version == 1


def test_pad_to_records_padded_length():
    blob = dhtb.pack(b"abc", pad_to=100)
    assert len(blob) == 0x200 + 100
    assert dhtb.parse(blob).payload_len == 100
    assert dhtb.strip(blob) == b"abc" + b"\0" * 97


def test_trailing_bytes_flagged_not_stripped():
    blob = dhtb.pack(b"abc") + b"TRAIL"
    info = dhtb.parse(blob)
    assert not info.exact and dhtb.strip(blob) == b"abc"


def test_rejects_garbage():
    with pytest.raises(dhtb.DhtbError):
        dhtb.parse(b"NOPE" + b"\0" * 0x300)
    with pytest.raises(dhtb.DhtbError):
        dhtb.parse(b"DHTB")
    bad = bytearray(dhtb.pack(b"abc"))
    struct.pack_into("<I", bad, 0x30, 1000)
    with pytest.raises(dhtb.DhtbError):
        dhtb.parse(bytes(bad))


def test_cli_roundtrip(tmp_path):
    payload = tmp_path / "p.bin"
    payload.write_bytes(b"xyz" * 100)
    img = tmp_path / "img.bin"
    assert main(["dhtb-pack", str(payload), "-o", str(img)]) == 0
    out = tmp_path / "back.bin"
    assert main(["dhtb-strip", str(img), "-o", str(out)]) == 0
    assert out.read_bytes() == payload.read_bytes()
    assert main(["dhtb-strip", str(payload), "--info"]) == 2


def test_elf_wrap_then_flatten_roundtrip():
    blob = bytes(range(200))
    wrapped = elf.wrap_elf(blob, base=0x80E66000)
    assert wrapped[:4] == b"\x7fELF"
    segs = elf.segments(wrapped)
    assert segs == [(0x80E66000, 200, 0x1000, 200)]
    assert elf.elf_to_bin(wrapped) == blob


def test_elf_thumb_entry_bit():
    wrapped = elf.wrap_elf(b"\0" * 4, base=0x1000, thumb=True)
    (entry,) = struct.unpack_from("<I", wrapped, 24)
    assert entry == 0x1001


def test_elf_rejects_non_elf():
    with pytest.raises(elf.ElfError):
        elf.elf_to_bin(b"not an elf")


def test_usb_module_imports_without_pyusb():
    from unisoc_pac_tools import usb_detect

    assert usb_detect.KNOWN_PIDS[0x4D00] == "download mode"
