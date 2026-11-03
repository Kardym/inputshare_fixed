import json
import time

from utils import DevicePosition, TimeCounter, clamp
from utils.config_manager import ConfigFile, ConfigManager
from utils.i18n import I18n

def test_clamp():
    assert clamp(5, 0, 3) == 3
    assert clamp(-5, 0, 3) == 0
    assert clamp(2, 0, 3) == 2

def test_device_position_parse_returns_reporter_direction():
    assert DevicePosition.parse(DevicePosition.TOP) == "down"
    assert DevicePosition.parse(DevicePosition.RIGHT) == "left"
    assert DevicePosition.parse(DevicePosition.BOTTOM) == "up"
    assert DevicePosition.parse(DevicePosition.LEFT) == "right"
    assert DevicePosition.parse("unknown") == "left"

def test_time_counter_reports_after_interval():
    reported: list[int] = []
    counter = TimeCounter(0.01, reported.append)
    counter.count()
    counter.count()
    time.sleep(0.02)
    counter.count()
    assert reported == [3]

def test_i18n_selects_language(config):
    config.language = "zh_"
    assert I18n()(["en", "zh"]) == "zh"
    config.language = "ko_"
    assert I18n()(["en", "zh"]) == "en"
    config.language = "zh_"
    assert I18n()(["en only"]) == "en only"

def test_read_config_filters_unknown_and_mistyped_fields(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "device_ip1": "192.168.0.2:5555",
        "edge_toggling": True,
        "trigger_margin": "80",  # wrong type
        "unknown_key": 1,
    }))
    config = ConfigManager.read_config(str(path))
    assert config.device_ip1 == "192.168.0.2:5555"
    assert config.edge_toggling is True
    assert config.trigger_margin == ConfigFile().trigger_margin

def test_read_config_rejects_integer_mouse_speed(tmp_path):
    # characterization: `mouse_speed` is typed as float, so an integer JSON value is dropped.
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"mouse_speed": 3}))
    assert ConfigManager.read_config(str(path)).mouse_speed == ConfigFile().mouse_speed
    path.write_text(json.dumps({"mouse_speed": 3.0}))
    assert ConfigManager.read_config(str(path)).mouse_speed == 3.0

def test_read_config_non_dict_returns_default(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[]")
    assert ConfigManager.read_config(str(path)) == ConfigFile()
