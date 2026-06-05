from collections import deque

from touch_input import (
    ABS_MT_POSITION_X,
    ABS_MT_TRACKING_ID,
    ACTIVE_TRACKING_ID,
    BTN_TOUCH,
    EV_ABS,
    EV_KEY,
    EV_SYN,
    PRESSED,
    RELEASED,
    RELEASED_TRACKING_ID,
    SYN_REPORT,
    TouchMachine,
    plan_touch,
    pop_coalesced,
)

PRESS = (EV_KEY, BTN_TOUCH, PRESSED)
LIFT = (EV_KEY, BTN_TOUCH, RELEASED)
TRACK_ON = (EV_ABS, ABS_MT_TRACKING_ID, ACTIVE_TRACKING_ID)
TRACK_OFF = (EV_ABS, ABS_MT_TRACKING_ID, RELEASED_TRACKING_ID)


def test_down_from_idle_presses_and_marks_contact() -> None:
    events, contact_down = plan_touch("down", 10, 20, contact_down=False)
    assert contact_down is True
    assert PRESS in events
    assert TRACK_ON in events
    assert (EV_ABS, ABS_MT_POSITION_X, 10) in events
    assert events[-1] == (EV_SYN, SYN_REPORT, 0)


def test_down_while_already_down_releases_before_pressing() -> None:
    events, contact_down = plan_touch("down", 1, 2, contact_down=True)
    assert contact_down is True
    assert events.index(TRACK_OFF) < events.index(TRACK_ON)


def test_move_while_down_emits_position_only() -> None:
    events, contact_down = plan_touch("move", 7, 8, contact_down=True)
    assert contact_down is True
    assert (EV_ABS, ABS_MT_POSITION_X, 7) in events
    assert PRESS not in events


def test_move_without_contact_is_ignored() -> None:
    assert plan_touch("move", 5, 5, contact_down=False) == ([], False)


def test_up_while_down_releases() -> None:
    events, contact_down = plan_touch("up", 0, 0, contact_down=True)
    assert contact_down is False
    assert LIFT in events
    assert TRACK_OFF in events


def test_up_emits_final_position_before_releasing() -> None:
    events, contact_down = plan_touch("up", 33, 44, contact_down=True)
    assert contact_down is False
    assert (EV_ABS, ABS_MT_POSITION_X, 33) in events
    assert events.index((EV_ABS, ABS_MT_POSITION_X, 33)) < events.index(TRACK_OFF)


def test_release_does_not_emit_a_position() -> None:
    events, _ = plan_touch("release", 99, 99, contact_down=True)
    assert (EV_ABS, ABS_MT_POSITION_X, 99) not in events
    assert TRACK_OFF in events


def test_up_without_contact_is_ignored() -> None:
    assert plan_touch("up", 0, 0, contact_down=False) == ([], False)


def test_release_is_an_alias_for_up() -> None:
    assert plan_touch("release", 0, 0, contact_down=True)[1] is False


def test_unknown_action_defaults_to_release() -> None:
    assert plan_touch("bogus", 0, 0, contact_down=True)[1] is False
    assert plan_touch("bogus", 0, 0, contact_down=False) == ([], False)


def test_watchdog_releases_stale_contact() -> None:
    machine = TouchMachine(release_timeout=0.8)
    machine.apply("down", 3, 4, now=100.0)
    assert machine.contact_down is True
    assert machine.tick(now=100.5) == []
    release = machine.tick(now=100.9)
    assert machine.contact_down is False
    assert LIFT in release


def test_tick_is_noop_without_contact() -> None:
    machine = TouchMachine()
    assert machine.tick(now=5.0) == []


def test_keepalive_resets_watchdog_without_emitting() -> None:
    machine = TouchMachine(release_timeout=2.0)
    machine.apply("down", 1, 1, now=0.0)
    assert machine.tick(now=1.9) == []
    assert machine.apply("keepalive", 0, 0, now=1.9) == []
    assert machine.contact_down is True
    assert machine.tick(now=3.5) == []
    assert machine.contact_down is True
    assert machine.tick(now=4.0) != []
    assert machine.contact_down is False


def _press_tracking_id(events: list[tuple[int, int, int]]) -> int | None:
    for event_type, code, value in events:
        if event_type == EV_ABS and code == ABS_MT_TRACKING_ID and value != RELEASED_TRACKING_ID:
            return value
    return None


def test_each_new_contact_uses_a_fresh_increasing_tracking_id() -> None:
    machine = TouchMachine()
    first = machine.apply("down", 1, 1, now=0.0)
    machine.apply("up", 1, 1, now=0.1)
    second = machine.apply("down", 2, 2, now=0.2)
    first_id = _press_tracking_id(first)
    second_id = _press_tracking_id(second)
    assert first_id == ACTIVE_TRACKING_ID
    assert second_id == (first_id or 0) + 1


def test_max_contact_cap_releases_despite_keepalives() -> None:
    machine = TouchMachine(release_timeout=1.0, max_contact=10.0)
    machine.apply("down", 1, 1, now=0.0)
    machine.apply("keepalive", 0, 0, now=9.9)
    assert machine.tick(now=9.9) == []
    assert machine.contact_down is True
    machine.apply("keepalive", 0, 0, now=10.1)
    release = machine.tick(now=10.1)
    assert machine.contact_down is False
    assert LIFT in release


def test_activity_resets_the_watchdog() -> None:
    machine = TouchMachine(release_timeout=0.8)
    machine.apply("down", 0, 0, now=0.0)
    machine.apply("move", 1, 1, now=0.7)
    assert machine.tick(now=1.0) == []
    assert machine.contact_down is True


def test_pop_coalesced_collapses_consecutive_moves() -> None:
    commands: deque[tuple[str, int, int]] = deque(
        [("move", 1, 1), ("move", 2, 2), ("move", 3, 3), ("up", 0, 0)]
    )
    assert pop_coalesced(commands) == ("move", 3, 3)
    assert list(commands) == [("up", 0, 0)]


def test_pop_coalesced_passes_non_move_through() -> None:
    commands: deque[tuple[str, int, int]] = deque([("down", 5, 5), ("move", 1, 1)])
    assert pop_coalesced(commands) == ("down", 5, 5)
    assert list(commands) == [("move", 1, 1)]


def test_pop_coalesced_handles_single_move() -> None:
    commands: deque[tuple[str, int, int]] = deque([("move", 9, 9)])
    assert pop_coalesced(commands) == ("move", 9, 9)
    assert list(commands) == []
