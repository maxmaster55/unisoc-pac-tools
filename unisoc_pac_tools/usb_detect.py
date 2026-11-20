"""Detect a Unisoc phone on the USB bus (read-only; needs ``pyusb``).

UNTESTED ON HARDWARE as a packaged module: the device-ID facts below come from
bring-up notes on one UMS9117 feature phone, not from a survey of devices.
This module only enumerates the bus; it never opens, claims or writes to a
device.

Known IDs (vendor 0x1782 = Spreadtrum/Unisoc):

* ``1782:4d00`` with no product string: download mode (boot ROM / BOOT1
  "auto download").  This is the one flashing tools such as ``spd_dump`` talk
  to.  On the observed phone, holding ``*`` while plugging in produced a
  4d00 that was *not* the boot ROM but the OS's own boot-mode listener (it
  ignores the BSL handshake and boots on after a few seconds).
* ``1782:4d01`` ("Generic Disk"): the normal OS in USB mass-storage mode.
* ``1782:000c`` ("Unisoc Phone"): the normal OS in its default USB mode.

Seeing 4d01 or 000c means the phone booted normally instead of entering
download mode.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

UNISOC_VID = 0x1782
KNOWN_PIDS = {
    0x4D00: "download mode",
    0x4D01: "normal OS, mass storage (not download mode)",
    0x000C: "normal OS, default USB mode (not download mode)",
}


@dataclass
class UsbDevice:
    vid: int
    pid: int
    product: str

    @property
    def description(self) -> str:
        return KNOWN_PIDS.get(self.pid, "unknown mode")


def list_unisoc_devices() -> list[UsbDevice]:
    """Enumerate Unisoc USB devices. Raises ImportError if pyusb is missing."""
    import usb.core
    import usb.util

    found = []
    for dev in usb.core.find(find_all=True, idVendor=UNISOC_VID):
        try:
            name = usb.util.get_string(dev, dev.iProduct) or ""
        except Exception:  # no permission / no string descriptor
            name = ""
        found.append(UsbDevice(dev.idVendor, dev.idProduct, name))
    return found


def wait_for_download_mode(timeout: float = 120.0, interval: float = 1.0) -> bool:
    """Poll until a 1782:4d00 device shows up; False on timeout."""
    deadline = time.monotonic() + timeout
    while True:
        if any(d.pid == 0x4D00 for d in list_unisoc_devices()):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)
