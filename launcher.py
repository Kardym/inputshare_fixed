"""Single-instance Windows tray supervisor for hot-plugged Android sessions."""
import ctypes
import hashlib
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
ASSETS = Path(getattr(sys, '_MEIPASS', ROOT))
ADB = ASSETS / 'adb-bin' / 'adb.exe'
ADB_PORT = 5038
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
LOG = logging.getLogger('InputShare.launcher')


def usb_devices(output):
    """Only authorized physical USB devices; leave emulators and network ADB alone."""
    serials = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[1] != 'device':
            continue
        serial = parts[0]
        if ':' in serial or serial.startswith('emulator-') or '_adb-tls-' in serial:
            continue
        serials.append(serial)
    return sorted(set(serials))


def connected_usb_devices():
    result = subprocess.run([str(ADB), '-P', str(ADB_PORT), 'devices', '-l'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=8, creationflags=NO_WINDOW)
    if result.returncode:
        raise OSError('ADB device discovery failed')
    return usb_devices(result.stdout)


def session_command(serial, stop_file):
    command = [sys.executable]
    if not getattr(sys, 'frozen', False):
        command.append(str(ROOT / 'main.py'))
    command += ['--session', '--stop-file', str(stop_file)]
    if serial is not None:
        command += ['--serial', serial]
    return command


class Session:
    def __init__(self, serial):
        self.directory = tempfile.TemporaryDirectory(prefix='inputshare-session-')
        self.stop_file = Path(self.directory.name) / 'stop'
        self.output = open(ROOT / 'InputShare-session-console.log', 'w', encoding='utf-8')
        try:
            self.process = subprocess.Popen(session_command(serial, self.stop_file), cwd=str(ROOT),
                                            stdout=self.output, stderr=subprocess.STDOUT,
                                            creationflags=NO_WINDOW)
        except Exception:
            self.output.close()
            self.directory.cleanup()
            raise
        LOG.info('Session started (pid=%s)', self.process.pid)

    def poll(self):
        return self.process.poll()

    def close(self):
        self.output.close()
        self.directory.cleanup()

    def stop(self, reason):
        if self.poll() is None:
            self.stop_file.write_text(reason, encoding='utf-8')
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                # The venv executable can have a Python child: stop only this tree.
                subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                               capture_output=True, timeout=5, creationflags=NO_WINDOW)
                self.process.wait(timeout=5)
        self.close()


class AutoConnectController:
    def __init__(self, launch=Session, clock=time.monotonic):
        self.launch = launch
        self.clock = clock
        self.session = None
        self.serial = None
        self.retry_after = 0
        self.status = 'Waiting for USB phone'

    def tick(self, serials, manual=False):
        if self.session is not None:
            result = self.session.poll()
            if result is not None:
                self.session.close()
                self.session = None
                self.serial = None
                if result == 0:
                    return 'exit' # Alt+Shift+Q or tray Exit also stops the supervisor.
                self.retry_after = self.clock() + 5
                self.status = 'Waiting to reconnect'
                LOG.info('Session ended; will reconnect (code=%s)', result)
            elif self.serial is not None and self.serial not in serials:
                self.session.stop('disconnect')
                self.session = None
                self.serial = None
                self.retry_after = self.clock() + 1
                self.status = 'Waiting for USB phone'
                LOG.info('Phone disconnected; waiting')
            return None
        if not manual and (not serials or self.clock() < self.retry_after):
            self.status = 'Waiting for USB phone'
            return None
        self.serial = None if manual else serials[0]
        self.session = self.launch(self.serial)
        self.status = 'Phone connected' if self.serial is not None else 'Manual connection'
        return None

    def stop(self):
        if self.session is not None:
            self.session.stop('exit')
            self.session = None


class SingleInstance:
    def __init__(self):
        self.handle = None
        if sys.platform != 'win32':
            raise RuntimeError('Automatic tray startup currently supports Windows')
        from ctypes import wintypes
        self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel32.CreateMutexW.restype = wintypes.HANDLE
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL

    def acquire(self):
        identity = hashlib.sha256(str(ROOT).lower().encode()).hexdigest()[:20]
        handle = self.kernel32.CreateMutexW(None, False, 'Local\\InputShareFixed-' + identity)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183: # ERROR_ALREADY_EXISTS
            self.kernel32.CloseHandle(handle)
            return False
        self.handle = handle
        return True

    def close(self):
        if self.handle:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


def run_launcher():
    instance = SingleInstance()
    if not instance.acquire():
        return 0
    handler = RotatingFileHandler(ROOT / 'InputShare-launcher.log', maxBytes=1048576,
                                  backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    LOG.setLevel(logging.INFO)
    LOG.addHandler(handler)
    stop = threading.Event()
    manual = threading.Event()
    worker = None
    controller = AutoConnectController()
    try:
        import pystray
        from PIL import Image

        def exit_launcher(icon, item):
            stop.set()
            icon.stop()

        def manual_connect(icon, item):
            if controller.session is None:
                manual.set()

        icon = pystray.Icon('InputShare Auto Connect', Image.open(ASSETS / 'ui' / 'icon.ico'),
                            title='InputShare - Waiting for USB phone', menu=pystray.Menu(
                                pystray.MenuItem(lambda item: controller.status, None, enabled=False),
                                pystray.MenuItem('Manual connection...', manual_connect,
                                                 enabled=lambda item: controller.session is None),
                                pystray.Menu.SEPARATOR,
                                pystray.MenuItem('Exit InputShare', exit_launcher)))

        def monitor():
            LOG.info('Automatic USB connection monitor started')
            while not stop.is_set():
                try:
                    serials = connected_usb_devices()
                    requested = manual.is_set()
                    manual.clear()
                    if controller.tick(serials, requested) == 'exit':
                        stop.set()
                        icon.stop()
                        break
                    icon.title = 'InputShare - ' + controller.status
                except Exception:
                    LOG.exception('Auto-connect check failed')
                stop.wait(2)
            LOG.info('Automatic connection monitor stopped')

        def setup(icon):
            nonlocal worker
            icon.visible = True
            worker = threading.Thread(target=monitor, daemon=True)
            worker.start()

        icon.run(setup=setup)
    finally:
        stop.set()
        if worker is not None:
            worker.join(timeout=30)
        try:
            controller.stop()
        finally:
            instance.close()
            LOG.removeHandler(handler)
            handler.close()
    return 0
