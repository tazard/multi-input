# Reading Multiple Keyboards / Barcode Scanners Separately

How to tell which physical device input came from (multiple scanners, keyboards, keypads) instead of receiving one merged stream of keystrokes.

## Summary

| # | Option | Extra hardware | Platform | Effort | Best when |
|---|--------|----------------|----------|--------|-----------|
| 1 | Scanner-configured prefix/suffix | None | Any | Very low | Scanners are programmable |
| 2 | Scanner in USB serial (CDC) / HID POS mode | None | Any | Low | Scanners support it |
| 3 | evdev on Linux | None | Linux only | Low–medium | App runs on Linux |
| 4 | Microcontroller bridge (ESP32 / RP2040) | Yes | Any | High | Keyboard-only devices on a locked-down platform |

**Recommended order:** 1 or 2 first, 3 if on Linux, 4 only as a last resort.

---

## Option 1 — Scanner-configured prefix/suffix

Almost all commercial scanners (Honeywell, Zebra, Datalogic, etc.) can be configured by scanning programming barcodes from the manual. Give each scanner a unique prefix.

- Example prefixes: `\x02S1:`, `\x02S2:` with a suffix of `\r` or `\n`
- Optionally enable **AIM symbology identifiers** to also get the barcode type (e.g. `]C1` for Code 128)

**Pros**
- Zero hardware, zero firmware
- Works on any OS and in any app that accepts keyboard input

**Cons**
- Still keyboard emulation: depends on window focus and keyboard layout
- Two scanners firing at once can interleave keystrokes
- Configuration lives on each scanner — a replaced or factory-reset unit loses it
- Prefix characters could collide with real typed input

---

## Option 2 — USB serial (CDC-ACM) or HID POS mode

Most scanners can be switched (via a config barcode) out of keyboard emulation into:

- **USB CDC / virtual COM** — appears as `/dev/ttyACM0` (Linux) or `COMx` (Windows) and sends whole barcode strings
- **HID POS** — a dedicated barcode HID usage page, not a keyboard; read through hidapi or OS POS APIs

Identify devices stably with `/dev/serial/by-id/` on Linux, or by USB serial number / VID:PID on Windows.

```python
import serial  # pyserial

def read_scanner(port: str, name: str) -> None:
    with serial.Serial(port, 115200, timeout=None) as ser:
        while True:
            line: bytes = ser.readline()
            print(f"[{name}] {line.decode(errors='replace').strip()}")
```

**Pros**
- Clean strings, no keycode decoding, no layout issues, no focus issues
- Each device is a separate stream by construction

**Cons**
- Not supported by cheap generic scanners
- Doesn't help with plain keyboards or keypads

---

## Option 3 — evdev on Linux

Every input device has its own `/dev/input/eventN` node. Read raw key events per device with [python-evdev](https://python-evdev.readthedocs.io/).

**Key points**
- Use `/dev/input/by-id/` or `/dev/input/by-path/` — `eventN` numbers change between boots
- Call `dev.grab()` so keystrokes go only to your process, not the focused window or console
- Permissions: add the user to the `input` group, or write a udev rule:
  ```
  SUBSYSTEM=="input", ATTRS{idVendor}=="05e0", MODE="0660", GROUP="scanners"
  ```
- You get keycodes, not characters: track Shift yourself and treat Enter as end-of-scan. Keycodes are positional (this mapping assumes US layout)
- Use `python -m evdev.evtest` to list devices and watch events
- For hotplug, watch with `pyudev` and spawn a reader task per device

```python
import asyncio
from evdev import InputDevice, ecodes

KEYMAP: dict[int, tuple[str, str]] = {
    **{getattr(ecodes, f"KEY_{c}"): (c.lower(), c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    **{getattr(ecodes, f"KEY_{d}"): (d, s) for d, s in zip("1234567890", "!@#$%^&*()")},
    ecodes.KEY_MINUS: ("-", "_"), ecodes.KEY_DOT: (".", ">"),
    ecodes.KEY_SLASH: ("/", "?"), ecodes.KEY_SPACE: (" ", " "),
}
SHIFTS = {ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT}

async def read_device(path: str, name: str) -> None:
    dev = InputDevice(path)
    dev.grab()
    buf: list[str] = []
    shift = False
    async for ev in dev.async_read_loop():
        if ev.type != ecodes.EV_KEY:
            continue
        if ev.code in SHIFTS:
            shift = ev.value != 0
        elif ev.value == 1:  # 1=down, 0=up, 2=repeat
            if ev.code == ecodes.KEY_ENTER:
                print(f"[{name}] {''.join(buf)}")
                buf.clear()
            elif ev.code in KEYMAP:
                buf.append(KEYMAP[ev.code][shift])

async def main() -> None:
    devices: dict[str, str] = {
        "dock": "/dev/input/by-id/usb-Honeywell_Scanner-event-kbd",
        "bench": "/dev/input/by-path/pci-0000:00:14.0-usb-0:2:1.0-event-kbd",
    }
    await asyncio.gather(*(read_device(p, n) for n, p in devices.items()))

asyncio.run(main())
```

**C++ equivalent:** `open()` the event node, `ioctl(fd, EVIOCGRAB, 1)`, then `read()` into `struct input_event` — or use libevdev.

**Pros**
- Works with any keyboard-type device, including plain keyboards and keypads
- No extra hardware

**Cons**
- Linux only
- Needs permissions setup and your own keycode → character decoding

---

## Option 4 — Microcontroller bridge with device prefix

A microcontroller acts as USB host for the scanner/keyboard, decodes key presses, and forwards them to the PC tagged with a device ID.

### Hardware choices

| Board | Notes |
|-------|-------|
| **ESP32-S3** | One USB OTG port: host *or* device, not both at once. Read the scanner as host, then output via the board's separate UART-to-USB bridge chip, BLE, or WiFi |
| **ESP32-P4** | Has more than one USB controller, so simultaneous host + device may be possible — verify current ESP-IDF support first |
| **RP2040 / RP2350** | Arguably the best fit: Pico-PIO-USB provides a software USB host port alongside the native device port. Ready-made boards exist (e.g. Adafruit Feather RP2040 USB Host). TinyUSB covers both sides |

### Design recommendations

- **Output framed messages over USB CDC serial, not as keyboard keystrokes**, e.g. `S1\tBARCODE\n` or one JSON object per line. Re-emitting as keystrokes brings back focus, layout, interleaving and prefix-collision problems.
- **Device identity**
  - One bridge per scanner → ID in firmware or set by DIP switches
  - One bridge + USB hub → ID from the hub port number (reported by TinyUSB host)
- **Decode on the bridge** (Shift tracking, Enter as terminator) so the PC only ever receives clean strings.

**Pros**
- Works with dumb, non-programmable devices
- Works on platforms where raw device access isn't possible (Windows kiosk apps, Android, web apps)
- Device ID tied to a physical port, so it survives swapping the scanner

**Cons**
- Extra hardware, firmware to write and maintain, another failure point
- Small added latency
- No benefit on Linux, where Option 3 already distinguishes devices

---

## Recommendation for POS development

1. Use **Option 2** (serial / HID POS mode) if the scanners support it — this is the cleanest.
2. Otherwise **Option 1** (scanner-programmed prefixes) for quick wins on any platform.
3. On Linux with keyboard-only devices, use **Option 3** (evdev).
4. Build the **Option 4** bridge only if you're stuck with keyboard-only devices on a platform you can't control.
