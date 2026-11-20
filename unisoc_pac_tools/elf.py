"""Small ELF32 helpers for firmware blobs (no binutils needed).

* :func:`elf_to_bin` flattens PT_LOAD segments, like ``objcopy -O binary``.
* :func:`wrap_elf` puts a raw ARM blob in a minimal ELF32 so disassemblers
  (IDA, Ghidra) pick the right CPU, endianness and load address.
"""

from __future__ import annotations

import struct

PT_LOAD = 1
EM_ARM = 40
_EHDR = 52
_PHDR = 32
_PAGE = 0x1000


class ElfError(ValueError):
    pass


def segments(data: bytes) -> list[tuple[int, int, int, int]]:
    """Return sorted ``(vaddr, memsz, file_off, filesz)`` for each PT_LOAD."""
    if len(data) < _EHDR or data[:4] != b"\x7fELF":
        raise ElfError("not an ELF file")
    if data[4] != 1:
        raise ElfError("not ELF32")
    if data[5] != 1:
        raise ElfError("not little-endian")
    (phoff,) = struct.unpack_from("<I", data, 28)
    (phentsize, phnum) = struct.unpack_from("<HH", data, 42)
    if phentsize != _PHDR:
        raise ElfError(f"unexpected phentsize {phentsize}")
    out = []
    for i in range(phnum):
        base = phoff + i * _PHDR
        if base + _PHDR > len(data):
            raise ElfError("program header table truncated")
        p_type, off, vaddr, _paddr, filesz, memsz, _fl, _al = struct.unpack_from(
            "<8I", data, base
        )
        if p_type == PT_LOAD:
            if off + filesz > len(data):
                raise ElfError("segment extends past end of file")
            out.append((vaddr, memsz, off, filesz))
    if not out:
        raise ElfError("no PT_LOAD segments")
    return sorted(out)


def elf_to_bin(data: bytes) -> bytes:
    """Flat image from the lowest load address up; gaps and .bss are zero-filled."""
    out = bytearray()
    cursor = None
    for vaddr, _memsz, off, filesz in segments(data):
        if cursor is None:
            cursor = vaddr
        if vaddr > cursor:
            out += b"\0" * (vaddr - cursor)
        out += data[off : off + filesz]
        cursor = vaddr + filesz
    return bytes(out)


def wrap_elf(payload: bytes, base: int = 0x80000000, thumb: bool = False) -> bytes:
    """Wrap a raw ARM blob in a single-segment ELF32 executable."""
    data_off = _PAGE + (base % _PAGE)  # keep vaddr congruent to offset mod page
    ehdr = struct.pack(
        "<16sHHIIIIIHHHHHH",
        b"\x7fELF" + bytes([1, 1, 1, 0]) + b"\0" * 8,
        2,  # ET_EXEC
        EM_ARM,
        1,
        base | (1 if thumb else 0),
        _EHDR,  # e_phoff
        0,  # e_shoff
        0x05000000,  # EF_ARM_EABI_VER5
        _EHDR,
        _PHDR,
        1,
        40,
        0,
        0,
    )
    phdr = struct.pack(
        "<8I", PT_LOAD, data_off, base, base, len(payload), len(payload), 5, _PAGE
    )
    return ehdr + phdr + b"\0" * (data_off - len(ehdr) - len(phdr)) + payload
