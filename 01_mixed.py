#!/usr/bin/env python3
"""The "standard" way: read ALL keyboards and merge them into one text stream,
exactly like the OS does for the focused window. You can't tell who typed what.

Works over SSH because it reads /dev/input/event* directly, not your terminal's stdin.

    python3 01_mixed.py           # keys ALSO still go to the Pi's console/desktop
    python3 01_mixed.py --grab    # keys go ONLY to this script
"""
import argparse
import select
import sys

from evdev import ecodes

from kbd_common import KeyDecoder, find_keyboards, label


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grab", action="store_true", help="take exclusive access to the keyboards")
    args = ap.parse_args()

    keyboards = find_keyboards()
    if not keyboards:
        sys.exit("No keyboards found (are you in the 'input' group?)")
    print("Reading (merged) from:")
    for k in keyboards:
        print(f"  {k.path}  {label(k)}")
    print("Type on any keyboard. Ctrl+C here to quit.\n")

    # ONE decoder shared by every keyboard -> Shift held on keyboard A also
    # capitalises keyboard B, and half-typed text from both lands in one buffer.
    # This is the problem the other examples solve.
    decoder = KeyDecoder()
    if args.grab:
        for k in keyboards:
            k.grab()
    try:
        while keyboards:
            ready, _, _ = select.select(keyboards, [], [])
            for dev in ready:
                try:
                    events = list(dev.read())
                except OSError:  # unplugged
                    print(f"\n[unplugged: {dev.path}]")
                    keyboards.remove(dev)
                    continue
                for ev in events:
                    if ev.type != ecodes.EV_KEY:
                        continue
                    ch, _line = decoder.feed(ev.code, ev.value)
                    if ch == "\b":
                        sys.stdout.write("\b \b")
                    elif ch:
                        sys.stdout.write(ch)
                    sys.stdout.flush()
    except KeyboardInterrupt:
        print()
    finally:
        for k in keyboards:
            try:
                if args.grab:
                    k.ungrab()
                k.close()
            except OSError:
                pass


if __name__ == "__main__":
    main()
