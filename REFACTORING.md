# 리팩토링 준비 노트

## 개발 환경

- Python 3.12 가상 환경이 `.venv`에 준비되어 있습니다. (CI는 Python 3.10.7을 사용하므로 3.10 이상의 문법만 사용해야 합니다.)
- 3.14에서는 의존성 호환성이 검증되지 않았으므로 3.12를 사용합니다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

| 작업 | 명령 |
| --- | --- |
| 앱 실행 | `.\.venv\Scripts\python.exe main.py` |
| 테스트 | `.\.venv\Scripts\python.exe -m pytest` |
| 정적 검사 | `.\.venv\Scripts\ruff.exe check .` |

- 앱을 실행하면 프로젝트 루트에 `config.json`과 `InputShare-debug.log`가 생성됩니다. 두 파일은 모두 git에서 제외됩니다.
- 앱은 포트 5038에서 자체 ADB 서버를 띄웁니다. 강제로 종료했다면 `.\adb-bin\adb.exe -P 5038 kill-server`로 정리합니다.
- 실제 입력 공유 동작은 Android 기기(USB 디버깅 또는 무선 디버깅)가 있어야 확인할 수 있습니다. 기기가 없으면 연결 창까지만 확인할 수 있습니다.

## 안전망: 특성 테스트

`tests/`의 테스트는 **현재 동작을 그대로 고정**하는 특성 테스트(characterization test)입니다. 실기기 없이 실행됩니다.

| 파일 | 고정하는 대상 |
| --- | --- |
| `test_hid_event.py` | scrcpy UHID 메시지(키보드, 마우스)의 바이트 레이아웃 |
| `test_inject_and_clipboard_event.py` | 키코드 주입, 클립보드 요청/응답 직렬화 |
| `test_state_stores.py` | `KeymodStateStore`, `MouseButtonStateStore`의 비트 연산 |
| `test_callbacks.py` | `callback_context_wrapper`가 입력 이벤트를 어떤 바이트로 보내는지 (가짜 소켓 사용) |
| `test_utils_and_config.py` | 설정 파일 파싱, i18n, `DevicePosition`, `TimeCounter` |
| `test_server.py` | reporter 설치 실패 처리, scrcpy 소켓 연결과 dummy byte 검사 (로컬 가짜 서버 사용) |

- `tests/conftest.py`는 메모리상의 설정 객체를 주입하여, 테스트가 실제 `config.json`을 읽거나 쓰지 않도록 합니다.
- 서버 배포 경로(`server/__init__.py`의 `deploy_*`, 실제 ADB 호출)는 테스트가 없습니다.
- UI(`ui/`), ADB/네트워크(`utils/adb_controller.py`, `utils/network/`), 서버 배포(`server/`)와 `input/controller.py`의 메인 루프는 테스트가 없습니다. 이 영역을 수정할 때는 실기기로 확인해야 합니다.

## 모듈 구조

```
main.py                     진입점: ADB 서버 → 연결 창 → scrcpy 서버 배포 → 입력 루프
├─ ui/connecting_window.py  페어링·연결 창 (customtkinter)
├─ server/                  scrcpy-server, reporter.apk 배포와 수신 스레드
│   ├─ scrcpy_receiver.py   scrcpy 소켓 연결, 기기 클립보드 수신
│   └─ reporter_receiver.py 엣지 전환 이벤트 수신 (Android 측 reporter 앱)
├─ input/
│   ├─ controller.py        pynput 리스너, 전환/종료 핫키, 메인 루프 (전역 상태)
│   ├─ callbacks.py         입력 이벤트 → scrcpy 메시지 변환, 마우스 전송 스레드
│   └─ edge_portal.py       화면 가장자리 감지 스레드
├─ scrcpy_client/           scrcpy 제어 프로토콜 정의와 직렬화 (순수 로직)
├─ ui/tray.py, settings.py, fullscreen_mask.py
└─ utils/                   설정, 로거, i18n, ADB 래퍼, 포트 탐색
```

## 리팩토링 후보

### 구조

1. **모듈 전역 상태**: `input/controller.py`의 `is_redirecting`, `toggle_event`, `exit_event`, `main_errno`를 여러 모듈이 공유합니다. `ui/fullscreen_mask.py`, `ui/tray.py`, `utils/adb_controller.py`(기기 목록)도 전역 변수를 사용합니다.
2. **순환 의존을 피하기 위한 함수 내부 import**: `callbacks → controller.schedule_exit`, `edge_portal → controller.schedule_toggle`, `reporter_receiver → controller, edge_portal`. 의존 방향이 서로 얽혀 있어서, 전환 상태를 별도의 객체로 분리하고 주입하는 방식이 적합합니다.
3. **import 시점의 부수 효과**
   - `utils/logger.py`: import하는 순간 로그 파일을 엽니다.
   - `input/edge_portal.py`: import 시점에 `screen_size()`와 `get_config()`를 호출하므로, 설정 창에서 엣지 전환 설정을 바꿔도 재시작하기 전까지 반영되지 않습니다.
   - `server/*_receiver.py`: import 시점에 `get_port()`로 포트를 탐색하고, 실패하면 `sys.exit(1)`을 호출합니다.
   - `utils/adb_controller.py`: import 시점에 `ADBUTILS_ADB_PATH` 환경 변수를 설정합니다.
4. **오류 처리 방식의 혼재**: `X | Exception`을 반환값으로 쓰는 방식과 예외를 던지는 방식이 섞여 있습니다.
5. **팩토리와 클로저의 남용**: `*_factory()` 함수가 스레드를 띄우고 종료 함수를 반환하는 패턴이 반복됩니다. 수명 주기(start/stop)를 갖는 클래스로 정리할 수 있습니다.
6. **Windows 전용 가정**: `adb-bin/adb.exe` 경로, `subprocess.CREATE_NO_WINDOW`, 문자열로 조립한 명령어(`Popen(command_string)`)를 사용합니다.

### 수정한 버그

아래 버그는 모두 수정했고, 회귀 테스트로 수정된 동작을 고정했습니다.

| 위치 | 수정 전 동작 | 테스트 |
| --- | --- | --- |
| `server/reporter_receiver.py` `install_server` | `except AdbInstallError \| BrokenPipeError`가 예외 발생 시 `TypeError`를 일으켜, 설치 실패 알림 대신 앱이 비정상 종료되었습니다. | `test_server.py::test_install_server_*` |
| `input/callbacks.py` `keyboard_press_callback` | 단축키 루프 안에서 `return`하여 첫 번째 이벤트만 전송했습니다. Alt+↑/↓ 이후 키가 눌린 상태로 남고, Alt+[ ] \ 는 미디어 키를 떼는 이벤트가 빠졌습니다. | `test_alt_up_shortcut_sends_key_then_release`, `test_alt_bracket_shortcut_*` |
| `input/callbacks.py` `mouse_movement_sender` | `except: pass`가 큐 타임아웃 외의 예외까지 무시했습니다. 이제 `queue.Empty`만 처리합니다. | 없음 |
| `scrcpy_client/hid_def.py` `MouseButtonStateStore.mouse_up` | XOR을 사용하여, 누르지 않은 버튼을 떼면 눌린 상태가 되었습니다. | `test_mouse_button_up_without_down_is_noop` |
| `scrcpy_client/hid_def.py` `KeymodStateStore.keyup` | 결합 마스크(`HID_MOD_ALT` 등)를 떼면 눌리지 않았던 비트가 켜졌습니다. | `test_keymod_combined_alt_release_clears_only_pressed_bits` |
| `utils/config_manager.py` `read_config` | `"mouse_speed": 3`처럼 정수로 저장된 값이 버려졌습니다. 이제 float 필드에 한해 정수를 변환합니다. | `test_read_config_accepts_integer_for_float_field` |
| `utils/config_manager.py` `is_first_use` | 파일 존재 여부를 그대로 넣어 의미가 반대였습니다. | `test_config_manager_is_first_use` |
| `main.py` `close_notification_resolver` | `case socket.timeout \| ...`가 값 패턴으로 해석되었습니다. `case TimeoutError()`로 정리했습니다. | 없음 |
| `server/scrcpy_receiver.py` `try_connect_server` | `connect()`가 `try` 바깥에 있어서 연결 거부 예외가 그대로 전파되었고, 실패 시 소켓을 닫지 않았습니다. | `test_server.py::test_try_connect_server_*` |

### 의존성과 호환성

- `adbutils==1.2.15`는 `pkg_resources`를 사용하므로 `setuptools<81`이 필요합니다. adbutils를 2.x로 올리면 이 제약을 없앨 수 있지만 API가 바뀌었습니다.
- `locale.getdefaultlocale()`(`utils/__init__.py:23`)는 Python 3.15에서 제거될 예정입니다.
- ruff 경고: `utils/network/__init__.py`의 `import *` 4건이 남아 있습니다.
