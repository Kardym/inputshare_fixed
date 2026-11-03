import struct
from types import SimpleNamespace

import pytest
from pynput import keyboard, mouse

import input.callbacks as callbacks
from input.pinch import PinchGestures, parse_pointer_position
from scrcpy_client.android_def import ScreenSize, ScreenPoint, ScreenPosition


def position(x=400, y=600, width=1080, height=2336):
    return ScreenPosition(ScreenSize(width, height), ScreenPoint(x, y))


def decode(messages):
    events = []
    for msg in messages:
        if msg[0] == 2:
            assert len(msg) % 32 == 0
            events.extend(struct.unpack(">BBQIIHHHII", msg[i:i + 32]) for i in range(0, len(msg), 32))
    return events


@pytest.fixture
def gesture(monkeypatch):
    sent = []
    cursor = SimpleNamespace(position=position())
    pinch = PinchGestures(sent.append, lambda: cursor.position)
    return pinch, cursor, sent


def dump_pointer(width=1080, height=2340):
    return f"""  Device 21: scrcpy
    Motion Ranges:
      X: source=MOUSE
  Device 25: scrcpy
    Motion Ranges:
      X: source=MOUSE
  Device 26: scrcpy
    Keyboard Input Mapper:
  Device 30: other mouse
    X: source=MOUSE
    Viewport INTERNAL: displayId=0, orientation=0, logicalFrame=[0, 0, {width}, {height}]
    CursorStatesByDisplay:
      LogicalDisplayId 1:
        DeviceId(25):[hoveringPointers=[Pointer(id=0, MOUSE) at (20, 30)]]
      LogicalDisplayId 0:
        DeviceId(21):[hoveringPointers=[Pointer(id=0, MOUSE) at (100, 100)]]
        DeviceId(25):[hoveringPointers=[Pointer(id=0, MOUSE) at (540, 1170)]]
        DeviceId(30):[hoveringPointers=[Pointer(id=0, MOUSE) at (10, 10)]]
    Windows:
"""


def test_parser_uses_current_scrcpy_mouse_on_default_display():
    assert parse_pointer_position(dump_pointer()) == position(540, 1168)


@pytest.mark.parametrize("width,height", [(2340, 1080), (3840, 5000)])
def test_parser_matches_scrcpy_aligned_and_scaled_size(width, height):
    result = parse_pointer_position(dump_pointer(width, height))
    assert result is not None
    assert result.size.width % 8 == result.size.height % 8 == 0
    assert max(result.size.width, result.size.height) <= 4096
    assert 0 <= result.point.x < result.size.width
    assert 0 <= result.point.y < result.size.height


def test_parser_refuses_missing_or_ambiguous_cursor():
    assert parse_pointer_position("") is None
    assert parse_pointer_position(dump_pointer().replace("MOUSE) at", "FINGER) at")) is None
    assert parse_pointer_position(dump_pointer().replace("Device 25: scrcpy", "Device 25: other").replace("Device 21: scrcpy", "Device 21: other")) is None


def test_anchor_stays_fixed_and_two_fingers_release_in_reverse_order(gesture):
    pinch, cursor, sent = gesture
    pinch.start()
    pinch.start() # repeated Alt must not add contacts
    anchor = cursor.position
    cursor.position = position(650, 700)
    pinch.click(True)
    session = pinch.session
    pinch.update(position(800, 900), session)
    pinch.stop()
    events = decode(sent)
    assert [(e[1], e[2]) for e in events] == [(0, 0), (0, 1), (2, 1), (1, 1), (1, 0)]
    assert events[0][3:5] == events[-1][3:5] == (anchor.point.x, anchor.point.y)
    assert events[0][7] == 65535
    assert events[-1][7] == events[-2][7] == 0
    assert all(e[8:] == (0, 0) for e in events)
    pinch.stop()
    assert len(decode(sent)) == 5


def test_mouse_release_keeps_anchor_and_old_worker_cannot_move_new_drag(gesture):
    pinch, cursor, sent = gesture
    pinch.start()
    pinch.click(True)
    old_session = pinch.session
    pinch.click(False)
    assert pinch.active
    pinch.click(True)
    before = len(sent)
    pinch.update(position(800, 900), old_session)
    assert len(sent) == before
    pinch.update(position(800, 900), pinch.session)
    assert len(sent) == before + 1
    pinch.stop()


@pytest.mark.parametrize("dy,expands", [(1, True), (-1, False), (100, True), (-100, False)])
def test_wheel_generates_pinch_in_both_directions(gesture, dy, expands):
    pinch, cursor, sent = gesture
    pinch.start()
    pinch.wheel(dy)
    second = [e for e in decode(sent) if e[2] == 1]
    assert [e[1] for e in second] == [0] + [2] * 6 + [1]
    anchor = cursor.position.point
    first_distance = (second[0][3] - anchor.x) ** 2 + (second[0][4] - anchor.y) ** 2
    last_distance = (second[-1][3] - anchor.x) ** 2 + (second[-1][4] - anchor.y) ** 2
    assert (last_distance > first_distance) is expands
    assert pinch.active and pinch.second is None
    assert all(0 <= e[3] < e[5] and 0 <= e[4] < e[6] for e in second)
    pinch.stop()


def test_rotation_or_lost_position_releases_contacts(gesture):
    pinch, cursor, sent = gesture
    pinch.start()
    pinch.click(True)
    pinch.update(position(width=2336, height=1080), pinch.session)
    assert not pinch.active
    assert [(e[1], e[2]) for e in decode(sent)][-2:] == [(1, 1), (1, 0)]
    cursor.position = None
    pinch.start()
    assert not pinch.active


def test_wheel_rotation_cancels_anchor(gesture):
    pinch, cursor, sent = gesture
    pinch.start()
    cursor.position = position(width=2336, height=1080)
    pinch.wheel(1)
    assert not pinch.active
    assert not decode(sent)


def test_reader_error_does_not_leave_contacts_pressed(gesture):
    pinch, cursor, sent = gesture
    pinch.start()
    def fail():
        raise TimeoutError("test timeout")
    pinch.read_position = fail
    pinch.click(True)
    assert not pinch.active
    assert not decode(sent)


def test_callback_alt_gesture_consumes_click_wheel_and_cleanup(monkeypatch):
    sent = []
    cursor = SimpleNamespace(position=position())
    instances = []
    def factory(send):
        pinch = PinchGestures(send, lambda: cursor.position)
        instances.append(pinch)
        return pinch
    monkeypatch.setattr(callbacks, "PinchGestures", factory)
    wrapped = callbacks.callback_context_wrapper(SimpleNamespace(sendall=sent.append))
    _, _, press, release, _, click, scroll, reset = wrapped
    press(keyboard.Key.alt_l, True)
    cursor.position = position(650, 700)
    click(0, 0, mouse.Button.left, True, True)
    release(keyboard.Key.alt_l, True)
    assert [(e[1], e[2]) for e in decode(sent)] == [(0, 0), (0, 1), (1, 1), (1, 0)]
    before = len(decode(sent))
    press(keyboard.Key.alt_l, True)
    scroll(0, 0, 0, 1, True)
    assert len(decode(sent)) == before + 10
    reset()
    assert not instances[0].active
    assert decode(sent)[-1][1:3] == (1, 0)


def test_pc_mode_keyboard_only_and_hotkey_shift_do_not_hold_touch(monkeypatch, config):
    sent = []
    monkeypatch.setattr(callbacks, "PinchGestures", lambda send: PinchGestures(send, position))
    _, _, press, release, _, _, _, reset = callbacks.callback_context_wrapper(SimpleNamespace(sendall=sent.append))
    press(keyboard.Key.alt_l, False)
    assert not decode(sent)
    release(keyboard.Key.alt_l, False)
    config.share_keyboard_only = True
    press(keyboard.Key.alt_l, True)
    assert not decode(sent)
    release(keyboard.Key.alt_l, True)
    config.share_keyboard_only = False
    press(keyboard.Key.alt_l, True)
    press(keyboard.Key.shift_l, True)
    assert not decode(sent)
    release(keyboard.Key.alt_l, False)
    press(keyboard.Key.alt_l, True) # Shift is still down: hotkey order is irrelevant.
    assert not decode(sent)
    reset()


def test_parser_accepts_android17_display_indentation():
    dump = dump_pointer().replace("    CursorStatesByDisplay:", "  CursorStatesByDisplay:").replace("      LogicalDisplayId", "    LogicalDisplayId")
    dump = dump.replace("    LogicalDisplayId 0:\n", "    LogicalDisplayId 0:\n      TouchedWindows:\n")
    assert parse_pointer_position(dump) == position(540, 1168)


def test_alt_alone_does_not_hold_a_long_press_or_destroy_mouse_hover(gesture):
    pinch, cursor, sent = gesture
    pinch.start()
    assert pinch.active and not pinch.touching
    assert not sent


def test_drag_does_not_require_mouse_hover_after_touch_down(gesture):
    pinch, cursor, sent = gesture
    pinch.start()
    cursor.position = position(700, 800)
    pinch.click(True)
    cursor.position = None # Android drops mouse hover state during touch.
    assert pinch.move(40, -30)
    assert pinch.second.point == ScreenPoint(740, 770)
    assert pinch.touching
    forwarded = []
    pinch.forward_mouse(b'zero movement HID', forwarded.append)
    assert forwarded == []
    pinch.click(False)
    assert not pinch.touching and pinch.active
    pinch.forward_mouse(b'ordinary mouse', forwarded.append)
    assert forwarded == [b'ordinary mouse']
    assert [(e[1], e[2]) for e in decode(sent)] == [(0, 0), (0, 1), (2, 1), (1, 1), (1, 0)]
    pinch.stop()


def test_rapid_drag_moves_clamp_to_display(gesture):
    pinch, cursor, sent = gesture
    pinch.start()
    pinch.click(True)
    pinch.move(99999, -99999)
    assert pinch.second.point == ScreenPoint(1079, 0)
    pinch.stop()


def test_hid_keepalive_cannot_interleave_between_touch_packets(gesture):
    pinch, cursor, sent = gesture
    forwarded = []
    original_send = pinch.send
    def send_with_keepalive(data):
        pinch.forward_mouse(b'keepalive', forwarded.append)
        original_send(data)
    pinch.send = send_with_keepalive
    pinch.start()
    pinch.click(True)
    pinch.move(20, 30)
    pinch.click(False)
    assert forwarded == []
    assert [(e[1], e[2]) for e in decode(sent)] == [(0, 0), (0, 1), (2, 1), (1, 1), (1, 0)]
    pinch.stop()


def test_repeated_alt_wheel_survives_missing_hover_after_first_pulse(gesture):
    pinch, cursor, sent = gesture
    pinch.start()
    pinch.wheel(1)
    cursor.position = None
    pinch.wheel(-1)
    assert pinch.active and not pinch.touching
    assert len(decode(sent)) == 20
    pinch.stop()


def test_m3_holds_two_contacts_and_moves_both_without_zoom(gesture):
    pinch, cursor, sent = gesture
    pinch.pan(True)
    first, second = pinch.anchor.point, pinch.second.point
    assert pinch.panning and pinch.touching
    assert second.x - first.x == 64 and second.y == first.y
    pinch.move(45, -25)
    assert pinch.anchor.point == ScreenPoint(first.x + 45, first.y - 25)
    assert pinch.second.point == ScreenPoint(second.x + 45, second.y - 25)
    pinch.pan(False)
    assert not pinch.active and not pinch.touching and not pinch.panning
    assert [(e[1], e[2]) for e in decode(sent)] == [(0, 0), (0, 1), (2, 0), (2, 1), (1, 1), (1, 0)]


@pytest.mark.parametrize('dx,dy', [(99999, 99999), (-99999, -99999)])
def test_m3_preserves_finger_spacing_at_display_edges(gesture, dx, dy):
    pinch, cursor, sent = gesture
    pinch.pan(True)
    pinch.move(dx, dy)
    assert pinch.second.point.x - pinch.anchor.point.x == 64
    assert pinch.second.point.y == pinch.anchor.point.y
    for pos in (pinch.anchor, pinch.second):
        assert 0 <= pos.point.x < pos.size.width
        assert 0 <= pos.point.y < pos.size.height
    pinch.pan(False)


def test_alt_release_does_not_cancel_m3_but_global_cleanup_does(gesture):
    pinch, cursor, sent = gesture
    pinch.pan(True)
    pinch.stop_alt()
    assert pinch.panning and pinch.touching
    pinch.stop()
    assert not pinch.panning and not pinch.touching
    assert [(e[1], e[2]) for e in decode(sent)][-2:] == [(1, 1), (1, 0)]


def test_callback_m3_consumes_middle_button_and_pans_both_fingers(monkeypatch):
    sent = []
    monkeypatch.setattr(callbacks, 'PinchGestures', lambda send: PinchGestures(send, position))
    _, _, _, _, move, click, _, reset = callbacks.callback_context_wrapper(SimpleNamespace(sendall=sent.append))
    click(100, 100, mouse.Button.middle, True, True)
    move(130, 120, True)
    click(130, 120, mouse.Button.left, True, True) # cannot replace an M3 gesture
    click(130, 120, mouse.Button.middle, False, True)
    events = decode(sent)
    assert [(e[1], e[2]) for e in events] == [(0, 0), (0, 1), (2, 0), (2, 1), (1, 1), (1, 0)]
    assert events[2][3] - events[0][3] == events[3][3] - events[1][3]
    assert events[2][4] - events[0][4] == events[3][4] - events[1][4]
    hid_mouse = [data for data in sent if data[0] == 13 and data[1:3] == b'\x00\x02']
    assert not any(data[5] & 4 for data in hid_mouse) # no ordinary middle-button press
    reset()


def test_m3_is_disabled_for_pc_mode_or_keyboard_only(monkeypatch, config):
    sent = []
    monkeypatch.setattr(callbacks, 'PinchGestures', lambda send: PinchGestures(send, position))
    _, _, _, _, _, click, _, reset = callbacks.callback_context_wrapper(SimpleNamespace(sendall=sent.append))
    click(0, 0, mouse.Button.middle, True, False)
    config.share_keyboard_only = True
    click(0, 0, mouse.Button.middle, True, True)
    assert not decode(sent)
    reset()
