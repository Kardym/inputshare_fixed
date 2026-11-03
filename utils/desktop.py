"""Live cursor bounds; never assume the first monitor starts at (0, 0)."""
import ctypes
import sys
from dataclasses import dataclass

import screeninfo


@dataclass(frozen=True)
class ScreenRect:
    left: int
    top: int
    right: int
    bottom: int

    def contains(self, point):
        x, y = point
        return self.left <= x < self.right and self.top <= y < self.bottom

    def clamp(self, point, margin=0):
        x, y = point
        mx = min(margin, max(0, (self.right - self.left - 1) // 2))
        my = min(margin, max(0, (self.bottom - self.top - 1) // 2))
        return (max(self.left + mx, min(self.right - 1 - mx, x)),
                max(self.top + my, min(self.bottom - 1 - my, y)))

    def intersection(self, other):
        result = ScreenRect(max(self.left, other.left), max(self.top, other.top),
                            min(self.right, other.right), min(self.bottom, other.bottom))
        return result if result.left < result.right and result.top < result.bottom else None

    def wrap(self, point):
        x, y = point
        new_x, new_y = x, y
        # Land INSIDE the opposite edge. Landing on the edge itself immediately
        # wraps back again and fills the input stream with synthetic warps.
        if self.right - self.left > 4:
            if x <= self.left:
                new_x = self.right - 3
            elif x >= self.right - 1:
                new_x = self.left + 2
        if self.bottom - self.top > 4:
            if y <= self.top:
                new_y = self.bottom - 3
            elif y >= self.bottom - 1:
                new_y = self.top + 2
        return (new_x, new_y) if (new_x, new_y) != point else None


def monitor_for_point(monitors, point):
    rects = [ScreenRect(m.x, m.y, m.x + m.width, m.y + m.height) for m in monitors]
    if not rects:
        raise RuntimeError('No connected monitors')
    for rect in rects:
        if rect.contains(point):
            return rect
    # Handles display gaps and monitors disconnected while sharing.
    x, y = point
    return min(rects, key=lambda r: (r.clamp(point)[0] - x) ** 2 + (r.clamp(point)[1] - y) ** 2)


if sys.platform == 'win32':
    from ctypes import wintypes

    class _MonitorInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                    ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]

    _user32 = ctypes.WinDLL('user32', use_last_error=True)
    _monitor_from_point = _user32.MonitorFromPoint
    _monitor_from_point.argtypes = [wintypes.POINT, wintypes.DWORD]
    _monitor_from_point.restype = wintypes.HANDLE
    _get_monitor_info = _user32.GetMonitorInfoW
    _get_monitor_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)]
    _get_monitor_info.restype = wintypes.BOOL
    _get_clip_cursor = _user32.GetClipCursor
    _get_clip_cursor.argtypes = [ctypes.POINTER(wintypes.RECT)]
    _get_clip_cursor.restype = wintypes.BOOL


def _windows_bounds(point):
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    handle = _monitor_from_point(wintypes.POINT(*point), 2) # MONITOR_DEFAULTTONEAREST
    if not handle or not _get_monitor_info(handle, ctypes.byref(info)):
        return None, None
    rect = info.rcMonitor # Full monitor, including the taskbar; never rcWork.
    monitor = ScreenRect(rect.left, rect.top, rect.right, rect.bottom)
    clip = wintypes.RECT()
    restriction = None
    if _get_clip_cursor(ctypes.byref(clip)):
        restriction = ScreenRect(clip.left, clip.top, clip.right, clip.bottom)
    return monitor, restriction


def cursor_motion_bounds(point):
    monitor, restriction = _windows_bounds(point) if sys.platform == 'win32' else (None, None)
    if monitor is None:
        monitor = monitor_for_point(screeninfo.get_monitors(), point)
    # A foreground PC app may clip the cursor to a smaller rect. Wrapping within
    # that rect preserves unlimited Android motion without altering that app.
    return (monitor.intersection(restriction) if restriction is not None else None) or monitor


def in_trigger_zone(point, bounds, direction, margin):
    x, y = point
    in_y = bounds.top + margin < y < bounds.bottom - margin
    return ((direction == 'left' and x <= bounds.left and in_y)
            or (direction == 'right' and x >= bounds.right - 1 and in_y)
            or (direction == 'top' and y <= bounds.top)
            or (direction == 'bottom' and y >= bounds.bottom - 1))
