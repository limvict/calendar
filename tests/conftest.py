# coding: utf-8
import os
import tempfile

# Qt 离屏模式，必须在导入 PyQt6 前设置
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 隔离配置/日志目录，避免测试污染真实用户目录
_TMP_HOME = tempfile.mkdtemp(prefix="calendar_tests_")
os.environ["APPDATA"] = _TMP_HOME
os.environ["XDG_DATA_HOME"] = _TMP_HOME
os.environ["HOME"] = _TMP_HOME
os.environ["MYCALENDAR_LOG_DIR"] = os.path.join(_TMP_HOME, "logs")

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """
    每个测试使用独立临时配置目录，并重置 ConfigManager 单例。
    """
    import config as config_mod

    monkeypatch.setattr(config_mod, "_get_base_dir", lambda: str(tmp_path))
    monkeypatch.setattr(config_mod, "CONFIG_SAVE_DEBOUNCE_MS", 10)

    config_mod.ConfigManager._instance = None
    cm = config_mod.ConfigManager()

    yield config_mod, cm

    try:
        cm.flush()
    except Exception:
        pass
    config_mod.ConfigManager._instance = None