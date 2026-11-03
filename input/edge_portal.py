import time
import threading
import pynput

from typing import Callable
from server.reporter_receiver import DevicePosition
from utils import VoidCallable
from utils.desktop import cursor_motion_bounds, in_trigger_zone
from utils.config_manager import get_config
from utils.logger import LOGGER, LogType

EDGE_PORTAL_LOOP_INTERVAL_SEC = 1 / 1000

mouse_controller = pynput.mouse.Controller()
pause_event = threading.Event()
close_event = threading.Event()
pause_edge_toggling_event = threading.Event()
edge_portal_passing_event = threading.Event()

edge_toggling_callbacks = []
def append_edge_toggling_callback(callback: Callable):
    global edge_toggling_callbacks
    edge_toggling_callbacks.append(callback)
def call_edge_toggling_callbacks():
    # this should be called after toggled by android client
    global edge_toggling_callbacks
    for callback in edge_toggling_callbacks: callback()

def pause_edge_toggling():
    LOGGER.write(LogType.Info, "Edge toggling paused.")
    pause_edge_toggling_event.set()
def resume_edge_toggling():
    LOGGER.write(LogType.Info, "Edge toggling resumed.")
    pause_edge_toggling_event.clear()

def create_edge_portal():
    from input.controller import schedule_toggle as main_schedule_toggle

    def return_to_before_toggling():
        nonlocal cursor_pos_before_toggling
        SIDE_MARGIN = 2
        if pause_event.is_set() or pause_edge_toggling_event.is_set(): return
        if cursor_pos_before_toggling == None: return
        temp_x, temp_y = cursor_pos_before_toggling
        bounds = cursor_motion_bounds(cursor_pos_before_toggling)
        direction = get_config().device_position
        if direction == DevicePosition.RIGHT:
            temp_x -= SIDE_MARGIN
        elif direction == DevicePosition.LEFT:
            temp_x += SIDE_MARGIN
        elif direction == DevicePosition.TOP:
            temp_y += SIDE_MARGIN
        elif direction == DevicePosition.BOTTOM:
            temp_y -= SIDE_MARGIN
        mouse_controller.position = bounds.clamp((temp_x, temp_y), SIDE_MARGIN)
    append_edge_toggling_callback(return_to_before_toggling)
    cursor_pos_before_toggling = None

    while not close_event.is_set():
        temp_pos = mouse_controller.position
        if temp_pos == None:
            # since the value of `mouse_controller.position` may be None sometimes,
            # make it a check here.
            # see this issue: https://github.com/moses-palmer/pynput/issues/559
            time.sleep(EDGE_PORTAL_LOOP_INTERVAL_SEC)
            continue
        bounds = cursor_motion_bounds(temp_pos)
        config = get_config()
        if pause_event.is_set():
            if (config.edge_toggling and not pause_edge_toggling_event.is_set()
                    and in_trigger_zone(temp_pos, bounds, config.device_position, config.trigger_margin)):
                cursor_pos_before_toggling = temp_pos
                main_schedule_toggle(True)
        else:
            target = bounds.wrap(temp_pos)
            if target is not None:
                edge_portal_passing_event.set()
                mouse_controller.position = target

        time.sleep(EDGE_PORTAL_LOOP_INTERVAL_SEC)
    LOGGER.write(LogType.Info, "Edge portal closed.")

def edge_portal_thread_factory() -> tuple[
    VoidCallable, VoidCallable, VoidCallable
]:
    def start_edge_portal():
        pause_event.clear()
    def pause_edge_portal():
        pause_event.set()
    def close_edge_portal():
        close_event.set()

    close_event.clear()
    edge_portal_passing_event.clear()
    pause_event.set()
    threading.Thread(target=create_edge_portal, daemon=True).start()
    return start_edge_portal, pause_edge_portal, close_edge_portal
