"""Fast input-capture policies and ordered work outside native Windows hooks."""
import queue
import threading


class KeyCapturePolicy:
    DOWN = {0x100, 0x104}
    UP = {0x101, 0x105}

    def __init__(self):
        self.pc_held = set()
        self.remote_held = set()

    def capture(self, msg, vk, remote):
        key = {0xa0: 0x10, 0xa1: 0x10, 0xa2: 0x11, 0xa3: 0x11,
               0xa4: 0x12, 0xa5: 0x12}.get(vk, vk)
        if msg in self.DOWN:
            (self.remote_held if remote else self.pc_held).add(key)
            return remote
        if msg in self.UP:
            was_pc = key in self.pc_held
            was_remote = key in self.remote_held
            self.pc_held.discard(key)
            self.remote_held.discard(key)
            # A modifier pressed before entering remote mode needs its key-up
            # delivered to Windows, while remote Alt-up must not open a PC menu.
            return False if was_pc else (was_remote or remote)
        return remote


class MouseCapturePolicy:
    DOWN = {0x201: 1, 0x204: 2, 0x207: 3, 0x20b: 4}
    UP = {0x202: 1, 0x205: 2, 0x208: 3, 0x20c: 4}

    def __init__(self):
        self.keys = KeyCapturePolicy()

    def capture(self, msg, mouse_data, remote):
        if msg == 0x200: # Keep physical motion for relative movement and edge wrapping.
            return False
        button = self.DOWN.get(msg) or self.UP.get(msg)
        if button:
            if button == 4:
                button += (mouse_data >> 16) - 1
            return self.keys.capture(0x100 if msg in self.DOWN else 0x101, button, remote)
        return remote # Wheel and horizontal-wheel events must not reach desktop apps.


class InputDispatcher:
    def __init__(self, generation, on_error):
        self.generation = generation
        self.on_error = on_error
        self.queue = queue.Queue()
        self.lock = threading.RLock()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, callback, *args):
        self.queue.put((self.generation(), callback, args))

    def exclusive(self, callback):
        with self.lock:
            return callback()

    def _run(self):
        while True:
            item = self.queue.get()
            if item is None:
                return
            generation, callback, args = item
            with self.lock:
                if generation != self.generation():
                    continue
                try:
                    callback(*args)
                except Exception as error:
                    self.on_error(error)

    def close(self):
        self.queue.put(None)
        self.thread.join(timeout=3)
