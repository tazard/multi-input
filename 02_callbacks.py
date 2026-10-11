#!/usr/bin/env python3
"""Synchronous, callback-based reader: no asyncio, just a `selectors` loop.
Each keyboard gets its own decoder, and every callback is told WHICH keyboard
the input came from.

    python3 02_callbacks.py --grab
"""
from __future__ import annotations

import argparse
import selectors
import sys
from datetime import datetime
from typing import Callable

from evdev import InputDevice, ecodes

from kbd_common import KeyDecoder, find_keyboards, label

KeyCallback = Callable[[str, str], None]    # (keyboard_label, char)
LineCallback = Callable[[str, str], None]   # (keyboard_label, full_line)


class KeyboardHub:
    """Watches several keyboards and dispatches per-device callbacks."""

    def __init__(self, devices: list[InputDevice], grab: bool = False) -> None:
        self.sel = selectors.DefaultSelector()
        self.grab = grab
        self._on_key: list[KeyCallback] = []
        self._on_line: list[LineCallback] = []
        for dev in devices:
            if grab:
                dev.grab()
            # store (label, decoder) alongside the device
            self.sel.register(dev, selectors.EVENT_READ, (label(dev), KeyDecoder()))

    def on_key(self, cb: KeyCallback) -> KeyCallback:
        self._on_key.append(cb)
        return cb

    def on_line(self, cb: LineCallback) -> LineCallback:
        self._on_line.append(cb)
        return cb

    def run(self) -> None:
        while self.sel.get_map():
            for key, _mask in self.sel.select():
                dev: InputDevice = key.fileobj
                name, decoder = key.data
                try:
                    events = list(dev.read())
                except OSError:
                    print(f"[{name}] unplugged")
                    self.sel.unregister(dev)
                    continue
                for ev in events:
                    if ev.type != ecodes.EV_KEY:
                        continue
                    ch, line = decoder.feed(ev.code, ev.value)
                    if ch and ch not in "\n\b":
                        for cb in self._on_key:
                            cb(name, ch)
                    if line is not None:
                        for cb in self._on_line:
                            cb(name, line)

    def close(self) -> None:
        for key in list(self.sel.get_map().values()):
            dev: InputDevice = key.fileobj
            try:
                if self.grab:
                    dev.ungrab()
                dev.close()
            except OSError:
                pass
        self.sel.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grab", action="store_true", help="take exclusive access to the keyboards")
    ap.add_argument("--keys", action="store_true", help="also print every single keypress")
    args = ap.parse_args()

    keyboards = find_keyboards()
    if not keyboards:
        sys.exit("No keyboards found (are you in the 'input' group?)")
    print("Listening on:")
    for k in keyboards:
        print(f"  {k.path}  {label(k)}")
    print("Type a line on each keyboard and press Enter. Ctrl+C here to quit.\n")

    hub = KeyboardHub(keyboards, grab=args.grab)

    @hub.on_line
    def print_line(keyboard: str, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{ts}  [{keyboard}]  {text!r}")

    if args.keys:
        @hub.on_key
        def print_key(keyboard: str, ch: str) -> None:
            print(f"          key  [{keyboard}]  {ch!r}")

    try:
        hub.run()
    except KeyboardInterrupt:
        print()
    finally:
        hub.close()


if __name__ == "__main__":
    main()
