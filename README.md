# multi-input: reading several keyboards separately with evdev

Hands-on demos of **Option 3 (evdev on Linux)** from
[`multi-input-device-options.md`](multi-input-device-options.md). They were written and run on a
Raspberry Pi 3 Model B with two USB keyboards (a cheap "SEM USB Keyboard" behind a USB hub and
an Ergodox EZ). The same approach works for barcode scanners and keypads, since they show up as
keyboards too.

| Script | What it shows |
|---|---|
| `00_list_keyboards.py` | Every input device, which ones are real keyboards, and their `by-id` / `by-path` names |
| `01_mixed.py` | The "standard" behaviour: all keyboards merged into one text stream, so you can't tell who typed what |
| `02_callbacks.py` | Plain synchronous code (`selectors` loop + callbacks, no asyncio). Each line is labelled with the keyboard it came from |
| `03_asyncio.py` | The asyncio version from the doc: one task per keyboard, devices chosen **by USB port** |
| `kbd_common.py` | Shared helpers: keyboard detection, port labels, keycode → character decoding |

## Setup

```bash
git clone https://github.com/tazard/multi-input.git
cd multi-input
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # or: sudo apt install python3-evdev

# Your user needs read access to /dev/input/event*. On Raspberry Pi OS the
# default user is usually in the 'input' group already. Check with:
id | grep -o input || sudo usermod -aG input "$USER"   # then log out and back in
```

## Why this works over SSH

When you SSH in, your terminal's stdin is a pseudo-terminal fed by your *laptop's* keyboard.
Keyboards plugged into the Pi never reach it. They go to the kernel input layer, which hands
keystrokes to whatever is in front of the Pi: the text console (`tty1`) or the desktop session.

evdev skips that path entirely. It opens `/dev/input/eventN`, the per-device node the kernel
creates for each keyboard, and reads raw key events. It doesn't matter where you're logged in
or which window has focus. Run the scripts in your SSH session and type on the Pi's keyboards.

> **`--grab` matters.** Without it, the keys you press *also* go to the Pi's console/desktop. If
> a shell is logged in on `tty1`, you'd be typing into it. With `--grab` (`EVIOCGRAB`), this
> process gets the events exclusively until it exits. While grabbed, Ctrl+C on the Pi keyboard
> does nothing, so quit from your SSH terminal.

## 1. Everything mixed: `01_mixed.py`

```bash
.venv/bin/python 01_mixed.py --grab
```

This reads both keyboards with `select()` and runs every event through **one shared decoder**, the
same way the OS merges keyboards. Type `hello` on one and `world` on the other at the same time
and you'll see something like `hwoerllldo`. Shift held on keyboard A also capitalises keyboard B.
This is the problem with keyboard-emulating scanners on a normal desktop app.

## 2. Synchronous with callbacks: `02_callbacks.py`

```bash
.venv/bin/python 02_callbacks.py --grab          # one line per Enter
.venv/bin/python 02_callbacks.py --grab --keys   # also every keypress
```

```
Listening on:
  /dev/input/event2  SEM USB Keyboard @ usb-0:1.5.1
  /dev/input/event5  ZSA Technology Labs Ergodox EZ @ usb-0:1.2

07:41:02  [SEM USB Keyboard @ usb-0:1.5.1]  'hello'
07:41:03  [ZSA Technology Labs Ergodox EZ @ usb-0:1.2]  'world'
```

`KeyboardHub` registers each `InputDevice` with a `selectors.DefaultSelector`. Each registration
stores the device's label and **its own `KeyDecoder`**, so Shift and half-typed buffers never leak
between devices. You register plain functions:

```python
hub = KeyboardHub(find_keyboards(), grab=True)

@hub.on_line
def handle(keyboard: str, text: str) -> None:
    print(keyboard, text)

hub.run()   # blocks; dispatches callbacks on this thread
```

This fits apps that already have a blocking main loop, or that would hand the loop to a thread
and post the callbacks into a GUI / queue.

## 3. asyncio: `03_asyncio.py`

```bash
.venv/bin/python 03_asyncio.py --grab
```

```
Listening on:
  /dev/input/by-path/platform-3f980000.usb-usb-0:1.2:1.0-event-kbd  station-A (Pi port 1.2) | ZSA Technology Labs Ergodox EZ
  /dev/input/by-path/platform-3f980000.usb-usb-0:1.5.1:1.0-event-kbd  station-B (hub on 1.5, port 1) | SEM USB Keyboard

[station-A (Pi port 1.2) | ZSA Technology Labs Ergodox EZ] 'hello'
[station-B (hub on 1.5, port 1) | SEM USB Keyboard] 'world'
```

This is the doc's example, extended. Each device gets a task running `async_read_loop()`, and
finished lines go onto one `asyncio.Queue` that a single consumer processes. The devices are
named in a `STATIONS` dict keyed by **`/dev/input/by-path`**, which is explained in the next
section. Any keyboard not listed there still gets read and is labelled `unassigned`. Unplugging a
device ends its task cleanly.

## Identifying devices: `eventN` vs `by-id` vs `by-path`

Run `00_list_keyboards.py`. On this Pi it shows:

```
KEYBOARD  /dev/input/event2  SEM USB Keyboard
          by-id:   /dev/input/by-id/usb-SEM_USB_Keyboard-event-kbd
          by-path: /dev/input/by-path/platform-3f980000.usb-usb-0:1.5.1:1.0-event-kbd

KEYBOARD  /dev/input/event5  ZSA Technology Labs Ergodox EZ
          by-id:   /dev/input/by-id/usb-ZSA_Technology_Labs_Ergodox_EZ_B4laW_v6bzKn-event-kbd
          by-path: /dev/input/by-path/platform-3f980000.usb-usb-0:1.2:1.0-event-kbd
```

There are three ways to name the same device:

- **`/dev/input/eventN`**: assigned in detection order. It changes across reboots and replugs.
  Don't hard-code it.
- **`/dev/input/by-id/…`**: built from the USB vendor, product, and **serial number**. It
  follows the *device* wherever it's plugged in. The Ergodox has a serial (`B4laW_v6bzKn`), so
  its id is unique. The SEM keyboard has **no serial**, which is common for cheap keyboards and
  scanners. Two identical units would get the *same* by-id name, and the symlink would point at
  only one of them. In that case, by-id can't tell them apart.
- **`/dev/input/by-path/…`**: built from the **physical USB port** the device is plugged into.
  Two identical, serial-less scanners get different paths because they sit in different sockets.
  The path follows the *socket*, not the device. Swap a broken scanner for a new one in the
  same socket and your code still knows which till/station it belongs to. **For identical
  devices, by-path is often the only option.**

### Reading a by-path name

```
platform-3f980000.usb - usb-0:1.5.1 : 1.0 - event-kbd
└─ USB controller ──┘   │    │       │      └─ node type (kbd = main keyboard interface)
                        │    │       └─ USB configuration.interface (1.0 = first interface)
                        │    └─ port chain: 1 → 5 → 1
                        └─ bus number
```

Here's the port chain on this Pi 3 (from `lsusb -t`):

```
root hub
└─ port 1: on-board SMSC LAN9514 hub (provides Ethernet + the 4 USB sockets)
   ├─ port 1: Ethernet
   ├─ port 2: Ergodox EZ                     → usb-0:1.2
   ├─ port 3: CH340 serial adapter
   └─ port 5: external 4-port hub
      └─ port 1: SEM USB Keyboard            → usb-0:1.5.1
```

Each hub adds one `.N` to the chain. Notes:

- **Which socket is which number?** Plug a device into each socket in turn and re-run
  `00_list_keyboards.py`, then write the mapping down or label the sockets.
- **The same hub port gives the same path**, so if you use an external hub, always use the same
  hub in the same upstream socket. Moving the hub changes every path beneath it.
- **Paths differ between boards.** A Pi 4/5 or a PC has a different controller prefix and
  topology, so recapture the paths on the target hardware.
- A single physical keyboard exposes several nodes: the main `-event-kbd` (interface `1.0`) plus
  "Consumer Control" (media keys), "System Control" (power/sleep), and sometimes a mouse.
  `kbd_common.is_keyboard()` keeps only nodes that can type letters, so the others don't show up
  as extra "keyboards".

### Optional: give ports your own names with udev

Instead of pasting long by-path strings into code, you can have udev create a friendly symlink
for a port. Create `/etc/udev/rules.d/99-stations.rules`:

```
SUBSYSTEM=="input", KERNEL=="event*", ENV{ID_PATH}=="platform-3f980000.usb-usb-0:1.2:1.0", SYMLINK+="input/station-a"
SUBSYSTEM=="input", KERNEL=="event*", ENV{ID_PATH}=="platform-3f980000.usb-usb-0:1.5.1:1.0", SYMLINK+="input/station-b"
```

Then `sudo udevadm control --reload && sudo udevadm trigger` and open `/dev/input/station-a`.
Find a device's `ID_PATH` with `udevadm info -q property /dev/input/event2 | grep ID_PATH`. You
can match `ENV{ID_SERIAL}` instead if you want to follow the device rather than the port.

## Limitations (same as in the doc)

- Keycodes are positional. `kbd_common.KEYMAP` assumes a **US layout**, and the scanner must be
  configured for US layout to match.
- Linux only. You need the `input` group or a udev rule.
- Hotplug: these scripts handle *unplug*, but a device plugged in after start-up isn't picked
  up. For that, watch for new devices with `pyudev` and start a reader per device.
