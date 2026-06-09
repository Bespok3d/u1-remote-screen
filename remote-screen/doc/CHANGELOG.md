# Changelog

## 0.1.11

- The recovery watchdog now re-arms panel wake on every gui respawn, so a screen
  the watchdog recovered never stays dark after the next idle blank.

## 0.1.1 - 0.1.10

- Iterative touch-injection and recovery hardening: serialized single-worker
  event writes, idle and client heartbeats, a max-hold cap, and a watchdog that
  recovers the firmware gui when it spins at full CPU.

## 0.1.0

- First release. Mirrors the printer's screen in any browser with working touch.
