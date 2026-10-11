#!/usr/bin/env python3
"""asyncio version: one task per keyboard, as in the options doc.

Devices are chosen by /dev/input/by-path (i.e. by physical USB port), so a
"station" keeps its name even if you swap the keyboard/scanner plugged into it.
Any other keyboards found are added with an automatic label.

    python3 03_asyncio.py --grab
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from evdev import InputDevice, ecodes

from kbd_common import KeyDecoder, find_keyboards, label

# Physical USB port -> role. Edit to match `python3 00_list_keyboards.py`.
# These are the two ports used on the Raspberry Pi 3 this was written on.
STATIONS: dict[str, str] = {
    "/dev/input/by-path/platform-3f980000.usb-usb-0:1.2:1.0-event-kbd": "station-A (Pi port 1.2)",
    "/dev/input/by-path/platform-3f980000.usb-usb-0:1.5.1:1.0-event-kbd": "station-B (hub on 1.5, port 1)",
}


async def read_device(dev: InputDevice, name: str, out: asyncio.Queue) -> None:
    decoder = KeyDecoder()
    try:
        async for ev in dev.async_read_loop():
            if ev.type != ecodes.EV_KEY:
                continue
            _ch, line = decoder.feed(ev.code, ev.value)
            if line is not None:
                await out.put((name, line))
    except OSError:
        await out.put((name, None))  # unplugged


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grab", action="store_true", help="take exclusive access to the keyboards")
    args = ap.parse_args()

    devices: list[tuple[InputDevice, str]] = []
    taken: set[str] = set()
    for path, role in STATIONS.items():
        if os.path.exists(path):
            dev = InputDevice(path)
            devices.append((dev, f"{role} | {dev.name}"))
            taken.add(os.path.realpath(path))
        else:
            print(f"(nothing plugged into {role}: {path})")
    for dev in find_keyboards():
        if os.path.realpath(dev.path) in taken:
            dev.close()
        else:
            devices.append((dev, f"unassigned | {label(dev)}"))

    if not devices:
        sys.exit("No keyboards found (are you in the 'input' group?)")
    print("Listening on:")
    for dev, name in devices:
        print(f"  {dev.path}  {name}")
    print("Type a line on each keyboard and press Enter. Ctrl+C here to quit.\n")

    if args.grab:
        for dev, _ in devices:
            dev.grab()

    # Readers push (keyboard, line) onto one queue; a single consumer handles them
    # in arrival order. Swap the print for your app's barcode/command handler.
    queue: asyncio.Queue = asyncio.Queue()
    tasks = [asyncio.create_task(read_device(d, n, queue)) for d, n in devices]
    live = len(tasks)
    try:
        while live:
            name, line = await queue.get()
            if line is None:
                print(f"[{name}] unplugged")
                live -= 1
            else:
                print(f"[{name}] {line!r}")
    finally:
        for t in tasks:
            t.cancel()
        for dev, _ in devices:
            try:
                if args.grab:
                    dev.ungrab()
                dev.close()
            except OSError:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
