# unisoc-pac-tools

Small, dependency-free Python tools for Unisoc (Spreadtrum) firmware files:

- inspect, extract, **repack**, CRC-check and **diff** `.pac` firmware archives
- wrap/strip the `DHTB` container around loader, boot and kernel images
- flatten an ELF32 to a raw binary, or wrap a raw ARM blob in an ELF for disassemblers
- (optional, hardware-untested) list Unisoc devices on USB

```
pip install .            # no runtime dependencies
pip install '.[usb]'     # adds pyusb for `upt usb`
upt list firmware.pac
upt extract firmware.pac out/            # files are written as <ID>_<name>
upt check firmware.pac                   # header + data CRC-16
upt repack firmware.pac new.pac --replace KernelImg=my_kernel.bin
upt diff firmware.pac new.pac
upt dhtb-strip KernelImg_x.bin -o payload.bin
upt dhtb-pack payload.bin -o image.bin [--pad-to N]
upt elf-to-bin in.elf -o out.bin
upt elf-wrap raw.bin -o out.elf --base 0x80000000 [--thumb]
```

## WARNING: you can brick a phone

This project edits firmware files. Writing a modified `.pac`, kernel, boot
loader or DHTB image to a device can leave it permanently unbootable,
especially if BOOT0/BOOT1/FDL images or NV (calibration and device identity) partitions are
touched. Nothing here flashes anything, but its output is meant to be flashed
by other tools. Keep a full backup of the device first, never replace
bootloader partitions unless you have a recovery path, and use everything at
your own risk (see the licences: no warranty).

## What is verified and what is not

Verified (against a real UMS9117 feature-phone firmware, 38 MB, 34 table
entries, 19 payloads; the firmware itself is not part of this repository):

| Check | Result |
| --- | --- |
| Header/table parsing vs. the public `unpac` C tool built from [spreadtrum_flash](https://github.com/ilyakurdyukov/spreadtrum_flash) | same IDs, names, sizes, offsets, type and addr fields |
| `extract` vs. `unpac extract` | all payloads byte-identical (by sha256) |
| `check` vs. `unpac check` | same head_crc `0x0b1a` and data_crc `0xe12f` |
| `repack` with no replacements | output **byte-identical** to the input |
| `repack --replace` with the identical file | byte-identical to the input |
| `repack --replace` with a different-size file | `unpac check`/`list` accept the result, CRCs valid |
| `diff` of two builds differing in one partition | reports exactly that partition |
| `dhtb-strip` then `dhtb-pack` on FDL1, BOOT1, KernelImg, UserImg | byte-identical to the original images |

Plus a pytest suite built from synthetic archives (no firmware bytes).

Not verified:

- Anything involving a USB device. `upt usb` only enumerates the bus
  (read-only); it is **untested on hardware beyond the facts below**.
- PAC files above 4 GiB (the 64-bit size/offset words are handled per the
  `unpac` layout but untested on real data) and PAC variants other than the one
  described below.
- DHTB variants with digests/signatures (secure-boot chips). In the images
  checked, every header byte except magic, version and length was zero.
- Whether a repacked PAC is accepted by a given vendor flashing tool. The
  structure is checked, not the flashing.
- Repacking a PAC with padding between payloads compacts it (documented, not
  byte-identical).

Notes from testing: a modified firmware produced by other tooling carried the
*original* data CRC (`upt check` flags this). `upt repack` always recomputes
both CRCs.

## Formats

All integers are little endian. Strings are UTF-16LE, NUL padded.

### PAC header (2124 bytes)

| Offset | Size | Field |
| --- | --- | --- |
| 0x000 | 48 | `pac_version` (e.g. `BP_R1.0.0`) |
| 0x030 | 4 | `pac_size` (total file length) |
| 0x034 | 512 | `fw_name` (product, e.g. `UMS9117`) |
| 0x234 | 512 | `fw_version` |
| 0x434 | 4 | `file_count` |
| 0x438 | 4 | `dir_offset` (always 2124) |
| 0x43C | 0x408 | unknown, alias string; preserved verbatim |
| 0x844 | 4 | magic `0xFFFAFFFA` |
| 0x848 | 2 | `head_crc`: CRC-16/ARC of bytes `0..0x848` |
| 0x84A | 2 | `data_crc`: CRC-16/ARC of bytes `2124..pac_size` |

CRC-16/ARC: reflected, polynomial `0xA001`, initial value 0.

### PAC file entry (2580 bytes each, from `dir_offset`)

| Offset | Size | Field |
| --- | --- | --- |
| 0x000 | 4 | `struct_size` (2580) |
| 0x004 | 512 | `id` (`FDL`, `BOOT1`, `KernelImg`, ...) |
| 0x204 | 512 | `name` |
| 0x5FC | 4 | `size_high` |
| 0x600 | 4 | `offset_high` |
| 0x604 | 4 | `size` (low) |
| 0x608 | 4 | `type` (0 operation, 1 file, 2 xml, 0x101 FDL) |
| 0x60C | 4 | `flash_use` |
| 0x610 | 4 | `offset` (low) |
| 0x614 | 4 | `omit_flag` |
| 0x618 | 4 | `addr_num` |
| 0x61C | 20 | `addr[5]` |
| 0x630 | 996 | unknown, preserved |

Size and offset are 64-bit (`high << 32 | low`). Entries with size 0 or
offset 0 carry no payload. Several IDs can share one file name, so `extract`
prefixes the ID.

### DHTB image

```
0x000  "DHTB"          magic
0x004  u32 version     1
0x030  u32 payload_len == file_size - 0x200
0x200  payload
```

## Layout

`unisoc_pac_tools/` has `pac.py`, `dhtb.py`, `elf.py`, `usb_detect.py` and the
`upt` CLI (`cli.py`). `python -m unisoc_pac_tools` also works.

## USB facts (from bring-up on one UMS9117 phone)

Vendor ID `0x1782`. `1782:4d00` with no product string is download mode.
`1782:4d01` ("Generic Disk", mass storage) and `1782:000c` ("Unisoc Phone")
are the normal OS, meaning the phone booted instead of entering download
mode. On that phone, holding `*` while plugging in gave a 4d00 that was the
OS's boot-mode listener rather than the boot ROM. Only observed on one
device; treat as hints.

## Not included

The BSL/FDL flashing client was dropped: it was never validated against a
device and contained an invented partition read/write protocol. Use
[`spd_dump`](https://github.com/ilyakurdyukov/spreadtrum_flash) for
actual flashing.

## Credits

The PAC layout and CRCs follow `unpac` and `spd_dump` by Ilya Kurdyukov
(public domain): <https://github.com/ilyakurdyukov/spreadtrum_flash>. The
DHTB notes come from inspecting real images.

## Development

```
pip install -e '.[test]'
pytest
```

## License

Licensed under either of MIT ([LICENSE-MIT](LICENSE-MIT)) or Apache-2.0
([LICENSE-APACHE](LICENSE-APACHE)) at your option.
