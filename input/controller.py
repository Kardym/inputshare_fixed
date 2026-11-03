import threading
import time
from pynput import keyboard, mouse
from typing import Callable
from input import EXIT_KEY_COMBINATION, SWITCH_KEY_COMBINATION
from input.capture import InputDispatcher, KeyCapturePolicy, MouseCapturePolicy
from scrcpy_client.clipboard_event import GetClipboardEvent, SetClipboardEvent
from scrcpy_client.hid_event import KeyEmptyEvent
from input.callbacks import KeyEventCallback,\
    MouseClickCallback, MouseMoveCallback, MouseScrollCallback,\
    SendDataCallback, SendDataAsyncCallback
from input.edge_portal import edge_portal_thread_factory
from server.scrcpy_receiver import ReceivedClipboardText
from ui.fullscreen_mask import mask_thread_factory
from utils.clipboard import Clipboard
from utils.config_manager import get_config
from utils.logger import LOGGER, LogType

is_redirecting = False
input_generation = 0
keyboard_controller = keyboard.Controller()
toggle_event = threading.Event()
exit_event = threading.Event()
main_errno: Exception | None = None

last_toggling_time  = time.perf_counter()
DEBOUNCING_DURATION = 0.25
def schedule_toggle(force: bool | None = None):
    global toggle_event, is_redirecting, last_toggling_time, input_generation
    current_time = time.perf_counter()
    if current_time - last_toggling_time < DEBOUNCING_DURATION:
        LOGGER.write(LogType.Info, "Toggling debounced."); return
    last_toggling_time = current_time

    if force is None:
        # triggered by hotkey
        keyboard_controller.release(keyboard.Key.shift)
        keyboard_controller.release(keyboard.Key.alt)
    is_redirecting = force if force is not None else not is_redirecting
    input_generation += 1
    reset_hotkeys()
    toggle_event.set()

def schedule_exit(errno: Exception | None = None):
    global main_errno, is_redirecting, input_generation
    if errno is not None:
        main_errno = errno
    is_redirecting = False
    input_generation += 1
    reset_hotkeys()
    exit_event.set()
    toggle_event.set()


def reset_hotkeys():
    global switch_hotkey, exit_hotkey
    switch_hotkey = keyboard.HotKey(keyboard.HotKey.parse(SWITCH_KEY_COMBINATION), schedule_toggle)
    exit_hotkey = keyboard.HotKey(keyboard.HotKey.parse(EXIT_KEY_COMBINATION), schedule_exit)


reset_hotkeys()


class CaptureKeyboardListener(keyboard.Listener):
    def __init__(self, **kwargs):
        self.capture_policy = KeyCapturePolicy()
        self.capture_current = False
        super().__init__(win32_event_filter=self.filter_event, **kwargs)

    def filter_event(self, msg, data):
        self.capture_current = self.capture_policy.capture(msg, data.vkCode, is_redirecting)
        return True

    @property
    def suppress(self):
        return self.capture_current


class CaptureMouseListener(mouse.Listener):
    def __init__(self, **kwargs):
        self.capture_policy = MouseCapturePolicy()
        self.capture_current = False
        super().__init__(win32_event_filter=self.filter_event, **kwargs)

    def filter_event(self, msg, data):
        capture = is_redirecting and not get_config().share_keyboard_only
        self.capture_current = self.capture_policy.capture(msg, data.mouseData, capture)
        return True

    @property
    def suppress(self):
        return self.capture_current


def keyboard_press_handler_factory(callback: KeyEventCallback, dispatch=None):
    def keyboard_press_handler(k: keyboard.Key | keyboard.KeyCode | None):
        global is_redirecting, keyboard_listener
        assert keyboard_listener is not None
        if k is None: return

        canonical_k = keyboard_listener.canonical(k)
        previous_generation = input_generation
        switch_hotkey.press(canonical_k)
        exit_hotkey.press(canonical_k)
        if previous_generation == input_generation:
            if dispatch:
                dispatch(callback, canonical_k, is_redirecting)
            else:
                callback(canonical_k, is_redirecting)
    return keyboard_press_handler

def keyboard_release_handler_factory(callback: KeyEventCallback, dispatch=None):
    def keyboard_release_handler(k: keyboard.Key | keyboard.KeyCode | None):
        global is_redirecting, keyboard_listener
        assert keyboard_listener is not None
        if k is None: return

        canonical_k = keyboard_listener.canonical(k)
        switch_hotkey.release(canonical_k)
        exit_hotkey.release(canonical_k)
        if dispatch:
            dispatch(callback, canonical_k, is_redirecting)
        else:
            callback(canonical_k, is_redirecting)
    return keyboard_release_handler

def mouse_move_handler_factory(callback: MouseMoveCallback, dispatch=None):
    def mouse_move_handler(x: int, y: int):
        global is_redirecting
        if dispatch:
            dispatch(callback, x, y, is_redirecting)
        else:
            callback(x, y, is_redirecting)
    return mouse_move_handler

def mouse_click_handler_factory(callback: MouseClickCallback, dispatch=None):
    def mouse_click_handler(x: int, y: int, button: mouse.Button, pressed: bool):
        global is_redirecting, main_errno
        if dispatch:
            dispatch(callback, x, y, button, pressed, is_redirecting)
        else:
            callback(x, y, button, pressed, is_redirecting)
    return mouse_click_handler

def mouse_scroll_handler_factory(callback: MouseScrollCallback, dispatch=None):
    def mouse_scroll_handler(x: int, y: int, dx: int, dy: int):
        global is_redirecting, main_errno
        if dispatch:
            dispatch(callback, x, y, dx, dy, is_redirecting)
        else:
            callback(x, y, dx, dy, is_redirecting)
    return mouse_scroll_handler

def main_loop(
    send_data: SendDataCallback,
    send_data_async: SendDataAsyncCallback,
    keyboard_press_callback: KeyEventCallback,
    keyboard_release_callback: KeyEventCallback,
    mouse_move_callback: MouseMoveCallback,
    mouse_click_callback: MouseClickCallback,
    mouse_scroll_callback: MouseScrollCallback,
    release_inputs: Callable[[], None],
) -> Exception | None:
    global is_redirecting, keyboard_listener, main_errno, toggle_event

    def before_toggle(is_redirecting: bool):
        if is_redirecting:
            last_received = ReceivedClipboardText.read()
            current_clipboard_content = Clipboard.safe_paste()
            if exit_event.is_set(): return
            if not get_config().sync_clipboard: return
            if current_clipboard_content is None: return
            if last_received is not None and\
               last_received == current_clipboard_content: return
            send_data_async(SetClipboardEvent(current_clipboard_content).serialize())

    def after_toggle(is_redirecting: bool):
        nonlocal show_mask, hide_mask,\
            start_edge_portal, pause_edge_portal
        if is_redirecting:
            if not get_config().share_keyboard_only:
                show_mask(); start_edge_portal()
            LOGGER.write(LogType.Info, "Input redirecting enabled.")
        else:
            dispatcher.exclusive(release_inputs)
            send_data(KeyEmptyEvent().serialize())
            hide_mask(); pause_edge_portal()
            LOGGER.write(LogType.Info, "Input redirecting disabled.")

    main_errno = send_data(GetClipboardEvent().serialize()) # start server clipboard sync
    show_mask, hide_mask, exit_mask = mask_thread_factory()
    start_edge_portal, pause_edge_portal, close_edge_portal = edge_portal_thread_factory()

    dispatcher = InputDispatcher(lambda: input_generation, schedule_exit)
    keyboard_listener = CaptureKeyboardListener(
        on_press=keyboard_press_handler_factory(keyboard_press_callback, dispatcher.submit),
        on_release=keyboard_release_handler_factory(keyboard_release_callback, dispatcher.submit),
    )
    mouse_listener = CaptureMouseListener(
        on_move=mouse_move_handler_factory(mouse_move_callback, dispatcher.submit),
        on_click=mouse_click_handler_factory(mouse_click_callback, dispatcher.submit),
        on_scroll=mouse_scroll_handler_factory(mouse_scroll_callback, dispatcher.submit),
    )
    try:
        keyboard_listener.start()
        keyboard_listener.wait()
        mouse_listener.start()
        mouse_listener.wait()
        while not exit_event.is_set() and main_errno is None:
            after_toggle(is_redirecting)
            toggle_event.wait()
            toggle_event.clear()
            before_toggle(is_redirecting)
    finally:
        keyboard_listener.stop()
        mouse_listener.stop()
        dispatcher.close()
        release_inputs()
        exit_mask()
        close_edge_portal()
    return main_errno
