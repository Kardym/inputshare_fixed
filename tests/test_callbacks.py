import threading

import pytest
from pynput import keyboard, mouse

from scrcpy_client import ControlMsgType
from scrcpy_client.android_def import AKeyCode, AKeyEventAction
from scrcpy_client.hid_def import HID_ID_KEYBOARD, HID_MouseButton, KeymodStateStore
from scrcpy_client.hid_event import KeyEvent
from scrcpy_client.inject_event import InjectKeyCode
from scrcpy_client.sdl_def import SDL_Scancode
from input.callbacks import _compute_mouse_pointer_diff, callback_context_wrapper

UHID_INPUT = ControlMsgType.MSG_TYPE_UHID_INPUT.value
INJECT_KEYCODE = ControlMsgType.MSG_TYPE_INJECT_KEYCODE.value

class FakeSocket:
    def __init__(self):
        self.lock = threading.Lock()
        self.sent: list[bytes] = []
    def sendall(self, data: bytes):
        with self.lock: self.sent.append(data)
    def keyboard_inputs(self) -> list[bytes]:
        with self.lock:
            return [d for d in self.sent if d[0] == UHID_INPUT and int.from_bytes(d[1:3], "big") == HID_ID_KEYBOARD]
    def mouse_inputs(self) -> list[bytes]:
        # skip the zero-movement keepalive events sent by the background sender thread
        with self.lock:
            return [d for d in self.sent if d[0] == UHID_INPUT and d[1:3] == b"\x00\x02" and d[5:] != bytes(4)]
    def keycodes(self) -> list[bytes]:
        with self.lock: return [d for d in self.sent if d[0] == INJECT_KEYCODE]

@pytest.fixture
def wrapped():
    sock = FakeSocket()
    (_send, _send_async, key_press, key_release,
     _mouse_move, mouse_click, _mouse_scroll) = callback_context_wrapper(sock) # type: ignore
    return sock, key_press, key_release, mouse_click

def test_mouse_pointer_diff_scaling(config):
    config.mouse_speed = 2.0
    assert _compute_mouse_pointer_diff(0, 0, 0, 0) == (0, 0)
    assert _compute_mouse_pointer_diff(1, 0, 0, 0) == (1, 0)
    assert _compute_mouse_pointer_diff(10, 0, 0, 0) == (5, 0)

def test_key_press_release_while_redirecting(wrapped):
    sock, key_press, key_release, _ = wrapped
    key_a = keyboard.KeyCode.from_char("a")
    key_press(key_a, True)
    key_release(key_a, True)
    assert sock.keyboard_inputs() == [
        KeyEvent(KeymodStateStore(), [SDL_Scancode.SDL_SCANCODE_A]).serialize(),
        KeyEvent(KeymodStateStore(), []).serialize(),
    ]

def test_key_press_not_redirecting_sends_nothing(wrapped):
    sock, key_press, key_release, _ = wrapped
    key_press(keyboard.KeyCode.from_char("a"), False)
    key_release(keyboard.KeyCode.from_char("a"), False)
    assert sock.keyboard_inputs() == []

def test_function_key_injects_android_keycode(wrapped):
    sock, key_press, key_release, _ = wrapped
    f2 = keyboard.KeyCode.from_vk(113)
    key_press(f2, True)
    key_release(f2, True)
    assert sock.keycodes() == [
        InjectKeyCode(AKeyCode.AKEYCODE_HOME, AKeyEventAction.AKEY_EVENT_ACTION_DOWN).serialize(),
        InjectKeyCode(AKeyCode.AKEYCODE_HOME, AKeyEventAction.AKEY_EVENT_ACTION_UP).serialize(),
    ]

def test_alt_up_shortcut_sends_only_first_event(wrapped):
    # characterization: `keyboard_press_callback` returns inside the shortcut loop,
    # so only the first of the two shortcut events is sent.
    sock, key_press, _, _ = wrapped
    key_press(keyboard.Key.alt_l, False)
    key_press(keyboard.KeyCode.from_vk(38), False)
    assert sock.keyboard_inputs() == [KeyEvent(KeymodStateStore(), [SDL_Scancode.SDL_SCANCODE_UP]).serialize()]

def test_mouse_click_while_redirecting(wrapped):
    sock, _, _, mouse_click = wrapped
    mouse_click(0, 0, mouse.Button.left, True, True)
    mouse_click(0, 0, mouse.Button.left, False, True)
    assert [d[5:] for d in sock.mouse_inputs()] == [bytes([HID_MouseButton.MOUSE_BUTTON_LEFT, 0, 0, 0])]

def test_mouse_side_button_injects_back(wrapped):
    sock, _, _, mouse_click = wrapped
    mouse_click(0, 0, mouse.Button.x1, True, True)
    assert sock.keycodes() == [
        InjectKeyCode(AKeyCode.AKEYCODE_BACK, AKeyEventAction.AKEY_EVENT_ACTION_DOWN).serialize(),
    ]

def test_share_keyboard_only_ignores_mouse(wrapped, config):
    config.share_keyboard_only = True
    sock, _, _, mouse_click = wrapped
    mouse_click(0, 0, mouse.Button.left, True, True)
    assert sock.mouse_inputs() == []
