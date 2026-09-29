# tests/conftest.py
# coding: utf-8
"""
pytest 共享 fixture。

提供：
  * qapp              —— PyQt6 QApplication 单例（session 级）
  * fake_lunar_env    —— 宽松农历替身，未注册日期返回 None
  * strict_lunar_env  —— 严格农历替身，语义同 fake，由测试自身保证合法性
"""
import sys
from pathlib import Path

import pytest

# 项目根目录加入 sys.path，保证能 import config / memorial / lunar 等
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _helpers import FakeLunarEnv  # noqa: E402


# ---------------------------------------------------------------- qapp
@pytest.fixture(scope="session")
def qapp():
    """PyQt6 QApplication 单例（session 级，避免重复创建崩溃）。"""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------- lunar 替身
def _install_fake_lunar(monkeypatch, env: FakeLunarEnv):
    """
    把 fake 农历查询注入到 memorial / lunar 模块。
    按 memorial.py 实际 import 方式替换：
      * get_lunar_by_datetime
      * lunar_to_gregorian
    """
    import memorial
    import lunar as lunar_mod

    for mod in (memorial, lunar_mod):
        if hasattr(mod, "get_lunar_by_datetime"):
            def _get_lunar(dt, _env=env):
                key = (dt.year, dt.month, dt.day) if hasattr(dt, "year") else dt
                return _env.get(key)
            monkeypatch.setattr(mod, "get_lunar_by_datetime", _get_lunar,
                                raising=False)

        if hasattr(mod, "lunar_to_gregorian"):
            def _to_greg(ly, lm, ld, is_leap=False, _env=env):
                return _env.get_gregorian(ly, lm, ld, is_leap)
            monkeypatch.setattr(mod, "lunar_to_gregorian", _to_greg,
                                raising=False)

    # 让 memorial 认为 cnlunar 已装
    monkeypatch.setattr(memorial, "HAS_CHNCAL", True, raising=False)


@pytest.fixture
def fake_lunar_env(monkeypatch):
    """宽松农历替身。测试里 env.add(公历, FakeLunar(...)) 注册映射。"""
    env = FakeLunarEnv()
    _install_fake_lunar(monkeypatch, env)
    return env


@pytest.fixture
def strict_lunar_env(monkeypatch):
    """严格农历替身。与 fake 共用机制，合法性由测试决定。"""
    env = FakeLunarEnv()
    _install_fake_lunar(monkeypatch, env)
    return env