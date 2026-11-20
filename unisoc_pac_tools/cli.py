"""Command line interface: ``upt <command>``."""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__, dhtb, elf, pac


def _int(v: str) -> int:
    return int(v, 0)


def _print_header(p: pac.Pac) -> None:
    print(f"PAC      : {os.path.basename(p.path)}  ({p.file_size} bytes)")
    print(f"  version   : {p.version}")
    print(f"  product   : {p.product}")
    print(f"  firmware  : {p.firmware}")
    print(f"  pac_size  : {p.pac_size}")
    print(f"  entries   : {len(p.entries)} ({len(p.payloads())} with payload)")


def _print_entries(p: pac.Pac) -> None:
    for e in p.payloads():
        print(
            f"  [{e.file_id:<12}] {e.file_name:<28} size={e.size:>10} "
            f"off=0x{e.offset:08x} type=0x{e.type:x}"
            + (f" addr=0x{e.addrs[0]:x}" if e.addrs else "")
        )


def cmd_list(a) -> int:
    p = pac.Pac(a.pac)
    _print_header(p)
    _print_entries(p)
    return 0


def cmd_extract(a) -> int:
    p = pac.Pac(a.pac)
    _print_header(p)
    written = p.extract(a.outdir, only=a.only)
    for w in written:
        print(f"  {os.path.basename(w)}  ({os.path.getsize(w)} bytes)")
    print(f"extracted {len(written)} file(s) to {a.outdir}")
    return 0


def cmd_check(a) -> int:
    p = pac.Pac(a.pac)
    head, data = p.compute_crcs()
    ok = head == p.head_crc and data == p.data_crc
    print(f"head_crc: stored 0x{p.head_crc:04x} computed 0x{head:04x}")
    print(f"data_crc: stored 0x{p.data_crc:04x} computed 0x{data:04x}")
    if p.pac_size != p.file_size:
        print(f"pac_size {p.pac_size} != file size {p.file_size}")
        ok = False
    print("OK" if ok else "MISMATCH")
    return 0 if ok else 1


def cmd_repack(a) -> int:
    reps = {}
    for spec in a.replace:
        fid, sep, path = spec.partition("=")
        if not sep or not os.path.isfile(path):
            print(f"error: --replace expects FileID=existing_file, got {spec!r}", file=sys.stderr)
            return 2
        reps[fid] = path
    out = pac.repack(a.original, a.output, reps)
    print(f"wrote {a.output} ({out.file_size} bytes)")
    for fid, path in sorted(reps.items()):
        print(f"  replaced {fid} <- {path}")
    return 0


def cmd_diff(a) -> int:
    pa, pb = pac.Pac(a.a), pac.Pac(a.b)
    changes, same = pac.diff(pa, pb)
    print(f"A: {os.path.basename(pa.path)}  {pa.file_size} bytes")
    print(f"B: {os.path.basename(pb.path)}  {pb.file_size} bytes")
    print(f"identical payloads: {same}")
    print(f"differences       : {len(changes)}")
    for c in changes:
        print(f"  {c.file_id:<14} {c.kind:<8} {c.detail}")
    return 1 if changes else 0


def cmd_dhtb_strip(a) -> int:
    with open(a.image, "rb") as fh:
        data = fh.read()
    info = dhtb.parse(data)
    print(f"{os.path.basename(a.image)}")
    print(f"  version        : {info.version}")
    print(f"  payload length : {info.payload_len} (0x{info.payload_len:X})")
    print(f"  file size      : {info.file_size} ({'exact' if info.exact else 'trailing bytes'})")
    print(f"  header clean   : {info.header_clean}")
    if a.info:
        return 0
    out = a.out or os.path.splitext(a.image)[0] + ".payload.bin"
    with open(out, "wb") as fh:
        fh.write(dhtb.strip(data))
    print(f"  -> wrote {out}")
    return 0


def cmd_dhtb_pack(a) -> int:
    with open(a.payload, "rb") as fh:
        payload = fh.read()
    blob = dhtb.pack(payload, a.version, a.pad_to)
    with open(a.out, "wb") as fh:
        fh.write(blob)
    print(f"{a.out}: {len(blob)} bytes, payload_len={len(blob) - dhtb.HEADER_SIZE}")
    return 0


def cmd_elf_to_bin(a) -> int:
    with open(a.elf, "rb") as fh:
        data = fh.read()
    blob = elf.elf_to_bin(data)
    with open(a.out, "wb") as fh:
        fh.write(blob)
    print(f"{a.out}: {len(blob)} bytes")
    return 0


def cmd_elf_wrap(a) -> int:
    with open(a.raw, "rb") as fh:
        payload = fh.read()
    with open(a.out, "wb") as fh:
        fh.write(elf.wrap_elf(payload, a.base, a.thumb))
    print(f"{a.out}: ELF32 ARM base=0x{a.base:X} payload={len(payload)} bytes")
    return 0


def cmd_usb(a) -> int:
    from . import usb_detect

    try:
        if a.wait:
            ok = usb_detect.wait_for_download_mode(a.timeout)
            print("download mode (1782:4d00) detected" if ok else "timed out")
            return 0 if ok else 1
        devs = usb_detect.list_unisoc_devices()
    except ImportError:
        print("error: this command needs pyusb: pip install 'unisoc-pac-tools[usb]'", file=sys.stderr)
        return 2
    for d in devs:
        print(f"  {d.vid:04x}:{d.pid:04x}  {d.description}  {d.product}")
    if not devs:
        print("no Unisoc (1782:*) device found")
    return 0 if devs else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="upt", description="Unisoc PAC / DHTB tools")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="show header and file table")
    p.add_argument("pac")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("extract", help="extract payloads as <ID>_<name>")
    p.add_argument("pac")
    p.add_argument("outdir")
    p.add_argument("only", nargs="*", help="only these IDs/names")
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("check", help="verify header and data CRC-16")
    p.add_argument("pac")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("repack", help="rewrite a PAC, optionally replacing payloads")
    p.add_argument("original")
    p.add_argument("output")
    p.add_argument("--replace", action="append", default=[], metavar="ID=FILE")
    p.set_defaults(fn=cmd_repack)

    p = sub.add_parser("diff", help="compare two PACs payload by payload")
    p.add_argument("a")
    p.add_argument("b")
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("dhtb-strip", help="remove the DHTB header from an image")
    p.add_argument("image")
    p.add_argument("-o", "--out")
    p.add_argument("--info", action="store_true", help="only print the header")
    p.set_defaults(fn=cmd_dhtb_strip)

    p = sub.add_parser("dhtb-pack", help="wrap a payload in a DHTB header")
    p.add_argument("payload")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--version", type=int, default=1)
    p.add_argument("--pad-to", type=int, metavar="BYTES")
    p.set_defaults(fn=cmd_dhtb_pack)

    p = sub.add_parser("elf-to-bin", help="flatten ELF32 PT_LOAD segments")
    p.add_argument("elf")
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(fn=cmd_elf_to_bin)

    p = sub.add_parser("elf-wrap", help="wrap a raw ARM blob in an ELF32 for disassemblers")
    p.add_argument("raw")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--base", type=_int, default=0x80000000)
    p.add_argument("--thumb", action="store_true")
    p.set_defaults(fn=cmd_elf_wrap)

    p = sub.add_parser("usb", help="list Unisoc USB devices (needs pyusb; untested on hardware)")
    p.add_argument("--wait", action="store_true", help="poll until 1782:4d00 appears")
    p.add_argument("--timeout", type=float, default=120.0)
    p.set_defaults(fn=cmd_usb)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (pac.PacError, dhtb.DhtbError, elf.ElfError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
