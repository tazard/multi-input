"""Shared helpers for the evdev examples: finding keyboards, naming them, decoding keys."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from evdev import InputDevice, ecodes, list_devices

BY_PATH = "/dev/input/by-path"
BY_ID = "/dev/input/by-id"

# Keycodes are *positional* (where the key sits on a US board), not characters.
# This table assumes a US layout. Value is (unshifted, shifted).
KEYMAP: dict[int, tuple[str, str]] = {
    **{getattr(ecodes, f"KEY_{c}"): (c.lower(), c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    **{getattr(ecodes, f"KEY_{d}"): (d, s) for d, s in zip("1234567890", "!@#$%^&*()")},
    ecodes.KEY_MINUS: ("-", "_"), ecodes.KEY_EQUAL: ("=", "+"),
    ecodes.KEY_LEFTBRACE: ("[", "{"), ecodes.KEY_RIGHTBRACE: ("]", "}"),
    ecodes.KEY_SEMICOLON: (";", ":"), ecodes.KEY_APOSTROPHE: ("'", '"'),
    ecodes.KEY_GRAVE: ("`", "~"), ecodes.KEY_BACKSLASH: ("\\", "|"),
    ecodes.KEY_COMMA: (",", "<"), ecodes.KEY_DOT: (".", ">"),
    ecodes.KEY_SLASH: ("/", "?"), ecodes.KEY_SPACE: (" ", " "),
    ecodes.KEY_TAB: ("\t", "\t"),
    # Numeric keypad (assumes NumLock on, which is what scanners/keypads usually send)
    **{getattr(ecodes, f"KEY_KP{d}"): (d, d) for d in "0123456789"},
    ecodes.KEY_KPDOT: (".", "."), ecodes.KEY_KPMINUS: ("-", "-"),
    ecodes.KEY_KPPLUS: ("+", "+"), ecodes.KEY_KPASTERISK: ("*", "*"),
    ecodes.KEY_KPSLASH: ("/", "/"),
}
SHIFTS = {ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT}
ENTERS = {ecodes.KEY_ENTER, ecodes.KEY_KPENTER}


def is_keyboard(dev: InputDevice) -> bool:
    """True for devices that can type letters. Filters out the 'Consumer Control' /
    'System Control' / mouse interfaces that a single USB keyboard also exposes."""
    keys = dev.capabilities().get(ecodes.EV_KEY, [])
    return all(k in keys for k in (ecodes.KEY_A, ecodes.KEY_Z, ecodes.KEY_ENTER, ecodes.KEY_SPACE))


def _symlinks_to(directory: str, event_path: str) -> list[str]:
    """All symlinks in `directory` that resolve to `event_path`."""
    if not os.path.isdir(directory):
        return []
    real = os.path.realpath(event_path)
    return sorted(
        os.path.join(directory, n)
        for n in os.listdir(directory)
        if os.path.realpath(os.path.join(directory, n)) == real
    )


def by_path(event_path: str) -> str | None:
    links = _symlinks_to(BY_PATH, event_path)
    return links[0] if links else None


def by_id(event_path: str) -> str | None:
    links = _symlinks_to(BY_ID, event_path)
    return links[0] if links else None


def usb_port(event_path: str) -> str | None:
    """Short port label from the by-path name, e.g. 'usb-0:1.5.1' for
    platform-3f980000.usb-usb-0:1.5.1:1.0-event-kbd."""
    link = by_path(event_path)
    if not link:
        return None
    name = os.path.basename(link)
    # <controller>-usb-<bus>:<port.chain>:<config>.<interface>-event-kbd
    i = name.find("-usb-")
    if i < 0:
        return name
    rest = name[i + 1:].split("-event")[0]          # usb-0:1.5.1:1.0
    return rest.rsplit(":", 1)[0]                    # usb-0:1.5.1


def label(dev: InputDevice) -> str:
    """Human-readable 'which keyboard' label: device name + physical USB port."""
    port = usb_port(dev.path)
    return f"{dev.name} @ {port}" if port else dev.name


def find_keyboards() -> list[InputDevice]:
    devs = [InputDevice(p) for p in list_devices()]
    kbds = [d for d in devs if is_keyboard(d)]
    for d in devs:
        if d not in kbds:
            d.close()
    return sorted(kbds, key=lambda d: d.path)


@dataclass
class KeyDecoder:
    """Turns a stream of EV_KEY events from ONE device into characters / lines.
    Keep one instance per device, otherwise Shift on keyboard A would affect keyboard B."""
    shift: bool = False
    caps: bool = False
    buf: list[str] = field(default_factory=list)

    def feed(self, code: int, value: int) -> tuple[str | None, str | None]:
        """Returns (char_typed, completed_line). value: 1=down, 0=up, 2=autorepeat."""
        if code in SHIFTS:
            self.shift = value != 0
            return None, None
        if value == 0:
            return None, None
        if code == ecodes.KEY_CAPSLOCK and value == 1:
            self.caps = not self.caps
            return None, None
        if code in ENTERS:
            line = "".join(self.buf)
            self.buf.clear()
            return "\n", line
        if code == ecodes.KEY_BACKSPACE:
            if self.buf:
                self.buf.pop()
            return "\b", None
        if code in KEYMAP:
            lower, upper = KEYMAP[code]
            use_upper = self.shift ^ (self.caps and lower.isalpha())
            ch = upper if use_upper else lower
            self.buf.append(ch)
            return ch, None
        return None, None
