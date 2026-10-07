# coding: utf-8
import sys
import os
import json
import copy
import logging
import tempfile
import threading
from logging.handlers import RotatingFileHandler
from threading import Timer
from typing import Any, Dict, Optional

# =========================================================================

CONFIG_VERSION = 2
CONFIG_SAVE_DEBOUNCE_MS = 500

LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3

# 命名 logger：避免污染 root logger / 第三方库日志
APP_LOGGER_NAME = "MyCalendarApp"

_logger: Optional[logging.Logger] = None
_logger_lock = threading.Lock()


# ===================== 路径辅助 =====================
def _get_base_dir() -> str:
    """按平台返回标准数据目录（不含应用名）。"""
    if sys.platform == "win32":
        return os.getenv("APPDATA") or os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support")
    return os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def _get_log_dir() -> str:
    # 测试/自定义优先：允许用环境变量指定日志目录
    override = os.getenv("MYCALENDAR_LOG_DIR")
    if override:
        return override
    return os.path.join(_get_base_dir(), "MyCalendarApp")


def get_resource_path(relative_path: str) -> str:
    """获取资源文件路径（兼容打包后环境）。"""
    if hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def _get_app_data_dir() -> str:
    data_dir = os.path.join(_get_base_dir(), "MyCalendarApp")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_config_path() -> str:
    return os.path.join(_get_app_data_dir(), "config.json")


def get_holiday_cache_path() -> str:
    return os.path.join(_get_app_data_dir(), "holiday_cache.json")


# ===================== 日志 =====================
def init_logger() -> logging.Logger:
    """
    初始化命名 logger（APP_LOGGER_NAME）。
    使用命名 logger 而非 root，避免把第三方库的 INFO 全写进本文件。
    """
    log_dir = _get_log_dir()
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "calendar_log.txt")

    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    # 不向 root 冒泡：避免第三方库通过 root 的 handler 影响本 logger
    logger.propagate = False

    # 幂等：模块重复导入 / 测试重复调用时避免重复挂 handler
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


def get_logger() -> logging.Logger:
    """懒加载 logger，首次调用时才真正创建日志文件。线程安全。"""
    global _logger
    if _logger is None:
        with _logger_lock:
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
        logger.exception(msg)
    else:
        logger.error(msg)


# ===================== 配置管理器 =====================
class ConfigManager:
    """
    配置管理器单例：统一读写、版本迁移、防抖保存、原子落盘。

    线程模型：
    - 所有对 self._cfg 的读写都持 self._lock（RLock，允许嵌套调用）。
    - _save_timer 的读/写也在锁内，避免多线程 save_debounced 互相覆盖。
    - 磁盘写通过"临时文件 + os.replace"保证原子性。

    可变值约定：
    - get() / get_nested() 返回值仅供读取；若需要在外部修改嵌套容器，
      请使用 snapshot()（深拷贝）或 update_nested()（原子更新），
      不要拿到内部 dict 直接原地改，否则绕过锁。
    """

    _instance: Optional["ConfigManager"] = None
    _init_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    # 先初始化锁，再加载配置（_load 内部会用到锁）
                    inst._lock = threading.RLock()
                    inst._save_timer: Optional[Timer] = None
                    inst._cfg: Dict[str, Any] = {}
                    inst._load()
                    cls._instance = inst
        return cls._instance

    # ---------- 加载 / 迁移 ----------
    def _load(self):
        cfg_path = get_config_path()
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("配置文件根节点不是 dict")
                with self._lock:
                    self._cfg = data
            except Exception as e:
                get_logger().warning(f"读取配置失败: {e}")
                with self._lock:
                    self._cfg = {}
        else:
            with self._lock:
                self._cfg = {}
        self._migrate()

    def _migrate(self):
        """补齐缺失字段（在锁内调用，或自行加锁）。"""
        with self._lock:
            cfg = self._cfg
            if "memorial_days" not in cfg:
                cfg["memorial_days"] = []
            if "memorial_cfg" not in cfg:
                cfg["memorial_cfg"] = {
                    "enable_remind": True,
                    "sound_enable": True,
                    "last_remind_date": "",
                    "remind_start_hour": 8,
                    "remind_end_hour": 22,
                }
            if "theme" not in cfg:
                cfg["theme"] = None
            if "topmost" not in cfg:
                cfg["topmost"] = False
            if "opacity" not in cfg:
                cfg["opacity"] = 0.92
            cfg["config_version"] = CONFIG_VERSION

    # ---------- 读取 ----------
    def get(self, key: str, default: Any = None) -> Any:
        """读取顶层键。返回内部值引用，调用方不应原地修改可变容器。"""
        with self._lock:
            return self._cfg.get(key, default)

    def get_nested(self, *keys: str, default: Any = None) -> Any:
        """
        读取嵌套键。返回深拷贝，避免调用方在锁外修改内部 dict。
        若只需要读一个标量，性能开销可忽略；
        若需要整体快照，直接使用 snapshot()。
        """
        with self._lock:
            cur = self._cfg
            for k in keys:
                if not isinstance(cur, dict):
                    return default
                cur = cur.get(k)
                if cur is None:
                    return default
            return copy.deepcopy(cur)

    def get_bool_nested(self, *keys, default: bool) -> bool:
        val = self.get_nested(*keys, default=default)
        return bool(val)

    def snapshot(self) -> Dict[str, Any]:
        """
        返回内部配置的深拷贝。
        设置对话框等"读—改—再提交"场景应使用此接口，
        以便"取消"时丢弃副本而不影响全局状态。
        """
        with self._lock:
            return copy.deepcopy(self._cfg)

    @property
    def raw(self) -> Dict[str, Any]:
        """
        兼容旧 API，等价于 snapshot()。
        保留 raw 名字是因为调用方可能仍在使用；
        新代码请直接用 snapshot()。
        """
        return self.snapshot()

    # ---------- 写入 ----------
    def set(self, key: str, value: Any, save: bool = True):
        """写入顶层键。"""
        with self._lock:
            self._cfg[key] = value
        if save:
            self.save_debounced()

    def set_nested(self, *keys_and_value: Any, save: bool = True):
        """
        写入嵌套键：config.set_nested("a", "b", "c", value)。
        会自动创建中间层 dict。
        """
        if len(keys_and_value) < 2:
            return
        *keys, value = keys_and_value
        with self._lock:
            cur = self._cfg
            for k in keys[:-1]:
                nxt = cur.get(k)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cur[k] = nxt
                cur = nxt
            cur[keys[-1]] = value
        if save:
            self.save_debounced()

    def update_nested(self, *keys: str, save: bool = True, **kwargs):
        """
        原子更新嵌套 dict 的多个键：config.update_nested("memorial_cfg",
        enable_remind=True, sound_enable=False)。

        替代旧写法：
            d = config.get("memorial_cfg", {})
            d["enable_remind"] = True          # 锁外修改，线程不安全
            config.set("memorial_cfg", d)
        """
        with self._lock:
            cur = self._cfg
            for k in keys:
                nxt = cur.get(k)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cur[k] = nxt
                cur = nxt
            cur.update(kwargs)
        if save:
            self.save_debounced()

    def replace_all(self, data: Dict[str, Any], save: bool = True):
        """
        整体替换配置（深拷贝入内部，避免外部引用共享）。
        常用于导入 / 恢复流程。
        """
        if not isinstance(data, dict):
            get_logger().warning("replace_all 收到非 dict 参数，已忽略")
            return
        with self._lock:
            self._cfg = copy.deepcopy(data)
        self._migrate()
        if save:
            self.save_debounced()

    # ---------- 持久化 ----------
    def save_debounced(self):
        """防抖保存：500ms 内的多次写只触发一次落盘。"""
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            timer = Timer(CONFIG_SAVE_DEBOUNCE_MS / 1000, self._flush_save)
            timer.daemon = True
            self._save_timer = timer
        # 在锁外启动，避免 Timer.start 万一阻塞时持有锁
        timer.start()

    def _flush_save(self):
        """
        原子写：先写临时文件并 fsync，再 os.replace 覆盖目标。
        这样即使写入途中进程被杀 / 断电，原 config.json 也不会被截断。
        """
        cfg_path = get_config_path()
        tmp_path = None
        try:
            with self._lock:
                data = copy.deepcopy(self._cfg)

            target_dir = os.path.dirname(cfg_path) or "."
            os.makedirs(target_dir, exist_ok=True)

            fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, cfg_path)
                tmp_path = None  # 替换成功，临时文件已消失
            finally:
                if tmp_path is not None and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
        except Exception as e:
            get_logger().error(f"保存配置失败: {e}")

    def flush(self):
        """
        同步落盘，供退出等场景强制刷写。
        先取消尚未触发的防抖定时器，避免与 _flush_save 并发写同一文件。
        """
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
        self._flush_save()

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
        """从文件导入配置并立即落盘。整个过程在锁内完成，避免半更新。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("导入的配置根节点不是 dict")
        except Exception as e:
            get_logger().error(f"读取导入文件失败: {e}")
            return False

        try:
            with self._lock:
                self._cfg = data
                self._migrate()      # 已在锁内，_migrate 内部会再取一次 RLock
                data_copy = copy.deepcopy(self._cfg)
            # 锁外做磁盘写（写失败也不影响内存状态）
            cfg_path = get_config_path()
            target_dir = os.path.dirname(cfg_path) or "."
            os.makedirs(target_dir, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data_copy, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, cfg_path)
                tmp_path = None
            finally:
                if tmp_path is not None and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
            return True
        except Exception as e:
            get_logger().error(f"导入配置失败: {e}")
            return False


# 全局单例
config = ConfigManager()


# ===================== 兼容旧 API =====================
def load_config() -> Dict[str, Any]:
    """兼容旧 API：返回深拷贝而非内部引用。"""
    return config.snapshot()


def save_config(cfg: dict):
    """兼容旧 API：整体替换配置（含迁移 + 立即落盘）。"""
    if not isinstance(cfg, dict):
        get_logger().warning("save_config 收到非 dict 参数，已忽略")
        return
    config.replace_all(cfg, save=False)
    config.flush()


# ===================== 节假日缓存 =====================
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