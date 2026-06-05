from pathlib import Path

from gui_watchdog import (
    SpinDetector,
    apply_wake_writes,
    find_process_pid,
    panel_wake_writes,
    read_cpu_ticks,
)


def test_spin_detector_trips_after_sustained_load() -> None:
    detector = SpinDetector(cpu_fraction=0.9, trip_seconds=6.0)
    assert not detector.update(0.95, now=0.0)
    assert not detector.update(0.95, now=4.0)
    assert detector.update(0.95, now=6.0)


def test_spin_detector_resets_when_load_drops() -> None:
    detector = SpinDetector(cpu_fraction=0.9, trip_seconds=6.0)
    detector.update(0.95, now=0.0)
    assert not detector.update(0.2, now=2.0)
    assert not detector.update(0.95, now=3.0)
    assert not detector.update(0.95, now=8.0)
    assert detector.update(0.95, now=9.1)


def test_read_cpu_ticks_handles_comm_with_parens(tmp_path: Path) -> None:
    utime = 500
    stime = 250
    (tmp_path / "100").mkdir()
    stat = f"100 (g(u)i) R 1 1 1 0 -1 0 0 0 0 0 {utime} {stime} 0 0"
    (tmp_path / "100" / "stat").write_text(stat)
    assert read_cpu_ticks(100, str(tmp_path)) == utime + stime


def test_find_process_pid(tmp_path: Path) -> None:
    target_pid = 20
    for pid, comm in [("10", "init"), (str(target_pid), "gui"), ("30", "klippy")]:
        (tmp_path / pid).mkdir()
        (tmp_path / pid / "comm").write_text(f"{comm}\n")
    (tmp_path / "notapid").mkdir()
    assert find_process_pid("gui", str(tmp_path)) == target_pid
    assert find_process_pid("absent", str(tmp_path)) is None


def _make_backlight(sysfs_root: Path, name: str, max_brightness: str | None) -> Path:
    device_root = sysfs_root / "class" / "backlight" / name
    device_root.mkdir(parents=True)
    (device_root / "bl_power").write_text("4")
    (device_root / "brightness").write_text("0")
    if max_brightness is not None:
        (device_root / "max_brightness").write_text(max_brightness)
    return device_root


def test_panel_wake_writes_lists_fb_blank_and_backlights(tmp_path: Path) -> None:
    fb_blank = tmp_path / "class" / "graphics" / "fb0" / "blank"
    fb_blank.parent.mkdir(parents=True)
    fb_blank.write_text("4")
    panel_bl = _make_backlight(tmp_path, "panel-backlight", "255")
    writes = panel_wake_writes(str(tmp_path))
    assert (str(fb_blank), "0") in writes
    assert (str(panel_bl / "bl_power"), "0") in writes
    assert (str(panel_bl / "brightness"), "255") in writes


def test_panel_wake_writes_handles_multiple_backlights(tmp_path: Path) -> None:
    first = _make_backlight(tmp_path, "a-panel", "100")
    second = _make_backlight(tmp_path, "b-panel", "255")
    writes = panel_wake_writes(str(tmp_path))
    brightness_targets = {path: value for path, value in writes if path.endswith("/brightness")}
    assert brightness_targets[str(first / "brightness")] == "100"
    assert brightness_targets[str(second / "brightness")] == "255"


def test_panel_wake_writes_skips_brightness_without_max(tmp_path: Path) -> None:
    panel_bl = _make_backlight(tmp_path, "panel-backlight", max_brightness=None)
    writes = panel_wake_writes(str(tmp_path))
    assert (str(panel_bl / "bl_power"), "0") in writes
    assert not any(path == str(panel_bl / "brightness") for path, _ in writes)


def test_panel_wake_writes_empty_when_no_sysfs(tmp_path: Path) -> None:
    assert panel_wake_writes(str(tmp_path)) == []


def test_apply_wake_writes_writes_values_and_logs_failures(tmp_path: Path) -> None:
    writable = tmp_path / "bl_power"
    writable.write_text("4")
    unreachable = tmp_path / "missing-parent" / "bl_power"
    logs: list[str] = []
    apply_wake_writes([(str(writable), "0"), (str(unreachable), "0")], logs.append)
    assert writable.read_text() == "0"
    assert any("panel wake write failed" in line for line in logs)
