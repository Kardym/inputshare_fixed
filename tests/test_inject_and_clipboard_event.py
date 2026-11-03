import struct

from scrcpy_client import ControlMsgType
from scrcpy_client.android_def import AKeyCode, AKeyEventAction
from scrcpy_client.clipboard_event import DeviceMsgType, GetClipboardEvent, GetClipboardEventResponse, SetClipboardEvent
from scrcpy_client.inject_event import InjectKeyCode

def test_inject_key_code():
    data = InjectKeyCode(AKeyCode.AKEYCODE_HOME, AKeyEventAction.AKEY_EVENT_ACTION_UP).serialize()
    assert data == struct.pack(">BBIII", ControlMsgType.MSG_TYPE_INJECT_KEYCODE.value,
                               AKeyEventAction.AKEY_EVENT_ACTION_UP.value, AKeyCode.AKEYCODE_HOME.value, 0, 0)
    assert len(data) == 14

def test_get_clipboard_event():
    assert GetClipboardEvent().serialize() == bytes([ControlMsgType.MSG_TYPE_GET_CLIPBOARD.value, 1])

def test_set_clipboard_event():
    data = SetClipboardEvent("한글 text").serialize()
    text = "한글 text".encode("utf-8")
    assert data == struct.pack(">BQBI", ControlMsgType.MSG_TYPE_SET_CLIPBOARD.value, 0, 0, len(text)) + text

def _clipboard_response(text: str) -> bytes:
    encoded = text.encode("utf-8")
    return bytes([DeviceMsgType.DEVICE_MSG_TYPE_CLIPBOARD]) + struct.pack(">I", len(encoded)) + encoded

def test_clipboard_response_roundtrip():
    assert GetClipboardEventResponse.deserialize(_clipboard_response("hello 世界")) == "hello 世界"
    assert GetClipboardEventResponse.deserialize(_clipboard_response("")) == ""

def test_clipboard_response_rejects_invalid_data():
    assert GetClipboardEventResponse.deserialize(bytes([DeviceMsgType.DEVICE_MSG_TYPE_ACK_CLIPBOARD, 0, 0, 0, 0])) is None
    assert GetClipboardEventResponse.deserialize(bytes([DeviceMsgType.DEVICE_MSG_TYPE_CLIPBOARD, 0, 0])) is None
    truncated = bytes([DeviceMsgType.DEVICE_MSG_TYPE_CLIPBOARD]) + struct.pack(">I", 10) + b"abc"
    assert GetClipboardEventResponse.deserialize(truncated) is None
