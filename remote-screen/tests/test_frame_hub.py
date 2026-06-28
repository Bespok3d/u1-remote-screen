import importlib.util
import sys
import types
from pathlib import Path

# remote-screen.py is a hyphenated entry script (run as `python3 remote-screen.py`), so load it by
# path. Stub Pillow so the import succeeds without the real dep; these tests inject a fake
# framebuffer and never encode, so PIL is never called. conftest already puts files/bin on sys.path
# for the sibling gui_watchdog / touch_input imports.
if "PIL" not in sys.modules:
    pil = types.ModuleType("PIL")
    pil.Image = types.SimpleNamespace()
    sys.modules["PIL"] = pil

BIN = Path(__file__).resolve().parent.parent / "files" / "bin"
_spec = importlib.util.spec_from_file_location("remote_screen", BIN / "remote-screen.py")
remote_screen = importlib.util.module_from_spec(_spec)
sys.modules["remote_screen"] = remote_screen
_spec.loader.exec_module(remote_screen)


class FakeFramebuffer:
    """Returns scripted (etag, jpeg) snapshots; (etag, None) means unchanged since client_etag."""

    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.client_etags = []

    def get_snapshot(self, client_etag=None):
        self.client_etags.append(client_etag)
        if self.snapshots:
            return self.snapshots.pop(0)
        return ('unchanged', None)


def make_hub(framebuffer, load_per_core=0.0):
    return remote_screen.FrameHub(
        framebuffer, remote_screen.LoadPacer(), 4,
        sleep=lambda _seconds: None, load_reader=lambda _cpus: load_per_core,
    )


# ── LoadPacer (fps from system load; prioritise Klipper/printing) ──────────────────────────────

def test_loadpacer_full_fps_with_headroom():
    pacer = remote_screen.LoadPacer(active_fps=15, floor_fps=5, ease_at=0.7, floor_at=1.5)
    assert pacer.fps_for(0.1) == 15
    assert pacer.fps_for(0.7) == 15


def test_loadpacer_floor_fps_under_heavy_load():
    pacer = remote_screen.LoadPacer(active_fps=15, floor_fps=5, ease_at=0.7, floor_at=1.5)
    assert pacer.fps_for(1.5) == 5
    assert pacer.fps_for(4.0) == 5


def test_loadpacer_eases_between_headroom_and_floor():
    pacer = remote_screen.LoadPacer(active_fps=15, floor_fps=5, ease_at=0.7, floor_at=1.5)
    midpoint = pacer.fps_for(1.1)
    assert 5 < midpoint < 15


def test_loadpacer_interval_is_inverse_of_fps():
    pacer = remote_screen.LoadPacer(active_fps=15, floor_fps=5)
    assert pacer.interval(0.0) == 1.0 / 15


# ── FrameHub (one shared producer; idle-teardown; load-adaptive) ───────────────────────────────

def test_hub_publishes_a_changed_frame_at_full_fps_when_idle():
    hub = make_hub(FakeFramebuffer([('e1', b'JPEG1')]), load_per_core=0.0)
    interval = hub.produce_once()
    assert hub.wait_frame(None, timeout=0) == ('e1', b'JPEG1')
    assert interval == 1.0 / 15


def test_hub_does_not_publish_an_unchanged_frame():
    hub = make_hub(FakeFramebuffer([('e1', None)]))
    hub.produce_once()
    assert hub.wait_frame('whatever', timeout=0) == (None, None)


def test_hub_backs_off_to_floor_fps_under_load():
    hub = make_hub(FakeFramebuffer([('e1', b'J')]), load_per_core=2.0)
    assert hub.produce_once() == 1.0 / 5


def test_hub_feeds_last_etag_back_so_unchanged_frames_stay_cheap():
    framebuffer = FakeFramebuffer([('e1', b'J1'), ('e1', None)])
    hub = make_hub(framebuffer)
    hub.produce_once()
    hub.produce_once()
    assert framebuffer.client_etags == [None, 'e1']


def test_hub_counts_viewers_for_idle_teardown():
    hub = make_hub(FakeFramebuffer([]))
    assert hub._viewers == 0
    hub.subscribe()
    hub.subscribe()
    assert hub._viewers == 2
    hub.unsubscribe()
    assert hub._viewers == 1
