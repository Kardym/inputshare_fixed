from scrcpy_client.hid_def import HID_MouseButton, HIDKeymod, KeymodStateStore, MouseButtonStateStore

def test_keymod_down_up():
    state = KeymodStateStore()
    state.keydown(HIDKeymod.HID_MOD_LEFT_CONTROL)
    state.keydown(HIDKeymod.HID_MOD_LEFT_ALT)
    assert state.has_key(HIDKeymod.HID_MOD_LEFT_ALT)
    assert not state.is_key(HIDKeymod.HID_MOD_LEFT_ALT)
    state.keyup(HIDKeymod.HID_MOD_LEFT_CONTROL)
    assert state.is_key(HIDKeymod.HID_MOD_LEFT_ALT)

def test_keymod_keyup_of_released_key_is_noop():
    state = KeymodStateStore()
    state.keyup(HIDKeymod.HID_MOD_LEFT_SHIFT)
    assert state.key == 0

def test_keymod_combined_alt_release_clears_only_pressed_bits():
    state = KeymodStateStore()
    state.keydown(HIDKeymod.HID_MOD_LEFT_ALT)
    state.keydown(HIDKeymod.HID_MOD_LEFT_SHIFT)
    state.keyup(HIDKeymod.HID_MOD_ALT)
    assert state.key == HIDKeymod.HID_MOD_LEFT_SHIFT

def test_mouse_button_down_up():
    state = MouseButtonStateStore()
    state.mouse_down(HID_MouseButton.MOUSE_BUTTON_LEFT)
    state.mouse_down(HID_MouseButton.MOUSE_BUTTON_RIGHT)
    state.mouse_up(HID_MouseButton.MOUSE_BUTTON_LEFT)
    assert state.mouse_button == HID_MouseButton.MOUSE_BUTTON_RIGHT

def test_mouse_button_up_without_down_is_noop():
    state = MouseButtonStateStore()
    state.mouse_up(HID_MouseButton.MOUSE_BUTTON_LEFT)
    assert state.mouse_button == HID_MouseButton.MOUSE_BUTTON_NONE
