import struct

import pytest

from unisoc_pac_tools import pac
from unisoc_pac_tools.cli import main
from conftest import SAMPLE, make_pac


def test_parse_header_and_entries(pac_path):
    p = pac.Pac(pac_path)
    assert (p.version, p.product, p.firmware) == ("BP_R1.0.0", "TESTCHIP", "TEST_FW_1")
    assert len(p.entries) == 5 and len(p.payloads()) == 4
    assert p.pac_size == p.file_size
    k = next(e for e in p.entries if e.file_id == "KernelImg")
    assert k.size == 5000 and k.addrs == (0x80000001,)
    assert p.read_payload(k) == b"K" * 5000


def test_crcs_match(pac_path):
    p = pac.Pac(pac_path)
    assert p.compute_crcs() == (p.head_crc, p.data_crc)
    assert main(["check", str(pac_path)]) == 0


def test_check_detects_corruption(pac_path):
    raw = bytearray(pac_path.read_bytes())
    raw[-1] ^= 0xFF
    pac_path.write_bytes(raw)
    assert main(["check", str(pac_path)]) == 1


def test_bad_magic(tmp_path):
    raw = bytearray(make_pac(SAMPLE))
    raw[0x844] = 0
    f = tmp_path / "bad.pac"
    f.write_bytes(raw)
    with pytest.raises(pac.PacError):
        pac.Pac(f)


def test_truncated_payload_rejected(tmp_path, pac_path):
    f = tmp_path / "cut.pac"
    f.write_bytes(pac_path.read_bytes()[:-100])
    with pytest.raises(pac.PacError):
        pac.Pac(f)


def test_extract_names_do_not_collide(tmp_path, pac_path):
    out = tmp_path / "out"
    paths = pac.Pac(pac_path).extract(out)
    names = sorted(p.rsplit("/", 1)[-1] for p in paths)
    assert names == ["BOOT1_boot1.bin", "FDL_fdl1.bin", "KernelImg_kernel.bin", "WCN_kernel.bin"]
    assert (out / "WCN_kernel.bin").read_bytes() == b"W" * 777
    assert not any(n.startswith("EraseFS") for n in names)


def test_extract_neutralises_path_separators(tmp_path):
    f = tmp_path / "evil.pac"
    f.write_bytes(make_pac([("X", "../../etc/passwd", b"data")]))
    out = tmp_path / "out"
    pac.Pac(f).extract(out)
    assert [p.name for p in out.iterdir()] == ["X_.._.._etc_passwd"]
    assert not (tmp_path / "etc").exists()


def test_extract_only(tmp_path, pac_path):
    paths = pac.Pac(pac_path).extract(tmp_path / "o", only=["BOOT1"])
    assert len(paths) == 1


def test_repack_without_changes_is_byte_identical(tmp_path, pac_path):
    out = tmp_path / "rt.pac"
    pac.repack(pac_path, out)
    assert out.read_bytes() == pac_path.read_bytes()


def test_repack_replace_updates_sizes_and_crcs(tmp_path, pac_path):
    new = tmp_path / "k.bin"
    new.write_bytes(b"N" * 12345)
    out = tmp_path / "new.pac"
    result = pac.repack(pac_path, out, {"KernelImg": new})
    assert result.compute_crcs() == (result.head_crc, result.data_crc)
    assert result.pac_size == result.file_size
    by = {e.file_id: e for e in result.payloads()}
    assert result.read_payload(by["KernelImg"]) == b"N" * 12345
    assert result.read_payload(by["WCN"]) == b"W" * 777  # shifted but intact
    changes, same = pac.diff(pac.Pac(pac_path), result)
    assert [(c.file_id, c.kind) for c in changes] == [("KernelImg", "size")] and same == 3


def test_repack_unknown_id(tmp_path, pac_path):
    with pytest.raises(pac.PacError):
        pac.repack(pac_path, tmp_path / "x.pac", {"Nope": b"x"})


def test_repack_cli_bad_spec(tmp_path, pac_path):
    assert main(["repack", str(pac_path), str(tmp_path / "o.pac"), "--replace", "bad"]) == 2


def test_diff_same_size_content_change(tmp_path, pac_path):
    other = tmp_path / "o.pac"
    pac.repack(pac_path, other, {"KernelImg": b"P" * 5000})
    changes, same = pac.diff(pac.Pac(pac_path), pac.Pac(other))
    assert [(c.file_id, c.kind) for c in changes] == [("KernelImg", "content")]
    assert same == 3
    assert main(["diff", str(pac_path), str(other)]) == 1
    assert main(["diff", str(pac_path), str(pac_path)]) == 0


def test_diff_added_removed(tmp_path, pac_path):
    f = tmp_path / "s.pac"
    f.write_bytes(make_pac(SAMPLE[:2] + [("Extra", "e.bin", b"e")]))
    changes, _ = pac.diff(pac.Pac(pac_path), pac.Pac(f))
    kinds = {(c.file_id, c.kind) for c in changes}
    assert {("Extra", "added"), ("KernelImg", "removed"), ("WCN", "removed")} <= kinds


def test_64bit_offset_and_size_fields():
    raw = pac.PacEntry.parse(0, __import__("conftest").make_entry(
        "BIG", "big.bin", 5, 7, size_hi=1, off_hi=2))
    assert raw.size == (1 << 32) + 5 and raw.offset == (2 << 32) + 7
    packed = raw.with_payload((3 << 32) + 1, (4 << 32) + 2)
    again = pac.PacEntry.parse(0, packed)
    assert (again.size, again.offset) == ((3 << 32) + 1, (4 << 32) + 2)


def test_crc16_known_value():
    assert pac.crc16(b"123456789") == 0xBB3D  # CRC-16/ARC check value


def test_cli_list_and_extract(tmp_path, pac_path, capsys):
    assert main(["list", str(pac_path)]) == 0
    assert "KernelImg" in capsys.readouterr().out
    assert main(["extract", str(pac_path), str(tmp_path / "x")]) == 0
    assert main(["list", str(tmp_path / "missing.pac")]) == 2
