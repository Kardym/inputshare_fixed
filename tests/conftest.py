import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import utils.config_manager as config_manager
from utils.config_manager import ConfigFile

# Install an in-memory config before any module calls `get_config()`,
# so tests never read or write the real `config.json`.
_fake_manager = SimpleNamespace(config=ConfigFile(), save=lambda: None, is_first_use=False)
setattr(config_manager, "__config_instance", _fake_manager)

@pytest.fixture(autouse=True)
def config() -> ConfigFile:
    _fake_manager.config = ConfigFile()
    return _fake_manager.config
