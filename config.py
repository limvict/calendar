# coding: utf-8
import sys
import os
import json
import copy
import logging
import traceback
import threading
from logging.handlers import RotatingFileHandler
from threading import Timer
from typing import Any, Dict, Optional

# ===================== Windows 任务栏托盘图标修复 =====================
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "MyCalendarApp.DesktopLunar.3.0.0")
    except Exception:
        pass
# =========================================================================

CONFIG_VERSION = 2
CONFIG_SAVE_DEBOUNCE_MS = 500

LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3

_logger = None


def _get_log_dir() -> str:
    # 1) 测试/自定义优先：允许用环境变量指定日志目录
    override = os.getenv("MYCALENDAR_LOG_DIR")
    if override:
        return override

    # 2) 按平台取标准目录
    if sys.platform == "win32":
        base = os.getenv("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:  # linux / 其他
        base = os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")

    return os.path.join(base, "MyCalendarApp")


def init_logger():
    log_dir = _get_log_dir()
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "calendar_log.txt")

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # 避免重复添加 handler（模块可能被多次导入/测试重复调用）
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return logger

    handler = RotatingFileHandler(
        log_path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def get_logger():
    """懒加载 logger，首次调用时才真正创建日志文件。"""
    global _logger
    if _logger is None:
        _logger = init_logger()
    return _logger


def log_exception(msg: str):
    """
    记录异常堆栈。仅在真实异常上下文存在时打印 traceback，
    避免 "NoneType: None" 噪音。
    """
    logger = get_logger()
    if sys.exc_info()[0] is not None:
        logger.error(f"{msg}\n{traceback.format_exc()}")
    else:
        logger.error(msg)


def get_resource_path(relative_path: str) -> str:
    """获取资源文件路径（兼容打包后环境）"""
    if hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def _get_app_data_dir() -> str:
    """获取应用数据目录（跨平台，避开权限问题）"""
    if sys.platform == "win32":
        base = os.getenv("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")

    data_dir = os.path.join(base, "MyCalendarApp")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_config_path() -> str:
    return os.path.join(_get_app_data_dir(), "config.json")


def get_holiday_cache_path() -> str:
    return os.path.join(_get_app_data_dir(), "holiday_cache.json")


class ConfigManager:
    """
    配置管理器单例：统一读写、版本迁移、防抖保存。
    """
    _instance: Optional["ConfigManager"] = None
    _save_timer: Optional[Timer] = None
    _init_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._lock = threading.RLock()
                    inst._load()
                    cls._instance = inst
        return cls._instance

    def _load(self):
        cfg_path = get_config_path()
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    self._cfg = json.load(f)
            except Exception as e:
                get_logger().warning(f"读取配置失败: {e}")
                self._cfg = {}
        else:
            self._cfg = {}
        self._migrate()

    def _migrate(self):
        if "memorial_days" not in self._cfg:
            self._cfg["memorial_days"] = []
        if "memorial_cfg" not in self._cfg:
            self._cfg["memorial_cfg"] = {
                "enable_remind": True,
                "sound_enable": True,
                "last_remind_date": "",
                "remind_start_hour": 8,
                "remind_end_hour": 22,
            }
        if "theme" not in self._cfg:
            self._cfg["theme"] = None
        if "topmost" not in self._cfg:
            self._cfg["topmost"] = False
        if "opacity" not in self._cfg:
            self._cfg["opacity"] = 0.92
        self._cfg["config_version"] = CONFIG_VERSION

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._cfg.get(key, default)

    def set(self, key: str, value: Any, save: bool = True):
        with self._lock:
            self._cfg[key] = value
        if save:
            self.save_debounced()

    def get_nested(self, *keys: str, default: Any = None) -> Any:
        with self._lock:
            cur = self._cfg
            for k in keys:
                if not isinstance(cur, dict):
                    return default
                cur = cur.get(k)
                if cur is None:
                    return default
            return cur

    def set_nested(self, *keys_and_value: Any, save: bool = True):
        if len(keys_and_value) < 2:
            return
        *keys, value = keys_and_value
        with self._lock:
            cur = self._cfg
            for k in keys[:-1]:
                if k not in cur or not isinstance(cur[k], dict):
                    cur[k] = {}
                cur = cur[k]
            cur[keys[-1]] = value
        if save:
            self.save_debounced()

    def get_bool_nested(self, *keys, default: bool):
        val = self.get_nested(*keys, default=default)
        return bool(val)

    def save_debounced(self):
        if self._save_timer is not None:
            self._save_timer.cancel()
        self._save_timer = Timer(
            CONFIG_SAVE_DEBOUNCE_MS / 1000, self._flush_save)
        self._save_timer.daemon = True
        self._save_timer.start()

    def _flush_save(self):
        cfg_path = get_config_path()
        try:
            with self._lock:
                data = copy.deepcopy(self._cfg)
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            get_logger().error(f"保存配置失败: {e}")

    def export_to_file(self, path: str) -> bool:
        try:
            with self._lock:
                data = copy.deepcopy(self._cfg)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            get_logger().error(f"导出配置失败: {e}")
            return False

    def import_from_file(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self._cfg = data
            self._migrate()
            self._flush_save()
            return True
        except Exception as e:
            get_logger().error(f"导入配置失败: {e}")
            return False

    @property
    def raw(self) -> Dict:
        with self._lock:
            return self._cfg


# 全局单例
config = ConfigManager()


def load_config():
    """兼容旧 API：返回深拷贝而非内部引用。"""
    with config._lock:
        return copy.deepcopy(config._cfg)


def save_config(cfg: dict):
    """兼容旧 API：整体替换配置（含迁移 + 立即落盘）。"""
    if not isinstance(cfg, dict):
        get_logger().warning("save_config 收到非 dict 参数，已忽略")
        return
    with config._lock:
        config._cfg = copy.deepcopy(cfg)
    config._migrate()
    config._flush_save()


def load_holiday_cache() -> dict:
    cache_path = get_holiday_cache_path()
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            get_logger().warning(f"读取节假日缓存失败: {e}")
    return {}


def save_holiday_cache(cache_data: dict):
    cache_path = get_holiday_cache_path()
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        get_logger().error(f"保存节假日缓存失败: {e}")