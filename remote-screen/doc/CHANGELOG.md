# Changelog

## 0.1.21

- The screen now appears as a tile in Fluidd and Mainsail on its own, next to your cameras. That used
  to need a second plugin ("Printer Screen as Camera"); it is now part of Remote Screen, so installing
  Remote Screen is all it takes. You pick the name the tile shows under when you install it, and you
  can change it later from the plugin's settings.
- If you already have "Printer Screen as Camera" installed, remove it before updating. Keeping both
  would register the screen twice in Fluidd and Mainsail, so the app blocks the update until it is
  gone.

## 0.1.20

- Lighter on the printer when several people watch the screen. The framebuffer is now captured and
  encoded once and shared by every viewer, instead of each open browser tab doing its own capture,
  so two or three watchers cost about the same as one.
- The screen stream now eases its frame rate down when the printer is busy (for example mid-print)
  and runs at full rate when there is spare capacity, so mirroring never steals time from printing.
  It still uses nothing at all while no one is watching.

- Internal only (no behavior change): the connection-decision logic (including the stale-sign-in
  self-heal) was extracted into a unit-tested function, with regression tests covering the auth
  scenarios, so these fixes can't silently break in future.

## 0.1.18

- Fixes the screen failing to connect (login prompt, then a broken image) after Moonraker Login was
  turned off, when you had signed in earlier. Any leftover sign-in - stored token or stream cookie,
  including one left over from the printer's other IP address - is now fully cleared when the screen
  is open, so it connects on its own without a login or a manual cache clear. (The internal stream
  script was also renamed.)

## 0.1.15

- Fixes the screen sometimes getting stuck on "Connecting..." after an update, where only a
  manual cache clear recovered it. The page and its script are no longer cached, so a normal
  reload always loads a fresh, matching set.

## 0.1.14

- With Moonraker Login on, the screen can now authenticate with a Moonraker API key as well as a
  username and password. Put it on the screen URL as ?api_key=YOUR_KEY (handy as the slicer's
  Device UI address, so the screen opens already signed in) or paste it into the login panel.

## 0.1.13

- Fixes the screen staying on "Reconnecting..." inside OrcaSlicer (and other embedded
  webviews). The stream again renders through a native image element, which every browser and
  webview can show, instead of a streaming fetch their engines do not support. Works the same
  directly at /screen/ and as a tile in Fluidd/Mainsail. With Moonraker Login off the screen
  is freely accessible; with it on the stream stays protected, carrying your session in a
  cookie since an image request cannot send a login header.

## 0.1.12

- The screen now behaves like Fluidd with the Moonraker Login (force_logins) plugin. With login off
  it connects directly. With login on it reuses your existing web-UI session when you have one
  (seamless), and otherwise shows a login on the screen itself instead of failing or sending you
  away. The stream authenticates with the Authorization header rather than a URL token the login
  gate could not forward.

## 0.1.11

- The recovery watchdog now re-arms panel wake on every gui respawn, so a screen
  the watchdog recovered never stays dark after the next idle blank.

## 0.1.1 - 0.1.10

- Iterative touch-injection and recovery hardening: serialized single-worker
  event writes, idle and client heartbeats, a max-hold cap, and a watchdog that
  recovers the firmware gui when it spins at full CPU.

## 0.1.0

- First release. Mirrors the printer's screen in any browser with working touch.
