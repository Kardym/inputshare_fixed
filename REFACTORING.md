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

`tests/`의 테스트는 **현재 동작을 그대로 고정**하는 특성 테스트(characterization test)입니다. 기기와 소켓 없이 실행됩니다.

| 파일 | 고정하는 대상 |
| --- | --- |
| `test_hid_event.py` | scrcpy UHID 메시지(키보드, 마우스)의 바이트 레이아웃 |
| `test_inject_and_clipboard_event.py` | 키코드 주입, 클립보드 요청/응답 직렬화 |
| `test_state_stores.py` | `KeymodStateStore`, `MouseButtonStateStore`의 비트 연산 |
| `test_callbacks.py` | `callback_context_wrapper`가 입력 이벤트를 어떤 바이트로 보내는지 (가짜 소켓 사용) |
| `test_utils_and_config.py` | 설정 파일 파싱, i18n, `DevicePosition`, `TimeCounter` |

- `tests/conftest.py`는 메모리상의 설정 객체를 주입하여, 테스트가 실제 `config.json`을 읽거나 쓰지 않도록 합니다.
- 이름에 `characterization`이라는 주석이 붙은 테스트는 **버그로 의심되는 현재 동작**을 고정한 것입니다. 해당 동작을 의도적으로 고친다면 테스트도 함께 수정해야 합니다.
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
4. **오류 처리 방식의 혼재**: `X | Exception`을 반환값으로 쓰는 방식과 예외를 던지는 방식이 섞여 있습니다. `callbacks.py:173`의 `except: pass`는 큐 타임아웃 외의 모든 예외까지 무시합니다.
5. **팩토리와 클로저의 남용**: `*_factory()` 함수가 스레드를 띄우고 종료 함수를 반환하는 패턴이 반복됩니다. 수명 주기(start/stop)를 갖는 클래스로 정리할 수 있습니다.
6. **Windows 전용 가정**: `adb-bin/adb.exe` 경로, `subprocess.CREATE_NO_WINDOW`, 문자열로 조립한 명령어(`Popen(command_string)`)를 사용합니다.

### 버그 또는 의심되는 동작

| 위치 | 내용 | 테스트 |
| --- | --- | --- |
| `server/reporter_receiver.py:30` | `except AdbInstallError \| BrokenPipeError`는 예외가 발생하면 `TypeError`를 일으킵니다. 튜플 `(A, B)`로 써야 합니다. | 없음 |
| `input/callbacks.py:101-102` | 단축키 처리 루프 안에서 `return`하므로 첫 번째 이벤트만 전송됩니다. Alt+↑/↓는 `KeyEmptyEvent`가 전송되지 않아 키가 눌린 상태로 남을 수 있습니다. | `test_alt_up_shortcut_sends_only_first_event` |
| `scrcpy_client/hid_def.py:26` | `mouse_up`이 XOR을 사용하므로, 누르지 않은 버튼을 떼면 오히려 눌린 상태가 됩니다. | `test_mouse_button_up_without_down_sets_bit` |
| `scrcpy_client/hid_def.py:137` | `keyup(HID_MOD_ALT)`처럼 결합 마스크를 떼면, 눌리지 않았던 비트가 켜집니다. | `test_keymod_combined_alt_partial_release` |
| `utils/config_manager.py:55` | `type(item) != float` 검사 때문에 `"mouse_speed": 3`처럼 정수로 저장된 값은 버려집니다. | `test_read_config_rejects_integer_mouse_speed` |
| `utils/config_manager.py:30` | `is_first_use`에 `os.path.exists()` 결과를 그대로 넣으므로 의미가 반대입니다. (현재 사용처는 없습니다.) | 없음 |
| `main.py:34` | `case socket.timeout \| ...`의 `socket.timeout`은 클래스 패턴이 아니라 값 패턴입니다. 뒤의 `TimeoutError()`가 대신 잡아 주기 때문에 현재는 동작합니다. | 없음 |
| `server/scrcpy_receiver.py:52` | `client_socket.connect()`가 `try` 바깥에 있어서, 연결 거부 예외가 그대로 전파됩니다. | 없음 |

### 의존성과 호환성

- `adbutils==1.2.15`는 `pkg_resources`를 사용하므로 `setuptools<81`이 필요합니다. adbutils를 2.x로 올리면 이 제약을 없앨 수 있지만 API가 바뀌었습니다.
- `locale.getdefaultlocale()`(`utils/__init__.py:23`)는 Python 3.15에서 제거될 예정입니다.
- ruff 경고: `server/scrcpy_receiver.py`의 `socket` 중복 import 1건, `utils/network/__init__.py`의 `import *` 4건입니다.
