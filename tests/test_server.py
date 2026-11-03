import socket
import threading

from adbutils import AdbInstallError

from server import reporter_receiver, scrcpy_receiver

class FailingInstallDevice:
    def __init__(self, error: Exception):
        self.error = error
    def install(self, _path: str):
        raise self.error

def test_install_server_returns_install_error():
    error = AdbInstallError("INSTALL_FAILED_TEST")
    assert reporter_receiver.install_server(FailingInstallDevice(error)) is error # type: ignore

def test_install_server_returns_broken_pipe_error():
    error = BrokenPipeError()
    assert reporter_receiver.install_server(FailingInstallDevice(error)) is error # type: ignore

def _unused_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def test_try_connect_server_returns_refused_error():
    res = scrcpy_receiver.try_connect_server("127.0.0.1", _unused_port())
    assert isinstance(res, ConnectionRefusedError)

def _connect_to_fake_server(payload: bytes) -> socket.socket | Exception:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        result: list[socket.socket | Exception] = []
        thread = threading.Thread(target=lambda: result.append(scrcpy_receiver.try_connect_server("127.0.0.1", port)))
        thread.start()
        server.settimeout(3)
        conn, _ = server.accept()
        conn.sendall(payload)
        thread.join(timeout=5)
        conn.close()
    return result[0]

def test_try_connect_server_accepts_dummy_byte():
    res = _connect_to_fake_server(b"\x00")
    assert isinstance(res, socket.socket)
    res.close()

def test_try_connect_server_rejects_invalid_dummy_byte():
    res = _connect_to_fake_server(b"\x01")
    assert isinstance(res, scrcpy_receiver.InvalidDummyByteException)
