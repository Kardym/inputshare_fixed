from types import SimpleNamespace

import pytest

import utils
import utils.desktop as desktop
from utils.desktop import ScreenRect, in_trigger_zone, monitor_for_point


def monitor(x, y, width, height, primary=False):
    return SimpleNamespace(x=x, y=y, width=width, height=height, is_primary=primary)


def test_screen_size_uses_primary_not_first_enumerated_monitor(monkeypatch):
    # Exact layout reported by the affected machine.
    monkeypatch.setattr(utils.screeninfo, 'get_monitors', lambda: [
        monitor(-1920, -406, 1920, 1200), monitor(0, 0, 1920, 1080, True), monitor(1920, 0, 1920, 1080)])
    assert utils.screen_size() == (1920, 1080)


@pytest.mark.parametrize('point,expected', [
    ((0, 500), (1917, 500)), ((1919, 500), (2, 500)),
    ((900, 0), (900, 1077)), ((900, 1079), (900, 2)),
    ((0, 0), (1917, 1077)), ((1919, 1079), (2, 2))])
def test_primary_edges_wrap_before_physical_cursor_stalls(point, expected):
    rect = ScreenRect(0, 0, 1920, 1080)
    assert rect.wrap(point) == expected
    assert rect.wrap(expected) is None # no stationary ping-pong at the opposite edge


def test_secondary_monitor_offsets_and_negative_coordinates():
    monitors = [monitor(-1920, -406, 1920, 1200), monitor(0, 0, 1920, 1080, True)]
    rect = monitor_for_point(monitors, (-900, -406))
    assert rect == ScreenRect(-1920, -406, 0, 794)
    target = rect.wrap((-900, -406))
    assert target == (-900, 791)
    assert rect.wrap(target) is None
    assert rect.wrap((-1920, 100)) == (-3, 100)


def test_nearest_monitor_handles_display_gap_and_disconnection():
    assert monitor_for_point([monitor(0, 0, 1920, 1080, True)], (-200, -200)) == ScreenRect(0, 0, 1920, 1080)


def test_live_bounds_respect_app_clip_and_update_after_switch(monkeypatch):
    if desktop.sys.platform != 'win32':
        pytest.skip('Windows cursor clipping')
    state = [ScreenRect(0, 0, 1920, 1080), ScreenRect(100, 200, 800, 600)]
    monkeypatch.setattr(desktop, '_windows_bounds', lambda point: tuple(state))
    clipped = desktop.cursor_motion_bounds((500, 599))
    assert clipped == state[1]
    assert clipped.wrap((500, 599)) == (500, 202)
    state[1] = ScreenRect(-1920, -406, 3840, 1080)
    assert desktop.cursor_motion_bounds((500, 1079)).wrap((500, 1079)) == (500, 2)
    state[0] = ScreenRect(0, 0, 2560, 1440)
    state[1] = None
    assert desktop.cursor_motion_bounds((2559, 700)).wrap((2559, 700)) == (2, 700)


def test_trigger_zone_uses_monitor_origin():
    rect = ScreenRect(-1920, -406, 0, 794)
    assert in_trigger_zone((-1920, 0), rect, 'left', 80)
    assert in_trigger_zone((-1, 0), rect, 'right', 80)
    assert in_trigger_zone((-800, -406), rect, 'top', 80)
    assert in_trigger_zone((-800, 793), rect, 'bottom', 80)
    assert not in_trigger_zone((-1920, -400), rect, 'left', 80)


def test_tiny_clip_does_not_create_warp_loop():
    assert ScreenRect(0, 0, 1, 1).wrap((0, 0)) is None
    assert ScreenRect(0, 0, 1, 1).clamp((50, 50), 2) == (0, 0)
