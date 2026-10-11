#!/usr/bin/env python3
"""List every input device, mark which ones are real keyboards, and show the
stable /dev/input/by-id and /dev/input/by-path names for each.

    python3 00_list_keyboards.py
"""
from evdev import InputDevice, list_devices

from kbd_common import by_id, by_path, is_keyboard, usb_port


def main() -> None:
    for path in sorted(list_devices()):
        dev = InputDevice(path)
        mark = "KEYBOARD" if is_keyboard(dev) else "        "
        print(f"{mark}  {dev.path:<18} {dev.name}")
        print(f"          phys:    {dev.phys}")
        print(f"          by-id:   {by_id(path) or '-'}")
        print(f"          by-path: {by_path(path) or '-'}")
        print(f"          port:    {usb_port(path) or '-'}")
        print()
        dev.close()


if __name__ == "__main__":
    main()
