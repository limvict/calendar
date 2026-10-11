# coding: utf-8
import sys
import os
import json
import copy
import time          # ← 新增
import logging
import tempfile
import threading
from logging.handlers import RotatingFileHandler
from threading import Timer
from typing import Any, Dict, Optional

CONFIG_VERSION = 2
CONFIG_SAVE_DEBOUNCE_MS = 500
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3

# 命名 logger，避免污染 root / 第三方库日志
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
    override = os.getenv("MYCALENDAR_LOG_DIR")
    return override or os.path.join(_get_base_dir(), "MyCalendarApp")

def get_resource_path(relative_path: str) -> str:
    """获取资源文件路径（兼容打包后环境）。"""
    base_path = getattr(sys, "_MEIPASS", None) or os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def _get_app_data_dir() -> str:
    data_dir = os.path.join(_get_base_dir(), "MyCalendarApp")
    try:
        os.makedirs(data_dir, exist_ok=True)
    except OSError as e:
        # 降级到临时目录，保证 config 模块可 import
        fallback = os.path.join(tempfile.gettempdir(), "MyCalendarApp")
        try:
            os.makedirs(fallback, exist_ok=True)
        except OSError:
            # 两个目录都不可写：此时不能调 get_logger（会递归回本函数），
            # 直接写 stderr，让用户至少看到告警。
            print(
                f"[MyCalendarApp] 无法创建数据目录 {data_dir!r}，"
                f"也无法降级到 {fallback!r}，配置将不可写",
                file=sys.stderr)
            return data_dir
        get_logger().warning(
            f"创建数据目录失败: {e}，降级到 {fallback}")
        return fallback
    return data_dir

def get_config_path() -> str:
    return os.path.join(_get_app_data_dir(), "config.json")

def get_holiday_cache_path() -> str:
    return os.path.join(_get_app_data_dir(), "holiday_cache.json")

# ===================== 日志 =====================
def init_logger() -> logging.Logger:
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # 避免第三方库经 root 注入

    # 幂等：任何 handler 存在都视为已初始化。
    # 不用 isinstance(RotatingFileHandler) 判定，否则 stderr 回退
    # 路径会被反复重入、叠加 StreamHandler。
    if logger.handlers:
        return logger

    _FMT = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s")

    def _attach_fallback(reason: str):
        h = logging.StreamHandler()   # 默认 sys.stderr
        h.setFormatter(_FMT)
        logger.addHandler(h)
        # 此时 logger 可用，但走 logger.warning 会依赖 handler 状态；
        # 用 print 直出更稳，且避免"回退路径本身再失败"的连锁。
        print(f"[{APP_LOGGER_NAME}] {reason}，日志将输出到 stderr",
              file=sys.stderr)

    log_dir = _get_log_dir()
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        _attach_fallback(f"无法创建日志目录 {log_dir!r}: {e}")
        return logger

    log_path = os.path.join(log_dir, "calendar_log.txt")
    try:
        handler = RotatingFileHandler(
            log_path, maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
    except OSError as e:
        _attach_fallback(f"无法打开日志文件 {log_path!r}: {e}")
        return logger

    handler.setFormatter(_FMT)
    logger.addHandler(handler)
    return logger

def get_logger() -> logging.Logger:
    global _logger
    if _logger is None:
        with _logger_lock:
            if _logger is None:
                _logger = init_logger()
    return _logger

def log_exception(msg: str):
    """仅在真实异常上下文存在时打印 traceback，避免 NoneType: None 噪音。"""
    logger = get_logger()
    if sys.exc_info()[0] is not None:
        logger.exception(msg)
    else:
        logger.error(msg)

# TRACE 级别低于 DEBUG，用于"逐条纪念日诊断"等高频日志，默认关闭。
TRACE_LEVEL = logging.DEBUG - 1
logging.addLevelName(TRACE_LEVEL, "TRACE")

def _logger_trace(self, msg, *args, **kwargs):
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, msg, args, **kwargs)

logging.Logger.trace = _logger_trace


class ConfigManager:
    """
    配置管理器单例：统一读写、版本迁移、防抖保存、原子落盘。

    线程模型：
    - 所有对 self._cfg 的读写都持 self._lock（RLock，允许嵌套）。
    - _save_timer 的读写也在锁内，避免并发 save_debounced 互相覆盖。
    - 磁盘写通过"临时文件 + os.replace"保证原子性。

    可变值约定：get() / get_nested() 返回的容器仅供读取；外部如需
    修改嵌套结构，请用 snapshot()（深拷贝）或 update_nested()。
    """
    _instance: Optional["ConfigManager"] = None
    _init_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._lock = threading.RLock()
                    inst._save_timer: Optional[Timer] = None
                    inst._cfg: Dict[str, Any] = {}
                    inst._last_flush_ts: float = 0.0    # ← 新增
                    inst._load()
                    cls._instance = inst
        return cls._instance

    def _load(self):
        """
        加载配置。路径获取本身也可能失败（权限 / 只读环境），
        失败时用空配置启动，保证 config 模块可 import。
        """
        cfg_path = None
        data: Dict[str, Any] = {}
        try:
            cfg_path = get_config_path()
        except Exception as e:
            get_logger().warning(f"获取配置路径失败: {e}，使用空配置")
            with self._lock:
                self._cfg = data
                self._migrate()
            return

        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if not isinstance(raw, dict):
                    raise ValueError("配置文件根节点不是 dict")
                data = raw
            except Exception as e:
                get_logger().warning(f"读取配置失败: {e}")
                data = {}
        with self._lock:
            self._cfg = data
            self._migrate()

    def _migrate(self):
        """
        补齐缺失字段。本方法是配置默认值的唯一权威定义，
        外部工具不应复制默认值表。

        【版本迁移顺序约束】将来新增 vN → vN+1 迁移时必须：
          1. 先读 old = cfg.get("config_version")；
          2. 按 old 走分支；
          3. **最后**写 cfg["config_version"] = CONFIG_VERSION。
        下面那行赋值不得上移到任何 if 分支之前。
        """
        with self._lock:
            cfg = self._cfg
            if not isinstance(cfg.get("memorial_days"), list):
                cfg["memorial_days"] = []
            mem_cfg = cfg.get("memorial_cfg")
            if not isinstance(mem_cfg, dict):
                mem_cfg = {}
            mem_cfg.setdefault("enable_remind", True)
            mem_cfg.setdefault("sound_enable", True)
            mem_cfg.setdefault("last_remind_date", "")
            mem_cfg.setdefault("remind_start_hour", 8)
            mem_cfg.setdefault("remind_end_hour", 22)
            cfg["memorial_cfg"] = mem_cfg
            cfg.setdefault("theme", None)
            cfg.setdefault("topmost", False)
            cfg.setdefault("opacity", 0.92)
            # 必须保持在此处（见 docstring 版本迁移约束）
            cfg.setdefault("language", "zh_CN")
            cfg["config_version"] = CONFIG_VERSION

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._cfg.get(key, default)

    def get_nested(self, *keys: str, default: Any = None) -> Any:
        """读取嵌套键，返回深拷贝以避免调用方在锁外修改内部容器。"""
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
        return bool(self.get_nested(*keys, default=default))

    def snapshot(self) -> Dict[str, Any]:
        """返回内部配置的深拷贝；"读—改—提交"场景应使用此接口。"""
        with self._lock:
            return copy.deepcopy(self._cfg)

    @property
    def raw(self) -> Dict[str, Any]:
        """兼容旧 API，等价于 snapshot()。"""
        return self.snapshot()

    def set(self, key: str, value: Any, save: bool = True):
        with self._lock:
            self._cfg[key] = value
        if save:
            self.save_debounced()

    def set_nested(self, *keys_and_value: Any, save: bool = True):
        """set_nested("a", "b", "c", value) 会自动创建中间层 dict。"""
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
        """原子更新嵌套 dict 的多个键，替代"锁外改 + set 回写"的旧写法。"""
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
        """整体替换配置；赋值与 _migrate 在同一把锁内，避免读到半更新状态。"""
        if not isinstance(data, dict):
            get_logger().warning("replace_all 收到非 dict 参数，已忽略")
            return
        with self._lock:
            self._cfg = copy.deepcopy(data)
            self._migrate()
        if save:
            self.save_debounced()

    def save_debounced(self):
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            timer = Timer(CONFIG_SAVE_DEBOUNCE_MS / 1000, self._flush_save)
            timer.daemon = True
            self._save_timer = timer
        # 锁外启动，避免 Timer.start 意外阻塞时持锁
        timer.start()

    def _flush_save(self):
        """
        原子写：临时文件 + fsync + os.replace，进程被杀 / 断电也不会
        截断原 config.json。

        并发守卫（best-effort）：快照时刻 snapshot_ts 早于已成功落盘
        的最新时刻时，本次丢弃。能显著缩小"旧快照覆盖新快照"的窗口，
        但不构成完全串行化 —— 两个线程同时通过检查后才写盘时仍可能
        乱序。真正杜绝需要文件锁或全局串行队列，代价与本程序收益不
        匹配，故只做概率性守卫。os.replace 保证文件本身永不损坏。

        若本次回调正是 self._save_timer 触发（Timer 是 Thread 子类，
        current_thread() 返回其自身），落盘后清空引用；若期间
        save_debounced 已起新 timer，则不动以避免误清。
        """
        current_timer = threading.current_thread()
        tmp_path = None
        try:
            cfg_path = get_config_path()
            with self._lock:
                if self._save_timer is current_timer:
                    self._save_timer = None
                data = copy.deepcopy(self._cfg)
                snapshot_ts = time.monotonic()
                # 已有更晚的快照落过盘 → 本次跳过
                if snapshot_ts <= self._last_flush_ts:
                    return
            target_dir = os.path.dirname(cfg_path) or "."
            os.makedirs(target_dir, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, cfg_path)
                tmp_path = None
                # 只有成功落盘才推进水位
                with self._lock:
                    if snapshot_ts > self._last_flush_ts:
                        self._last_flush_ts = snapshot_ts
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
        同步落盘，供退出路径使用。

        Timer.cancel() 只对"尚未进入回调"的 timer 生效；若 timer 线程
        已进入 _flush_save 锁外序列化阶段，本函数会再跑一次 _flush_save
        ——两个线程并发写盘。落盘走"临时文件 + os.replace"，目标文件不会
        损坏，最坏情况是两次快照写入顺序不确定。退出路径上通常无其他
        线程改配置，影响可忽略，故不额外加锁串行化。
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
        """从文件导入配置并立即落盘；整个过程在锁内完成，避免半更新。"""
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
                self._migrate()
                data_copy = copy.deepcopy(self._cfg)
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
    return config.snapshot()

def save_config(cfg: dict):
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