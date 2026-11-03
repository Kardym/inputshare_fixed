"""Two real touchscreen contacts, anchored at the Android mouse cursor."""
import math
import re
import threading
import time
from typing import Callable

from scrcpy_client.android_def import AMotionEventAction, AMotionEventButtons, ScreenPoint, ScreenPosition, ScreenSize
from scrcpy_client.inject_event import InjectTouchEvent
from utils.adb_controller import get_adb_device
from utils.logger import LOGGER, LogType


def parse_pointer_position(dump: str) -> ScreenPosition | None:
    # Read the default display only; PC coordinates and Android acceleration differ.
    viewport = re.search(r'Viewport INTERNAL: displayId=0,[^\n]*logicalFrame=\[0, 0, (\d+), (\d+)\]', dump)
    if viewport is None:
        return None
    width, height = map(int, viewport.groups())
    if min(width, height) < 8:
        return None
    mouse_ids = set()
    for device in re.finditer(r'^  Device (\d+): scrcpy\s*\n(.*?)(?=^  Device |\Z)', dump, re.M | re.S):
        if 'source=MOUSE' in device[2]:
            mouse_ids.add(int(device[1]))
    header = re.search(r'(?m)^([ \t]*)CursorStatesByDisplay:[ \t]*\n', dump)
    if header is None:
        return None
    cursors = re.split(r'\n' + re.escape(header[1]) + r'\S', dump[header.end():], maxsplit=1)[0]
    display = re.search(r'LogicalDisplayId 0:(.*?)(?=LogicalDisplayId \d+:|\Z)', cursors, re.S)
    if display is None:
        return None
    positions = {}
    for match in re.finditer(r'DeviceId\((\d+)\):[^\n]*?MOUSE\) at \(([-\d.]+), ([-\d.]+)\)', display[1]):
        if int(match[1]) in mouse_ids:
            positions[int(match[1])] = (float(match[2]), float(match[3]))
    if not positions:
        return None
    x, y = positions[max(positions)]
    # scrcpy 2.7 rounds its control coordinate space down to multiples of 8,
    # including with video=false, and this application uses max_size=4096.
    w, h = width & ~7, height & ~7
    if max(w, h) > 4096:
        if h > w:
            w, h = ((w * 4096 // h + 4) & ~7), 4096
        else:
            w, h = 4096, ((h * 4096 // w + 4) & ~7)
    point = ScreenPoint(max(0, min(w - 1, round(x * w / width))),
                        max(0, min(h - 1, round(y * h / height))))
    return ScreenPosition(ScreenSize(w, h), point)


def read_pointer_position(device=None) -> ScreenPosition | None:
    if device is None:
        device = get_adb_device()
    if isinstance(device, Exception):
        return None
    dump = device.shell('dumpsys input', timeout=1)
    return parse_pointer_position(dump) if isinstance(dump, str) else None


class PinchGestures:
    ANCHOR_ID = 0
    MOVING_ID = 1

    def __init__(self, send: Callable[[bytes], None], read_position=None):
        self.send = send
        # Cache the selected device per connection; do not log device selection on every poll.
        device = None
        def read_selected_pointer():
            nonlocal device
            if device is None:
                candidate = get_adb_device()
                if isinstance(candidate, Exception):
                    return None
                device = candidate
            return read_pointer_position(device)
        self.read_position = read_position or read_selected_pointer
        self.lock = threading.RLock()
        self.anchor: ScreenPosition | None = None
        self.second: ScreenPosition | None = None
        self.session = 0
        self.dragging = False

    @property
    def active(self):
        with self.lock:
            return self.anchor is not None

    def _touch(self, pointer_id, position, action):
        event = InjectTouchEvent(position, action,
                                 AMotionEventButtons.AMOTION_EVENT_BUTTON_NONE,
                                 pointer_id=pointer_id)
        self.send(event.serialize())

    def start(self):
        with self.lock:
            if self.anchor is not None:
                return
            try:
                position = self.read_position()
            except Exception as error:
                LOGGER.write(LogType.Error, 'Cannot read pinch cursor: ' + str(error))
                return
            if position is None:
                LOGGER.write(LogType.Info, 'Pinch unavailable: Android mouse cursor position not reported.')
                return
            self.session += 1
            self.anchor = position
            self._touch(self.ANCHOR_ID, position, AMotionEventAction.AMOTION_EVENT_ACTION_DOWN)

    def _release_second(self):
        self.session += 1 # Invalidate a previous drag worker before another click.
        if self.second is not None:
            self._touch(self.MOVING_ID, self.second, AMotionEventAction.AMOTION_EVENT_ACTION_UP)
            self.second = None
        self.dragging = False

    def stop(self):
        with self.lock:
            self.session += 1
            self._release_second()
            if self.anchor is not None:
                self._touch(self.ANCHOR_ID, self.anchor, AMotionEventAction.AMOTION_EVENT_ACTION_UP)
                self.anchor = None

    def _current_position(self):
        position = self.read_position()
        if position is None or self.anchor is None or position.size != self.anchor.size:
            self.stop()
            return None
        return position

    def click(self, pressed):
        with self.lock:
            if self.anchor is None:
                return
            if not pressed:
                self._release_second()
                return
            if self.second is not None:
                return
            try:
                position = self._current_position()
            except Exception as error:
                self.stop()
                LOGGER.write(LogType.Error, 'Pinch cursor read failed: ' + str(error))
                return
            if position is None:
                return
            self.second = position
            self.dragging = True
            self._touch(self.MOVING_ID, position, AMotionEventAction.AMOTION_EVENT_ACTION_DOWN)
            threading.Thread(target=self._follow_cursor, args=(self.session,), daemon=True).start()

    def update(self, position, session):
        with self.lock:
            if session != self.session or not self.dragging or self.second is None:
                return
            if position is None or self.anchor is None or position.size != self.anchor.size:
                self.stop()
                return
            if position.point != self.second.point:
                self.second = position
                self._touch(self.MOVING_ID, position, AMotionEventAction.AMOTION_EVENT_ACTION_MOVE)

    def _follow_cursor(self, session):
        while True:
            time.sleep(0.025)
            with self.lock:
                if session != self.session or not self.dragging:
                    return
            try:
                self.update(self.read_position(), session)
            except Exception as error:
                with self.lock:
                    if session == self.session:
                        self.stop()
                LOGGER.write(LogType.Error, 'Pinch tracking stopped: ' + str(error))
                return

    def wheel(self, dy):
        with self.lock:
            if self.anchor is None or self.dragging or not dy:
                return
            try:
                if self._current_position() is None:
                    return
            except Exception as error:
                self.stop()
                LOGGER.write(LogType.Error, 'Pinch zoom stopped: ' + str(error))
                return
            anchor = self.anchor
            # Put the moving finger toward the centre, where it has room to move.
            x, y = anchor.point.x, anchor.point.y
            w, h = anchor.size.width, anchor.size.height
            dx, dy_axis = ((1 if x < w / 2 else -1), 0) if w >= h else (0, (1 if y < h / 2 else -1))
            room = (w - 1 - x if dx > 0 else x) if dx else (h - 1 - y if dy_axis > 0 else y)
            radius = min(max(24, min(w, h) // 8), room // 2)
            if radius < 4:
                return
            end = max(2, min(room, radius * math.exp(max(-4, min(4, dy)) * 0.18)))
            def position(distance):
                return ScreenPosition(anchor.size, ScreenPoint(round(x + dx * distance), round(y + dy_axis * distance)))
            self.second = position(radius)
            self._touch(self.MOVING_ID, self.second, AMotionEventAction.AMOTION_EVENT_ACTION_DOWN)
            try:
                for step in range(1, 7):
                    self.second = position(radius + (end - radius) * step / 6)
                    self._touch(self.MOVING_ID, self.second, AMotionEventAction.AMOTION_EVENT_ACTION_MOVE)
                    time.sleep(0.006)
            finally:
                self._release_second()
