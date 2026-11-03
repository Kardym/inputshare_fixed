import sys
from multiprocessing import freeze_support

# The waiting process never imports session modules or truncates the session log.
if __name__ == "__main__":
    freeze_support()
    if "--session" not in sys.argv:
        from launcher import run_launcher
        sys.exit(run_launcher())

from typing import Callable

from adbutils import AdbInstallError
from server import deploy_reporter_server, deploy_scrcpy_server, scrcpy_receiver, reporter_receiver
from input.callbacks import callback_context_wrapper
from ui.connecting_window import open_connecting_window
from ui.tray import tray_thread_factory
from utils.adb_controller import ADBWiredConnectionError, append_adb_device, get_adb_client, start_adb_server
from utils.config_manager import get_config
from utils.i18n import get_i18n
from utils.logger import LogType, LOGGER
from utils.notification import Notification, send_notification

def close_notification_resolver(errno: Exception | None):
    close_notification = None
    i18n = get_i18n()
    match errno:
        case None: pass
        case ADBWiredConnectionError():
            close_notification = Notification(
                i18n(["ConnectionError", "连接错误"]),
                i18n(["Wired connection failed, please check if the device is connected correctly.", "有线连接失败，请检查是否正确连接设备。"]))
        case scrcpy_receiver.InvalidDummyByteException():
            close_notification = Notification(
                i18n(["NetworkError", "网络错误"]),
                i18n(["Connection with device failed, please retry.", "设备连接失败，请重试。"]))
        case AdbInstallError():
            close_notification = Notification(
                i18n(["NetworkError", "网络错误"]),
                i18n(["Android client installation failed, please retry.", "安卓客户端安装失败，请重试。"]))
        case TimeoutError(): # `socket.timeout` is an alias of `TimeoutError`
            close_notification = Notification(
                i18n(["NetworkError", "网络错误"]),
                i18n(["Connection with device timeout, please retry.", "设备连接超时，请重试。"]))
        case ConnectionAbortedError() | ConnectionResetError():
            close_notification = Notification(
                i18n(["NetworkError", "网络错误"]),
                i18n(["Unexpected connection aborted.", "连接意外中断。"]))
        case _:
            error_name = errno.__class__.__name__
            close_notification = Notification(
                i18n(["Error", "错误"]),
                i18n([f"Unknown error: {error_name}", f"未知错误：{error_name}"]))
    if "--session" not in sys.argv:
        get_adb_client().server_kill()
        LOGGER.write(LogType.Adb, "ADB server killed.")
    LOGGER.write(LogType.Info, "Program terminated with: " + str(close_notification))
    if "--session" not in sys.argv:
        send_notification(close_notification)

if __name__ == "__main__":
    import argparse
    import threading
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", action="store_true")
    parser.add_argument("--serial")
    parser.add_argument("--stop-file")
    options = parser.parse_args()

    start_adb_server()
    is_wired_connection = True if options.serial else open_connecting_window()
    if is_wired_connection:
        device_list = get_adb_client().device_list()
        if options.serial:
            device_list = [device for device in device_list if device.serial == options.serial]
        if len(device_list) == 0:
            # selected wired connection
            close_notification_resolver(ADBWiredConnectionError())
            sys.exit(1)
        append_adb_device(device_list[0])

    res = deploy_scrcpy_server()
    if isinstance(res, Exception):
        close_notification_resolver(res)
        sys.exit(1)
    scrcpy_server_process, scrcpy_client_socket = res

    stop_scrcpy_receiver = scrcpy_receiver.server_receiver_factory(scrcpy_client_socket)
    stop_reporter_receiver: Callable | None = None

    if get_config().edge_toggling:
        res = deploy_reporter_server()
        if isinstance(res, Exception):
            stop_scrcpy_receiver()
            scrcpy_server_process.terminate()
            close_notification_resolver(res)
            sys.exit(1)
        stop_reporter_receiver = reporter_receiver.server_receiver_factory()

    close_tray = tray_thread_factory(scrcpy_client_socket)
    callbacks  = callback_context_wrapper(scrcpy_client_socket)

    from input.controller import main_loop, schedule_exit
    watcher_stop = threading.Event()
    if options.stop_file:
        stop_path = Path(options.stop_file)
        def watch_supervisor():
            while not watcher_stop.wait(0.2):
                if stop_path.exists():
                    reason = stop_path.read_text(encoding="utf-8")
                    schedule_exit(ConnectionResetError("Device disconnected") if reason == "disconnect" else None)
                    return
        threading.Thread(target=watch_supervisor, daemon=True).start()
    try:
        main_errno = main_loop(*callbacks)
    finally:
        watcher_stop.set()
        LOGGER.write(LogType.Info, "Terminated, closing...")
        stop_scrcpy_receiver()
        stop_reporter_receiver and stop_reporter_receiver() # type: ignore
        scrcpy_server_process.terminate()
        close_tray()

    close_notification_resolver(main_errno)

    sys.exit(2 if main_errno is not None else 0)
