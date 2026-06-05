#!/usr/bin/env python3

import os
import signal
import threading
import time
from collections.abc import Callable

GUI_COMM = "gui"
WATCHDOG_INTERVAL = 2.0
SPIN_CPU_FRACTION = 0.90
SPIN_TRIP_SECONDS = 6.0
STAT_UTIME_INDEX = 11
STAT_STIME_INDEX = 12
DEFAULT_SYSFS_ROOT = "/sys"
FB_BLANK_REL = "class/graphics/fb0/blank"
BACKLIGHT_ROOT_REL = "class/backlight"
PANEL_UNBLANK = "0"


def comm_of(pid: str, proc_root: str) -> str:
    try:
        with open(f"{proc_root}/{pid}/comm") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def find_process_pid(comm: str, proc_root: str = "/proc") -> int | None:
    for entry in os.listdir(proc_root):
        if entry.isdigit() and comm_of(entry, proc_root) == comm:
            return int(entry)
    return None


def read_cpu_ticks(pid: int, proc_root: str = "/proc") -> int | None:
    try:
        with open(f"{proc_root}/{pid}/stat") as handle:
            fields = handle.read().rpartition(")")[2].split()
    except OSError:
        return None
    if len(fields) <= STAT_STIME_INDEX:
        return None
    return int(fields[STAT_UTIME_INDEX]) + int(fields[STAT_STIME_INDEX])


def _list_backlight_devices(backlight_root: str) -> list[str]:
    try:
        entries = sorted(os.listdir(backlight_root))
    except OSError:
        return []
    return [
        f"{backlight_root}/{entry}"
        for entry in entries
        if os.path.isdir(f"{backlight_root}/{entry}")
    ]


def _read_max_brightness(device_root: str) -> str | None:
    try:
        with open(f"{device_root}/max_brightness") as handle:
            return handle.read().strip()
    except OSError:
        return None


def _device_wake_writes(device_root: str) -> list[tuple[str, str]]:
    writes: list[tuple[str, str]] = []
    bl_power = f"{device_root}/bl_power"
    if os.path.exists(bl_power):
        writes.append((bl_power, PANEL_UNBLANK))
    brightness = f"{device_root}/brightness"
    max_value = _read_max_brightness(device_root)
    if max_value is not None and os.path.exists(brightness):
        writes.append((brightness, max_value))
    return writes


def panel_wake_writes(sysfs_root: str = DEFAULT_SYSFS_ROOT) -> list[tuple[str, str]]:
    writes: list[tuple[str, str]] = []
    fb_blank = f"{sysfs_root}/{FB_BLANK_REL}"
    if os.path.exists(fb_blank):
        writes.append((fb_blank, PANEL_UNBLANK))
    for device_root in _list_backlight_devices(f"{sysfs_root}/{BACKLIGHT_ROOT_REL}"):
        writes.extend(_device_wake_writes(device_root))
    return writes


def apply_wake_writes(writes: list[tuple[str, str]], log: Callable[[str], None]) -> None:
    for path, value in writes:
        try:
            with open(path, "w") as handle:
                handle.write(value)
        except OSError as error:
            log(f"gui-watchdog: panel wake write failed: {path}: {error}")


class SpinDetector:
    def __init__(self, cpu_fraction: float, trip_seconds: float) -> None:
        self._cpu_fraction = cpu_fraction
        self._trip_seconds = trip_seconds
        self._busy_since: float | None = None

    def update(self, cpu_fraction: float, now: float) -> bool:
        if cpu_fraction < self._cpu_fraction:
            self._busy_since = None
            return False
        if self._busy_since is None:
            self._busy_since = now
        return (now - self._busy_since) >= self._trip_seconds

    def reset(self) -> None:
        self._busy_since = None


class GuiWatchdog:
    def __init__(
        self,
        log: Callable[[str], None],
        comm: str = GUI_COMM,
        proc_root: str = "/proc",
        sysfs_root: str = DEFAULT_SYSFS_ROOT,
    ) -> None:
        self._log = log
        self._comm = comm
        self._proc_root = proc_root
        self._sysfs_root = sysfs_root
        self._clk_tck = os.sysconf("SC_CLK_TCK")
        self._detector = SpinDetector(SPIN_CPU_FRACTION, SPIN_TRIP_SECONDS)
        self._last_pid: int | None = None
        self._last_ticks: int | None = None
        worker = threading.Thread(target=self._run, name="gui-watchdog", daemon=True)
        worker.start()

    def _run(self) -> None:
        while True:
            time.sleep(WATCHDOG_INTERVAL)
            self._check()

    def _check(self) -> None:
        pid = find_process_pid(self._comm, self._proc_root)
        ticks = read_cpu_ticks(pid, self._proc_root) if pid is not None else None
        if pid is None or ticks is None:
            self._set_baseline(None, None)
            return
        if pid != self._last_pid:
            self._rearm_panel_wake(pid)
            self._set_baseline(pid, ticks)
            return
        if self._last_ticks is None:
            self._set_baseline(pid, ticks)
            return
        fraction = (ticks - self._last_ticks) / (self._clk_tck * WATCHDOG_INTERVAL)
        self._last_ticks = ticks
        if self._detector.update(fraction, time.monotonic()):
            self._recover(pid)

    def _set_baseline(self, pid: int | None, ticks: int | None) -> None:
        self._last_pid = pid
        self._last_ticks = ticks
        self._detector.reset()

    def _rearm_panel_wake(self, pid: int) -> None:
        writes = panel_wake_writes(self._sysfs_root)
        if not writes:
            return
        self._log(
            f"gui-watchdog: rearming panel wake for gui pid {pid} "
            f"(prev {self._last_pid}); {len(writes)} sysfs writes"
        )
        apply_wake_writes(writes, self._log)

    def _recover(self, pid: int) -> None:
        self._log(
            f"gui-watchdog: pid {pid} pegged >= {SPIN_CPU_FRACTION:.0%} "
            f"for >= {SPIN_TRIP_SECONDS:.0f}s; killing to force respawn"
        )
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError as error:
            self._log(f"gui-watchdog: kill failed: {error}")
        self._set_baseline(None, None)
