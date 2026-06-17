# Remote Screen

View and control your printer's touchscreen from any web browser: desktop, tablet, or
phone. The screen is mirrored live and your taps are sent back to the printer.

## Features

- Full screen mirroring with touch control.
- Works in desktop, tablet, and phone browsers.
- Works with the Moonraker Login plugin: it reuses your web UI session, or signs you in on the screen itself.
- Installable as a Progressive Web App (PWA).

## Access

Once installed: `http://<printer-ip>/screen/`

To show it as a tile inside Fluidd and Mainsail (next to your cameras), also install
**webcam-screen**, which registers the mirror as a Moonraker `[webcam]` iframe sized for
the U1's 480x320 display.

## How it works

A lightweight framebuffer server captures the screen and forwards touch input, served
through nginx. It is low-overhead and changes nothing about the on-device UI.

## Troubleshooting

- **Screen not reachable:** confirm Fluidd/Mainsail work normally, then reload `/screen/`.
- **Screen looks frozen:** refresh the browser tab. The plugin includes a watchdog that
  recovers the on-device UI automatically if it stalls; give it a couple of seconds.
- **Dark after sitting idle:** the firmware blanks the panel when idle; a tap wakes it, and
  the watchdog re-arms wake-on-touch after a recovery.
