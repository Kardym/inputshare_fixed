from types import SimpleNamespace
import socket
import threading

import pytest

import launcher
from launcher import AutoConnectController, SingleInstance, usb_devices


def test_only_authorized_usb_phones_are_selected():
    output = """List of devices attached
PHONE123 device product:test model:Phone
PHONE123 device product:test model:Phone
LOCKED unauthorized usb:1
MISSING offline
emulator-5554 device
192.168.1.5:5555 device
adb-phone._adb-tls-connect._tcp device
"""
    assert usb_devices(output) == ['PHONE123']
    assert usb_devices('List of devices attached\n') == []


class FakeSession:
    def __init__(self, serial):
        self.serial = serial
        self.result = None
        self.closed = False
        self.reason = None
    def poll(self):
        return self.result
    def close(self):
        self.closed = True
    def stop(self, reason):
        self.reason = reason
        self.closed = True


def controller():
    created = []
    now = SimpleNamespace(value=100)
    def launch(serial):
        session = FakeSession(serial)
        created.append(session)
        return session
    return AutoConnectController(launch, lambda: now.value), created, now


def test_wait_connect_disconnect_and_reconnect_without_duplicate_sessions():
    manager, created, now = controller()
    manager.tick([])
    assert not created
    manager.tick(['phone'])
    manager.tick(['phone'])
    assert len(created) == 1
    manager.tick([])
    assert created[0].reason == 'disconnect'
    assert manager.session is None
    manager.tick(['phone'])
    assert len(created) == 1
    now.value += 2
    manager.tick(['phone'])
    assert len(created) == 2
    assert created[1].serial == 'phone'
    manager.stop()
    assert created[1].reason == 'exit'


def test_user_exit_stops_monitor_and_error_exit_retries_after_delay():
    manager, created, now = controller()
    manager.tick(['phone'])
    created[0].result = 2
    assert manager.tick(['phone']) is None
    assert created[0].closed
    manager.tick(['phone'])
    assert len(created) == 1
    now.value += 6
    manager.tick(['phone'])
    created[1].result = 0
    assert manager.tick(['phone']) == 'exit'
    assert manager.session is None


def test_manual_connection_is_not_treated_as_usb_disconnect():
    manager, created, now = controller()
    manager.tick([], manual=True)
    assert created[0].serial is None
    manager.tick([])
    assert not created[0].closed
    manager.stop()


def test_session_command_quotes_are_delegated_to_subprocess(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, 'ROOT', tmp_path / 'directory with spaces')
    monkeypatch.setattr(launcher.sys, 'frozen', False, raising=False)
    command = launcher.session_command('phone', tmp_path / 'stop file')
    assert command[1] == str(launcher.ROOT / 'main.py')
    assert command[-2:] == ['--serial', 'phone']
    assert command[command.index('--stop-file') + 1] == str(tmp_path / 'stop file')


def test_single_instance_blocks_duplicates_and_can_be_restarted(monkeypatch, tmp_path):
    if launcher.sys.platform != 'win32':
        pytest.skip('Windows mutex')
    monkeypatch.setattr(launcher, 'ROOT', tmp_path)
    first, second = SingleInstance(), SingleInstance()
    try:
        assert first.acquire()
        assert not second.acquire()
        first.close()
        assert second.acquire()
    finally:
        first.close()
        second.close()


def test_disconnected_scrcpy_socket_exits_session(monkeypatch):
    import input.controller as controller_module
    from server.scrcpy_receiver import server_receiver_factory
    exited = threading.Event()
    errors = []
    def schedule_exit(error):
        errors.append(error)
        exited.set()
    monkeypatch.setattr(controller_module, 'schedule_exit', schedule_exit)
    client, peer = socket.socketpair()
    stop = server_receiver_factory(client)
    try:
        peer.close()
        assert exited.wait(2)
        assert isinstance(errors[0], ConnectionResetError)
    finally:
        stop()
        peer.close()


def test_intentional_receiver_shutdown_unblocks_without_exit_notification(monkeypatch):
    import input.controller as controller_module
    from server.scrcpy_receiver import server_receiver_factory
    errors = []
    monkeypatch.setattr(controller_module, 'schedule_exit', errors.append)
    client, peer = socket.socketpair()
    stop = server_receiver_factory(client)
    try:
        stop()
        assert not errors
    finally:
        peer.close()


def test_managed_session_cleanup_keeps_discovery_adb_server_alive(monkeypatch):
    import main
    calls = []
    monkeypatch.setattr(main.sys, 'argv', ['main.py', '--session'])
    monkeypatch.setattr(main, 'get_adb_client', lambda: SimpleNamespace(server_kill=lambda: calls.append('kill')))
    monkeypatch.setattr(main, 'send_notification', lambda _: calls.append('notify'))
    main.close_notification_resolver(None)
    assert calls == []
