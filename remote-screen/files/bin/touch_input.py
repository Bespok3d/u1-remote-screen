#!/usr/bin/env python3

import fcntl
import os
import struct
import threading
import time
from collections import deque
from collections.abc import Callable

EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03
SYN_REPORT = 0x00
BTN_TOUCH = 0x14A
ABS_X = 0x00
ABS_Y = 0x01
ABS_MT_SLOT = 0x2F
ABS_MT_TRACKING_ID = 0x39
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36

PRIMARY_SLOT = 0
ACTIVE_TRACKING_ID = 1
RELEASED_TRACKING_ID = -1
MAX_TRACKING_ID = 0xFFFF
PRESSED = 1
RELEASED = 0

EVENT_STRUCT = "llHHi"
ABS_INFO_STRUCT = "iiiii"
ABS_INFO_SIZE = 24
ABS_INFO_VALUE_BYTES = 20
ABS_INFO_MAX_INDEX = 2
EVIOCGABS_BASE = 0x80184540
MICROSECONDS = 1_000_000

DEFAULT_RELEASE_TIMEOUT = 1.0
MAX_CONTACT_SECONDS = 10.0
TAP_HOLD_SECONDS = 0.05

InputEvent = tuple[int, int, int]
Command = tuple[str, int, int]


def _press_events(touch_x: int, touch_y: int, tracking_id: int) -> list[InputEvent]:
    return [
        (EV_ABS, ABS_MT_SLOT, PRIMARY_SLOT),
        (EV_ABS, ABS_MT_TRACKING_ID, tracking_id),
        (EV_ABS, ABS_MT_POSITION_X, touch_x),
        (EV_ABS, ABS_MT_POSITION_Y, touch_y),
        (EV_KEY, BTN_TOUCH, PRESSED),
        (EV_SYN, SYN_REPORT, 0),
    ]


def _drag_events(touch_x: int, touch_y: int) -> list[InputEvent]:
    return [
        (EV_ABS, ABS_MT_POSITION_X, touch_x),
        (EV_ABS, ABS_MT_POSITION_Y, touch_y),
        (EV_SYN, SYN_REPORT, 0),
    ]


def _release_events() -> list[InputEvent]:
    return [
        (EV_ABS, ABS_MT_SLOT, PRIMARY_SLOT),
        (EV_ABS, ABS_MT_TRACKING_ID, RELEASED_TRACKING_ID),
        (EV_KEY, BTN_TOUCH, RELEASED),
        (EV_SYN, SYN_REPORT, 0),
    ]


def _plan_down(
    touch_x: int, touch_y: int, contact_down: bool, tracking_id: int
) -> tuple[list[InputEvent], bool]:
    prefix = _release_events() if contact_down else []
    return prefix + _press_events(touch_x, touch_y, tracking_id), True


def _plan_move(
    touch_x: int, touch_y: int, contact_down: bool, _tracking_id: int
) -> tuple[list[InputEvent], bool]:
    if not contact_down:
        return [], False
    return _drag_events(touch_x, touch_y), True


def _plan_release(
    touch_x: int, touch_y: int, contact_down: bool, _tracking_id: int
) -> tuple[list[InputEvent], bool]:
    if not contact_down:
        return [], False
    return _release_events(), False


def _plan_up(
    touch_x: int, touch_y: int, contact_down: bool, _tracking_id: int
) -> tuple[list[InputEvent], bool]:
    if not contact_down:
        return [], False
    return _drag_events(touch_x, touch_y) + _release_events(), False


def _plan_keepalive(
    touch_x: int, touch_y: int, contact_down: bool, _tracking_id: int
) -> tuple[list[InputEvent], bool]:
    return [], contact_down


_Planner = Callable[[int, int, bool, int], tuple[list[InputEvent], bool]]

_PLANNERS: dict[str, _Planner] = {
    "down": _plan_down,
    "move": _plan_move,
    "up": _plan_up,
    "release": _plan_release,
    "keepalive": _plan_keepalive,
}


def plan_touch(
    action: str,
    touch_x: int,
    touch_y: int,
    contact_down: bool,
    tracking_id: int = ACTIVE_TRACKING_ID,
) -> tuple[list[InputEvent], bool]:
    planner = _PLANNERS.get(action, _plan_release)
    return planner(touch_x, touch_y, contact_down, tracking_id)


def pop_coalesced(commands: deque[Command]) -> Command:
    command = commands.popleft()
    if command[0] != "move":
        return command
    while commands and commands[0][0] == "move":
        command = commands.popleft()
    return command


class TouchMachine:
    def __init__(
        self,
        release_timeout: float = DEFAULT_RELEASE_TIMEOUT,
        max_contact: float = MAX_CONTACT_SECONDS,
    ) -> None:
        self._release_timeout = release_timeout
        self._max_contact = max_contact
        self._contact_down = False
        self._last_activity = 0.0
        self._contact_started = 0.0
        self._tracking_id = 0

    @property
    def contact_down(self) -> bool:
        return self._contact_down

    @property
    def tracking_id(self) -> int:
        return self._tracking_id

    def apply(self, action: str, touch_x: int, touch_y: int, now: float) -> list[InputEvent]:
        was_down = self._contact_down
        if action == "down":
            self._tracking_id = self._tracking_id % MAX_TRACKING_ID + 1
        events, self._contact_down = plan_touch(
            action, touch_x, touch_y, self._contact_down, self._tracking_id
        )
        self._last_activity = now
        if self._contact_down and not was_down:
            self._contact_started = now
        return events

    def tick(self, now: float) -> list[InputEvent]:
        if not self._contact_down:
            return []
        idle = (now - self._last_activity) >= self._release_timeout
        held_too_long = (now - self._contact_started) >= self._max_contact
        if not idle and not held_too_long:
            return []
        events, self._contact_down = plan_touch("release", 0, 0, self._contact_down)
        return events

    def remaining(self, now: float) -> float:
        return max(0.0, self._release_timeout - (now - self._last_activity))


class EvdevWriter:
    def __init__(
        self, device: str, fb_width: int, fb_height: int, log: Callable[[str], None]
    ) -> None:
        self._fb_width = fb_width
        self._fb_height = fb_height
        self._touch_max_x = fb_width
        self._touch_max_y = fb_height
        self._log = log
        self._fd = self._open(device)
        self._touch_max_x = self._axis_max([ABS_MT_POSITION_X, ABS_X], fb_width)
        self._touch_max_y = self._axis_max([ABS_MT_POSITION_Y, ABS_Y], fb_height)
        self._log(f"Touch range: {self._touch_max_x}x{self._touch_max_y}")

    def _open(self, device: str) -> int | None:
        try:
            return os.open(device, os.O_WRONLY)
        except OSError as error:
            self._log(f"Failed to open touch device {device}: {error}")
            return None

    def _axis_max(self, axes: list[int], fallback: int) -> int:
        for axis in axes:
            value = self._query_axis(axis)
            if value is not None:
                return value
        return fallback

    def _query_axis(self, axis: int) -> int | None:
        if self._fd is None:
            return None
        buffer = bytearray(ABS_INFO_SIZE)
        try:
            fcntl.ioctl(self._fd, EVIOCGABS_BASE + axis, buffer)
        except OSError:
            return None
        fields = struct.unpack(ABS_INFO_STRUCT, bytes(buffer[:ABS_INFO_VALUE_BYTES]))
        return int(fields[ABS_INFO_MAX_INDEX])

    def scale(self, x: int, y: int) -> tuple[int, int]:
        touch_x = int(x * self._touch_max_x / self._fb_width)
        touch_y = int(y * self._touch_max_y / self._fb_height)
        return touch_x, touch_y

    def emit(self, events: list[InputEvent]) -> None:
        fd = self._fd
        if fd is None:
            return
        for event_type, code, value in events:
            os.write(fd, self._pack(event_type, code, value))

    @staticmethod
    def _pack(event_type: int, code: int, value: int) -> bytes:
        now = time.time()
        seconds = int(now)
        microseconds = int((now - seconds) * MICROSECONDS)
        return struct.pack(EVENT_STRUCT, seconds, microseconds, event_type, code, value)

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


class TouchController:
    def __init__(
        self,
        emit: Callable[[list[InputEvent]], None],
        scale: Callable[[int, int], tuple[int, int]],
        trace: Callable[[str], None] | None = None,
    ) -> None:
        self._emit = emit
        self._scale = scale
        self._trace_fn = trace
        self._tap_hold = TAP_HOLD_SECONDS
        self._machine = TouchMachine()
        self._commands: deque[Command] = deque()
        self._condition = threading.Condition()
        self._last_trace = 0.0
        self._last_scaled = (0, 0)
        worker = threading.Thread(target=self._run, name="touch-worker", daemon=True)
        worker.start()

    def submit(self, action: str, x: int, y: int) -> None:
        with self._condition:
            self._commands.append((action, x, y))
            self._condition.notify()

    def _run(self) -> None:
        while True:
            command = self._next_command()
            if command is not None:
                self._dispatch(command)
            self._enforce_cap(time.monotonic())

    def _enforce_cap(self, now: float) -> None:
        released = self._machine.tick(now)
        if not released:
            return
        self._emit(released)
        if self._trace_fn is not None:
            self._trace_fn(f"{time.time():.3f} mono={now:.4f} a=auto-release ev={len(released)}")

    def _next_command(self) -> Command | None:
        with self._condition:
            if not self._commands:
                self._condition.wait(self._wait_timeout())
            if not self._commands:
                return None
            return pop_coalesced(self._commands)

    def _wait_timeout(self) -> float | None:
        if not self._machine.contact_down:
            return None
        return self._machine.remaining(time.monotonic())

    def _dispatch(self, command: Command) -> None:
        action, x, y = command
        if action == "tap":
            self._emit_action("down", x, y)
            time.sleep(self._tap_hold)
            self._emit_action("up", x, y)
            return
        self._emit_action(action, x, y)

    def _emit_action(self, action: str, x: int, y: int) -> None:
        scaled = self._scale(x, y)
        now = time.monotonic()
        events = self._machine.apply(action, scaled[0], scaled[1], now)
        self._emit(events)
        self._trace(action, (x, y), scaled, now, len(events))

    def _trace(
        self, action: str, raw: tuple[int, int], scaled: tuple[int, int], now: float, count: int
    ) -> None:
        if self._trace_fn is None:
            return
        delta = now - self._last_trace
        moved_x = scaled[0] - self._last_scaled[0]
        moved_y = scaled[1] - self._last_scaled[1]
        self._last_trace = now
        self._last_scaled = scaled
        self._trace_fn(
            f"{time.time():.3f} mono={now:.4f} dt={delta:.4f} a={action} "
            f"raw={raw[0]},{raw[1]} scaled={scaled[0]},{scaled[1]} d={moved_x},{moved_y} "
            f"down={int(self._machine.contact_down)} tid={self._machine.tracking_id} ev={count}"
        )
