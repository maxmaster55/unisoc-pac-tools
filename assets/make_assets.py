#!/usr/bin/env python3
"""Regenerate the README images in this directory.

    pip install -e '.[test]' pillow
    python3 assets/make_assets.py

upt-demo.gif   a terminal session: real `upt` runs on a synthetic .pac built
               with the test suite's builders (tests/conftest.py), in a
               temporary directory. No firmware bytes are involved.
pac-layout.svg the PAC file layout (header, file table, payloads, CRCs).
dhtb.svg       the DHTB container.

Needs Pillow, pytest (imported by tests/conftest.py) and the DejaVu Sans Mono
font (found with fc-match).
"""

import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"
sys.path.insert(0, str(ROOT / "tests"))
from conftest import ENTRY, HEADER, make_dhtb, make_pac  # noqa: E402

# One dark palette for every image; each carries a solid background so it
# reads the same on GitHub's light and dark themes.
BG = "#0f172a"
PANEL = "#1e293b"
LINE = "#334155"
MUTED = "#94a3b8"
TEXT = "#e2e8f0"
GREEN = "#4ade80"
AMBER = "#fbbf24"
BLUE = "#60a5fa"
VIOLET = "#c084fc"
RED = "#f87171"
SANS = "system-ui,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'DejaVu Sans Mono',monospace"

# ------------------------------------------------------------ demo session


def blob(seed, n):
    return random.Random(seed).randbytes(n)


def demo_files(work):
    files = [
        ("FDL", "fdl1.bin", make_dhtb(blob(1, 12_000))),
        ("FDL2", "fdl2.bin", make_dhtb(blob(2, 40_000))),
        ("BOOT1", "boot1.bin", make_dhtb(blob(3, 24_000))),
        ("KernelImg", "kernel.bin", make_dhtb(blob(4, 96_000))),
        ("UserImg", "user.bin", make_dhtb(blob(5, 160_000))),
    ]
    pac = make_pac(files, ops=("EraseFS",), product="DEMOCHIP", fw="DEMO_FW_1.0")
    (work / "demo.pac").write_bytes(pac)
    (work / "my_kernel.bin").write_bytes(make_dhtb(blob(6, 101_000)))


SESSION = [
    "upt list demo.pac",
    "upt check demo.pac",
    "upt extract demo.pac out/",
    "upt repack demo.pac new.pac --replace KernelImg=my_kernel.bin",
    "upt check new.pac",
    "upt diff demo.pac new.pac",
]


def run_session():
    """[(command, output lines)], run for real in a scratch directory."""
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        demo_files(work)
        result = []
        for cmd in SESSION:
            argv = [sys.executable, "-m", "unisoc_pac_tools", *cmd.split()[1:]]
            p = subprocess.run(argv, cwd=work, env=env, capture_output=True, text=True)
            result.append((cmd, (p.stdout + p.stderr).rstrip("\n").splitlines()))
    return result


def line_colour(line, prev_header):
    if line == "OK":
        return GREEN
    if line == "MISMATCH" or line.startswith("error"):
        return RED
    if prev_header == "diff" and line.startswith("  "):
        return AMBER
    if line.startswith("  replaced"):
        return AMBER
    return TEXT


def font_file(pattern):
    path = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True).stdout
    if not path:
        sys.exit(f"font not found: {pattern}")
    return path


def terminal_gif():
    session = run_session()
    cols, rows, cw, lh = 104, 22, 8, 17
    mono = ImageFont.truetype(font_file("DejaVu Sans Mono"), 13)
    title_f = ImageFont.truetype(font_file("DejaVu Sans"), 12)
    pad, top = 16, 34
    W, H = pad * 2 + cols * cw, top + rows * lh + 14

    def render(lines, cursor):
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, W, 24), fill=PANEL)
        for i, c in enumerate((RED, AMBER, GREEN)):
            d.ellipse((12 + i * 18, 7, 22 + i * 18, 17), fill=c)
        d.text((W / 2, 12), "upt  (synthetic demo.pac)", font=title_f, anchor="mm", fill=MUTED)
        for r, segs in enumerate(lines[-rows:]):
            x = pad
            for text, colour in segs:
                d.text((x, top + r * lh), text, font=mono, fill=colour)
                x += len(text) * cw
            if cursor and r == len(lines[-rows:]) - 1:
                d.rectangle((x + 1, top + r * lh + 1, x + cw - 1, top + r * lh + lh - 2), fill=TEXT)
        return im

    frames, durations = [], []

    def add(lines, ms, cursor=True):
        frames.append(render(lines, cursor))
        durations.append(ms)

    lines = []
    for cmd, output in session:
        prompt = [("$ ", GREEN)]
        lines.append(prompt)
        add(lines, 500)
        for i in range(2, len(cmd) + 2, 2):  # type two characters per frame
            lines[-1] = prompt + [(cmd[:i], TEXT)]
            add(lines, 45)
        add(lines, 350)
        kind = cmd.split()[1]
        for out_line in output:
            lines.append([(out_line[:cols], line_colour(out_line, kind))])
        lines.append([("", TEXT)])
        add(lines, 2400, cursor=False)
    lines.append([("$ ", GREEN)])
    add(lines, 3000)

    sheet = Image.new("RGB", (W, H * 4))
    for i, k in enumerate(range(0, len(frames), max(1, len(frames) // 4))[:4]):
        sheet.paste(frames[k], (0, H * i))
    pal = sheet.quantize(colors=32, method=Image.Quantize.MEDIANCUT)
    frames = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    path = OUT / "upt-demo.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    return path, session


# ------------------------------------------------------------------- SVGs


def svg(w, h, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'font-family="{SANS}" font-size="13">\n'
        f'<rect width="{w}" height="{h}" rx="12" fill="{BG}"/>\n{body}</svg>\n'
    )


def t(x, y, s, fill=TEXT, size=None, anchor=None, mono=False, weight=None):
    a = [f'x="{x}"', f'y="{y}"', f'fill="{fill}"']
    if size:
        a.append(f'font-size="{size}"')
    if anchor:
        a.append(f'text-anchor="{anchor}"')
    if mono:
        a.append(f'font-family="{MONO}"')
    if weight:
        a.append(f'font-weight="{weight}"')
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<text {' '.join(a)}>{s}</text>"


def rect(x, y, w, h, fill=PANEL, stroke=LINE, rx=6, extra=""):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}"{extra}/>'


def field_table(x, y, w, title, colour, rows, hot=()):
    """A zoomed-in struct: (offset, size, field) rows; `hot` fields get colour."""
    rh = 19
    h = 30 + len(rows) * rh + 6
    out = [rect(x, y, w, h, stroke=colour), t(x + 12, y + 20, title, colour, weight="600")]
    for i, (off, size, name) in enumerate(rows):
        ry = y + 30 + i * rh + 13
        c = colour if name.split()[0] in hot else TEXT
        out += [t(x + 12, ry, off, MUTED, 12, mono=True), t(x + 68, ry, size, MUTED, 12, mono=True),
                t(x + 126, ry, name, c, 12.5)]
    return out, h


def pac_svg():
    W = 880
    sx, sw = 140, 170  # the file strip
    out = [
        t(24, 36, "PAC file layout", size=17, weight="600"),
        t(24, 58, "All integers little endian, strings UTF-16LE. Blocks not to scale.", MUTED),
    ]
    # the file, top to bottom
    hy, hh = 84, 118
    ty = hy + hh
    ent = [("entry 0", 30), ("entry 1", 30), ("…", 22), ("entry n-1", 30)]
    th = sum(h for _, h in ent)
    py = ty + th + 14
    pays = [("payload of entry 0", 44), ("payload of entry 1", 70), ("…", 24), ("last payload", 52)]
    ph = sum(h for _, h in pays)
    out.append(rect(sx, hy, sw, hh, fill="#3b2f12", stroke=AMBER))
    out.append(t(sx + sw / 2, hy + hh / 2 + 4, f"header  {HEADER} B", AMBER, anchor="middle", weight="600"))
    y = ty
    entry1_y = None
    for name, h in ent:
        out.append(rect(sx, y, sw, h, fill="#142c4a", stroke=BLUE, rx=0))
        out.append(t(sx + sw / 2, y + h / 2 + 4, name + (f"  {ENTRY} B" if "entry" in name else ""),
                     BLUE, 12, anchor="middle"))
        if name == "entry 1":
            entry1_y = y
        y += h
    y = py
    pay1 = None
    for name, h in pays:
        out.append(rect(sx, y, sw, h, fill="#2a1f45", stroke=VIOLET, rx=0))
        out.append(t(sx + sw / 2, y + h / 2 + 4, name, VIOLET, 12, anchor="middle"))
        if name.endswith("entry 1"):
            pay1 = (y, h)
        y += h
    end = y

    # offsets to the right of the strip
    ox = sx + sw + 8
    for yy, label in ((hy, "0"), (ty, f"{HEADER} = dir_offset"), (py, f"{HEADER} + n × {ENTRY}"),
                      (end, "pac_size")):
        out.append(f'<line x1="{sx + sw}" y1="{yy}" x2="{ox - 2}" y2="{yy}" stroke="{MUTED}"/>')
        out.append(t(ox, yy + 4, label, MUTED, 11.5, mono=True))

    # CRC coverage brackets on the left
    def bracket(y0, y1, name, what, colour):
        bx = sx - 14
        out.append(f'<path d="M{bx + 8} {y0 + 1} H{bx} V{y1 - 1} H{bx + 8}" fill="none" stroke="{colour}" '
                   f'stroke-width="2"/>')
        out.append(t(bx - 8, (y0 + y1) / 2 - 3, name, colour, 12.5, anchor="end", weight="600"))
        out.append(t(bx - 8, (y0 + y1) / 2 + 13, what, MUTED, 11, anchor="end"))

    bracket(hy, hy + hh - 6, "head_crc", "bytes 0..0x848", AMBER)
    bracket(ty, end, "data_crc", f"bytes {HEADER}..pac_size", GREEN)
    out.append(t(24, end + 30, "Both CRCs are CRC-16/ARC (reflected, poly 0xA001, init 0).", MUTED, 12))
    out.append(t(24, end + 47, "upt check verifies them; upt repack recomputes them.", MUTED, 12))

    # zoomed header
    px, pw = 500, 356
    rows_h = [("0x000", "48", "pac_version"), ("0x030", "4", "pac_size  (file length)"),
              ("0x034", "512", "fw_name  (product)"), ("0x234", "512", "fw_version"),
              ("0x434", "4", "file_count"), ("0x438", "4", f"dir_offset  (= {HEADER})"),
              ("0x43C", "0x408", "unknown, kept verbatim"), ("0x844", "4", "magic  0xFFFAFFFA"),
              ("0x848", "2", "head_crc"), ("0x84A", "2", "data_crc")]
    tab, h1 = field_table(px, 76, pw, "header", AMBER, rows_h, hot=("magic", "head_crc", "data_crc"))
    out += tab
    zoom = f'stroke="{LINE}" stroke-dasharray="3 3" fill="none"'
    out.append(f'<path d="M{sx + sw} {hy} L{px} 76 M{sx + sw} {hy + hh} L{px} {76 + h1}" {zoom}/>')

    # zoomed entry
    ey = 76 + h1 + 16
    rows_e = [("0x000", "4", "struct_size  (= 2580)"), ("0x004", "512", "id  FDL, BOOT1, KernelImg, …"),
              ("0x204", "512", "name"), ("0x5FC", "4+4", "size_high, offset_high"),
              ("0x604", "4", "size"), ("0x608", "4", "type  0 op, 1 file, 2 xml, 0x101 FDL"),
              ("0x60C", "4", "flash_use"), ("0x610", "4", "offset"),
              ("0x614", "4", "omit_flag"), ("0x618", "4+20", "addr_num, addr[5]"),
              ("0x630", "996", "unknown, kept verbatim")]
    tab, h2 = field_table(px, ey, pw, "file table entry", BLUE, rows_e, hot=("size", "offset"))
    out += tab
    out.append(f'<path d="M{sx + sw} {entry1_y + 15} L{px} {ey + 15}" {zoom}/>')

    # offset/size point at the payload
    off_y = ey + 30 + 7 * 19 + 9
    py1, ph1 = pay1
    out.append(f'<path d="M{px} {off_y} C{px - 90} {off_y}, {sx + sw + 110} {py1 + 4}, {sx + sw + 3} {py1 + 4}" '
               f'fill="none" stroke="{BLUE}" stroke-width="1.6" marker-end="url(#a)"/>')
    out.append(t(px - 8, off_y + 17, "offset", BLUE, 11.5, anchor="end"))
    out.insert(0, f'<defs><marker id="a" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" '
                  f'orient="auto"><path d="M0 0L8 4L0 8z" fill="{BLUE}"/></marker></defs>')
    note_y = ey + h2 + 22
    out.append(t(px, note_y, "size/offset are 64-bit: high << 32 | low.", MUTED, 12))
    out.append(t(px, note_y + 17, "size 0 or offset 0: no payload (an operation", MUTED, 12))
    out.append(t(px, note_y + 34, "such as an erase step).", MUTED, 12))
    H = max(end + 70, note_y + 52)
    return svg(W, H, "\n".join(out) + "\n")


def dhtb_svg():
    W, H = 880, 270
    x0, y0, bh = 40, 96, 54
    segs = [  # (label, sublabel, width, colour, fill)
        ('"DHTB"', "magic", 82, AMBER, "#3b2f12"),
        ("1", "version", 70, AMBER, "#3b2f12"),
        ("0", "0x08..0x2F", 92, MUTED, PANEL),
        ("payload_len", "u32", 104, GREEN, "#123524"),
        ("0", "0x34..0x1FF", 112, MUTED, PANEL),
        ("payload", "payload_len bytes", 336, VIOLET, "#2a1f45"),
    ]
    offs = ["0x000", "0x004", "0x008", "0x030", "0x034", "0x200"]
    out = [t(24, 36, "DHTB image", size=17, weight="600"),
           t(24, 58, "The container around FDL, BOOT, KernelImg and UserImg images. Little endian; "
                     "not to scale.", MUTED)]
    x = x0
    for (lab, sub, w, c, fill), off in zip(segs, offs):
        out.append(rect(x, y0, w, bh, fill=fill, stroke=c, rx=0))
        out.append(t(x + w / 2, y0 + 23, lab, c, 13, anchor="middle", mono=lab not in ("payload",),
                     weight="600"))
        out.append(t(x + w / 2, y0 + 41, sub, MUTED, 11, anchor="middle"))
        out.append(f'<line x1="{x}" y1="{y0 - 4}" x2="{x}" y2="{y0 - 12}" stroke="{MUTED}"/>')
        out.append(t(x + 3, y0 - 6, off, MUTED, 11, mono=True))
        x += w
    out.append(t(x - 3, y0 - 6, "file end", MUTED, 11, anchor="end"))
    hdr_end = x - segs[-1][2]
    # braces
    def brace(xa, xb, y, label, colour):
        out.append(f'<path d="M{xa + 1} {y} v8 H{xb - 1} v-8" fill="none" stroke="{colour}" stroke-width="1.6"/>')
        out.append(t((xa + xb) / 2, y + 26, label, colour, 12.5, anchor="middle"))
    brace(x0, hdr_end, y0 + bh + 8, "0x200-byte header", AMBER)
    brace(hdr_end, x, y0 + bh + 8, "payload_len == file_size - 0x200", VIOLET)
    out.append(t(24, 226, "Every header byte except magic, version and payload_len was zero in the images "
                          "checked (no digest or signature).", MUTED, 12))
    out.append(t(24, 248, "upt dhtb-strip image -o payload.bin", TEXT, 12, mono=True))
    out.append(t(330, 248, "upt dhtb-pack payload.bin -o image [--pad-to N]", TEXT, 12, mono=True))
    return svg(W, H, "\n".join(out) + "\n")


if __name__ == "__main__":
    gif, session = terminal_gif()
    (OUT / "pac-layout.svg").write_text(pac_svg())
    (OUT / "dhtb.svg").write_text(dhtb_svg())
    for cmd, output in session:
        print("$", cmd, *output, sep="\n  ")
    for name in ("upt-demo.gif", "pac-layout.svg", "dhtb.svg"):
        print(f"assets/{name}  {(OUT / name).stat().st_size / 1024:.0f} KiB")
