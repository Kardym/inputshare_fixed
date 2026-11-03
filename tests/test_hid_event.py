import struct

from scrcpy_client import ControlMsgType
from scrcpy_client.hid_def import HID_ID_KEYBOARD, HID_ID_MOUSE, HID_KEYBOARD_REPORT_DESC, HID_MOUSE_REPORT_DESC,\
    HID_MouseButton, HIDKeymod, KeymodStateStore, MouseButtonStateStore
from scrcpy_client.hid_event import HIDKeyboardInitEvent, HIDMouseInitEvent, KeyEmptyEvent, KeyEvent,\
    MouseClickEvent, MouseMoveEvent, MouseScrollEvent
from scrcpy_client.sdl_def import SDL_Scancode

UHID_CREATE = ControlMsgType.MSG_TYPE_UHID_CREATE.value
UHID_INPUT = ControlMsgType.MSG_TYPE_UHID_INPUT.value

def test_control_msg_type_values():
    # these values must match the scrcpy-server 2.7 protocol
    assert ControlMsgType.MSG_TYPE_INJECT_KEYCODE.value == 0
    assert ControlMsgType.MSG_TYPE_GET_CLIPBOARD.value == 8
    assert ControlMsgType.MSG_TYPE_SET_CLIPBOARD.value == 9
    assert UHID_CREATE == 12
    assert UHID_INPUT == 13

def test_keyboard_init_event():
    data = HIDKeyboardInitEvent().serialize()
    header = struct.pack(">BHBH", UHID_CREATE, HID_ID_KEYBOARD, 0, len(HID_KEYBOARD_REPORT_DESC))
    assert data == header + HID_KEYBOARD_REPORT_DESC

def test_mouse_init_event():
    data = HIDMouseInitEvent().serialize()
    header = struct.pack(">BHBH", UHID_CREATE, HID_ID_MOUSE, 0, len(HID_MOUSE_REPORT_DESC))
    assert data == header + HID_MOUSE_REPORT_DESC

def test_key_event_layout():
    keymod = KeymodStateStore()
    keymod.keydown(HIDKeymod.HID_MOD_LEFT_SHIFT)
    data = KeyEvent(keymod, [SDL_Scancode.SDL_SCANCODE_A, SDL_Scancode.SDL_SCANCODE_B]).serialize()
    assert data[:5] == struct.pack(">BHH", UHID_INPUT, HID_ID_KEYBOARD, 8)
    assert data[5:] == bytes([HIDKeymod.HID_MOD_LEFT_SHIFT, 0,
                              SDL_Scancode.SDL_SCANCODE_A.value, SDL_Scancode.SDL_SCANCODE_B.value, 0, 0, 0, 0])

def test_key_empty_event():
    data = KeyEmptyEvent().serialize()
    assert data == struct.pack(">BHH", UHID_INPUT, HID_ID_KEYBOARD, 8) + bytes(8)

def test_mouse_move_event_clamps_and_encodes_twos_complement():
    buttons = MouseButtonStateStore()
    buttons.mouse_down(HID_MouseButton.MOUSE_BUTTON_LEFT)
    data = MouseMoveEvent(500, -500, buttons).serialize()
    assert data[:5] == struct.pack(">BHH", UHID_INPUT, HID_ID_MOUSE, 4)
    assert data[5:] == bytes([HID_MouseButton.MOUSE_BUTTON_LEFT, 127, (-127) % 256, 0])

def test_mouse_click_event():
    buttons = MouseButtonStateStore()
    buttons.mouse_down(HID_MouseButton.MOUSE_BUTTON_RIGHT)
    assert MouseClickEvent(buttons).serialize()[5:] == bytes([HID_MouseButton.MOUSE_BUTTON_RIGHT, 0, 0, 0])

def test_mouse_scroll_event():
    assert MouseScrollEvent(-1).serialize()[5:] == bytes([0, 0, 0, 255])
    assert MouseScrollEvent(300).serialize()[5:] == bytes([0, 0, 0, 127])
