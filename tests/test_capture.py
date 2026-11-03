from types import SimpleNamespace
import threading

from pynput import keyboard

from input.capture import InputDispatcher, KeyCapturePolicy, MouseCapturePolicy
import input.controller as controller


def test_alt_does_not_reach_desktop_while_remote():
    policy = KeyCapturePolicy()
    for _ in range(20):
        assert policy.capture(0x104, 0xa4, True)
        assert policy.capture(0x105, 0xa4, True)


def test_local_modifier_gets_release_after_entering_remote():
    policy = KeyCapturePolicy()
    assert not policy.capture(0x104, 0xa4, False)
    assert not policy.capture(0x100, 0xa0, False)
    assert not policy.capture(0x105, 0x12, True)
    assert not policy.capture(0x101, 0x10, True)
    assert policy.capture(0x104, 0xa4, True)


def test_remote_release_does_not_open_desktop_menu_after_control_switch():
    policy = KeyCapturePolicy()
    assert policy.capture(0x104, 0xa4, True)
    assert policy.capture(0x105, 0xa4, False)
    assert not policy.capture(0x104, 0xa4, False)


def test_remote_mouse_clicks_and_wheel_are_blocked_but_motion_can_wrap():
    policy = MouseCapturePolicy()
    assert not policy.capture(0x200, 0, True)
    for down, up in ((0x201,0x202),(0x204,0x205),(0x207,0x208),(0x20b,0x20c)):
        assert policy.capture(down, 1 << 16, True)
        assert policy.capture(up, 1 << 16, True)
    assert policy.capture(0x20a, 120 << 16, True)
    assert policy.capture(0x20e, 120 << 16, True)
    assert not policy.capture(0x20a, 120 << 16, False)


def test_listener_changes_capture_without_restarting(monkeypatch, config):
    mouse = controller.CaptureMouseListener()
    keys = controller.CaptureKeyboardListener()
    monkeypatch.setattr(controller, 'is_redirecting', True)
    keys.filter_event(0x104, SimpleNamespace(vkCode=0xa4))
    assert keys.suppress
    mouse.filter_event(0x20a, SimpleNamespace(mouseData=0))
    assert mouse.suppress
    config.share_keyboard_only = True
    mouse.filter_event(0x20a, SimpleNamespace(mouseData=0))
    assert not mouse.suppress
    monkeypatch.setattr(controller, 'is_redirecting', False)
    keys.filter_event(0x100, SimpleNamespace(vkCode=65))
    assert not keys.suppress


def test_slow_gesture_work_does_not_block_hook_submission_and_drops_old_events():
    generation = SimpleNamespace(value=0)
    entered, unblock, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []
    errors = []
    dispatcher = InputDispatcher(lambda: generation.value, errors.append)
    def slow():
        entered.set()
        assert unblock.wait(2)
    try:
        dispatcher.submit(slow)
        assert entered.wait(1)
        dispatcher.submit(lambda: calls.append('stale click'))
        generation.value += 1
        dispatcher.submit(finished.set)
        unblock.set()
        assert finished.wait(2)
        assert not calls and not errors
    finally:
        unblock.set()
        dispatcher.close()


def test_toggle_clears_old_hotkey_state_so_alt_alone_cannot_toggle(monkeypatch):
    monkeypatch.setattr(controller, 'keyboard_controller', SimpleNamespace(release=lambda key: None))
    monkeypatch.setattr(controller, 'last_toggling_time', 0)
    monkeypatch.setattr(controller, 'is_redirecting', False)
    monkeypatch.setattr(controller, 'input_generation', 0)
    monkeypatch.setattr(controller, 'toggle_event', threading.Event())
    old_switch, old_exit = controller.switch_hotkey, controller.exit_hotkey
    try:
        controller.reset_hotkeys()
        for key in keyboard.HotKey.parse('<alt>+<shift>+e'):
            controller.switch_hotkey.press(key)
        assert controller.is_redirecting
        generation = controller.input_generation
        controller.switch_hotkey.press(keyboard.Key.alt)
        assert controller.is_redirecting and controller.input_generation == generation
    finally:
        controller.switch_hotkey, controller.exit_hotkey = old_switch, old_exit


def test_remote_cursor_enters_primary_mask_and_returns_to_original_monitor(monkeypatch):
    import input.edge_portal as portal
    from utils.desktop import ScreenRect
    cursor = SimpleNamespace(position=(-1000, 200))
    monkeypatch.setattr(portal, 'mouse_controller', cursor)
    monkeypatch.setattr(portal, 'screen_size', lambda: (1920, 1080))
    monkeypatch.setattr(portal, 'cursor_motion_bounds', lambda point: ScreenRect(-1920, -406, 0, 794))
    monkeypatch.setattr(portal, 'pause_event', threading.Event())
    monkeypatch.setattr(portal, 'close_event', threading.Event())
    monkeypatch.setattr(portal, 'edge_portal_passing_event', threading.Event())
    monkeypatch.setattr(portal.threading, 'Thread', lambda **kwargs: SimpleNamespace(start=lambda: None))
    start, pause, close = portal.edge_portal_thread_factory()
    start()
    assert cursor.position == (960, 540)
    assert portal.edge_portal_passing_event.is_set()
    start() # repeated start must preserve the original desktop position
    pause()
    assert cursor.position == (-1000, 200)
    close()
    assert cursor.position == (-1000, 200)
