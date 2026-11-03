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
        self.cursor_position: ScreenPosition | None = None
        self.anchor_down = False
        self.session = 0
        self.dragging = False
        self.panning = False

    @property
    def active(self):
        with self.lock:
            return self.anchor is not None

    @property
    def touching(self):
        with self.lock:
            return self.anchor_down

    def forward_mouse(self, data, send):
        # This check and the send share the contact-state lock. Even a queued
        # zero-movement HID report must not interrupt a touchscreen gesture.
        with self.lock:
            if not self.anchor_down:
                return send(data)
        return None

    def _event(self, pointer_id, position, action):
        return InjectTouchEvent(position, action, AMotionEventButtons.AMOTION_EVENT_BUTTON_NONE,
                                pointer_id=pointer_id).serialize()

    def start(self):
        with self.lock:
            if self.anchor is not None:
                return
            try:
                self.anchor = self.read_position()
            except Exception as error:
                LOGGER.write(LogType.Error, 'Cannot read pinch cursor: ' + str(error))
                return
            if self.anchor is None:
                LOGGER.write(LogType.Info, 'Pinch unavailable: Android mouse cursor position not reported.')
                return
            self.session += 1
            # Remember the anchor now, but put BOTH fingers down only when a
            # gesture starts. This avoids long presses and preserves mouse hover
            # coordinates while the user positions their second finger.
            self.cursor_position = self.anchor
            LOGGER.write(LogType.Info, 'Pinch anchor ready.')

    def _begin_contacts(self, position):
        self.anchor_down = True
        self.second = position
        self.cursor_position = position
        self.send(self._event(self.ANCHOR_ID, self.anchor, AMotionEventAction.AMOTION_EVENT_ACTION_DOWN)
                  + self._event(self.MOVING_ID, position, AMotionEventAction.AMOTION_EVENT_ACTION_DOWN))

    def _lift_contacts(self):
        self.session += 1
        events = b''
        if self.second is not None:
            events += self._event(self.MOVING_ID, self.second, AMotionEventAction.AMOTION_EVENT_ACTION_UP)
        if self.anchor_down:
            events += self._event(self.ANCHOR_ID, self.anchor, AMotionEventAction.AMOTION_EVENT_ACTION_UP)
        if events:
            self.send(events)
        self.second = None
        self.anchor_down = False
        self.dragging = False
        self.panning = False

    def stop(self):
        with self.lock:
            was_active = self.anchor is not None
            self._lift_contacts()
            self.anchor = None
            if was_active:
                LOGGER.write(LogType.Info, 'Pinch released.')

    def stop_alt(self):
        with self.lock:
            if not self.panning:
                self.stop()

    def pan(self, pressed):
        with self.lock:
            if not pressed:
                if self.panning:
                    self.stop()
                return
            if self.panning:
                return
            fallback = self.cursor_position
            self.stop()
            try:
                position = self.read_position() or fallback
            except Exception as error:
                LOGGER.write(LogType.Error, 'Cannot start two-finger pan: ' + str(error))
                return
            if position is None:
                LOGGER.write(LogType.Info, 'Two-finger pan unavailable: move the Android cursor first.')
                return
            size = position.size
            gap = min(32, (size.width - 1) // 2)
            x = max(gap, min(size.width - 1 - gap, position.point.x))
            y = max(0, min(size.height - 1, position.point.y))
            self.anchor = ScreenPosition(size, ScreenPoint(x - gap, y))
            self._begin_contacts(ScreenPosition(size, ScreenPoint(x + gap, y)))
            self.dragging = True
            self.panning = True
            LOGGER.write(LogType.Info, 'M3 two-finger pan started.')

    def _pan_move(self, dx, dy):
        first, second = self.anchor, self.second
        w, h = first.size.width, first.size.height
        # Clamp the pair together so its spacing cannot change at an edge.
        dx = max(-min(first.point.x, second.point.x), min(dx, w - 1 - max(first.point.x, second.point.x)))
        dy = max(-min(first.point.y, second.point.y), min(dy, h - 1 - max(first.point.y, second.point.y)))
        if not dx and not dy:
            return
        self.anchor = ScreenPosition(first.size, ScreenPoint(first.point.x + dx, first.point.y + dy))
        self.second = ScreenPosition(second.size, ScreenPoint(second.point.x + dx, second.point.y + dy))
        self.cursor_position = ScreenPosition(first.size, ScreenPoint((self.anchor.point.x + self.second.point.x) // 2,
                                                                      self.anchor.point.y))
        self.send(self._event(self.ANCHOR_ID, self.anchor, AMotionEventAction.AMOTION_EVENT_ACTION_MOVE)
                  + self._event(self.MOVING_ID, self.second, AMotionEventAction.AMOTION_EVENT_ACTION_MOVE))

    def _current_position(self):
        position = self.read_position()
        if self.anchor is None:
            return None
        # Mouse hover can be absent after a touch gesture until the physical
        # cursor moves again. Keep Alt armed instead of falling back to scroll.
        if position is None:
            return self.cursor_position or self.anchor
        if position.size != self.anchor.size:
            self.stop()
            return None
        self.cursor_position = position
        return position

    def click(self, pressed):
        with self.lock:
            if self.anchor is None:
                return
            if not pressed:
                self._lift_contacts()
                return
            if self.dragging:
                return
            try:
                position = self._current_position()
            except Exception as error:
                self.stop()
                LOGGER.write(LogType.Error, 'Pinch cursor read failed: ' + str(error))
                return
            if position is None:
                return
            self._begin_contacts(position)
            self.dragging = True
            LOGGER.write(LogType.Info, 'Pinch drag started.')

    def update(self, position, session):
        with self.lock:
            if session != self.session or not self.dragging or self.second is None:
                return
            if position is None or self.anchor is None or position.size != self.anchor.size:
                self.stop()
                return
            if position.point != self.second.point:
                self.second = position
                self.cursor_position = position
                self.send(self._event(self.MOVING_ID, position, AMotionEventAction.AMOTION_EVENT_ACTION_MOVE))

    def move(self, dx, dy):
        with self.lock:
            if not self.dragging or self.second is None:
                return False
            if self.panning:
                self._pan_move(dx, dy)
                return True
            # Once fingers are down Android may no longer report a mouse hover
            # cursor. Drive the second touch directly from relative PC movement.
            pos = self.second
            point = ScreenPoint(max(0, min(pos.size.width - 1, pos.point.x + dx)),
                                max(0, min(pos.size.height - 1, pos.point.y + dy)))
            self.update(ScreenPosition(pos.size, point), self.session)
            return True

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
            self._begin_contacts(position(radius))
            LOGGER.write(LogType.Info, 'Pinch wheel: ' + ('zoom in' if dy > 0 else 'zoom out'))
            try:
                for step in range(1, 7):
                    self.second = position(radius + (end - radius) * step / 6)
                    self.send(self._event(self.MOVING_ID, self.second, AMotionEventAction.AMOTION_EVENT_ACTION_MOVE))
                    time.sleep(0.012)
            finally:
                self._lift_contacts()
