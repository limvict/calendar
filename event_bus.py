# coding: utf-8
# ⚠️ 本文件有改动：P2-2 删除死事件 THEME_CHANGED / REMIND_TRIGGERED
import threading
from typing import Callable, Any, Dict, List, Tuple
from PyQt6.QtCore import QObject, pyqtSignal

from config import get_logger   # [FIX-3]

logger = get_logger()   # [FIX-3]

def _same_callable(a, b) -> bool:
    """
    【Bug 2 修复】安全比较两个 callable 是否指向同一个绑定方法。
    - 普通函数/闭包：直接 is 比较
    - 绑定方法：Python 每次属性访问都会 new 一个对象，is 永远 False，
      需退化到比较 __self__ 和 __func__
    """
    if a is b:
        return True
    sa = getattr(a, "__self__", None)
    sb = getattr(b, "__self__", None)
    fa = getattr(a, "__func__", None)
    fb = getattr(b, "__func__", None)
    if sa is None or sb is None or fa is None or fb is None:
        return False
    return sa is sb and fa is fb

class EventBus(QObject):
    """
    事件总线：发布-订阅模式，解耦各模块间通信。

    【P2 修复】原实现把"单例"逻辑放在 __new__ 里（跳过 __init__），
    对 QObject 是隐患：Qt 侧线程亲和性 / 内部状态依赖 __init__ 正常
    执行；未来若给本类加实例级 pyqtSignal 或 moveToThread 都会踩坑。

    现在：
      - EventBus 只做"订阅/发布"的真实工作，每次构造都是独立实例。
      - 全局唯一由模块级 _EventBusProxy 保证（见文件末尾）。
      - 外部 API 完全兼容：`from event_bus import event_bus` 拿到的是
        代理对象，subscribe / unsubscribe / publish 用法不变。
    """
    _global_signal = pyqtSignal(str, dict)

    def __init__(self):
        super().__init__()
        self._subscriber_map: Dict[str, List[Tuple[Callable, Callable]]] = {}
        self._lock = threading.RLock()

    def subscribe(self, event_type: str, slot: Callable[[dict], Any]) -> None:
        """
        订阅指定事件
        :param event_type: 事件类型字符串
        :param slot: 回调槽函数，接收一个 dict 参数
        """
        def _wrapper(etype: str, data: dict):
            if etype != event_type:
                return
            # [FIX-3] 单个订阅者抛异常不应吃掉后续订阅者。
            # Qt 的 DirectConnection 里 Python 异常会向上冒泡到 emit 调用者，
            # 排在其后的 wrapper 会收不到本次事件。
            try:
                slot(data)
            except Exception:
                logger.exception(
                    f"事件 {event_type} 的订阅者 {slot} 抛异常，已隔离"
                )

        with self._lock:
            self._subscriber_map.setdefault(event_type, []).append((slot, _wrapper))
        self._global_signal.connect(_wrapper)

    def unsubscribe(self, event_type: str, slot: Callable[[dict], Any]) -> None:
        """
        取消订阅
        :param event_type: 事件类型字符串
        :param slot: 之前注册的槽函数
        """
        with self._lock:
            entries = self._subscriber_map.get(event_type, [])
            # 用 _same_callable 判断，并清理所有重复订阅项（不 break）
            removed_indices = []
            for i, (s, w) in enumerate(entries):
                if _same_callable(s, slot):
                    try:
                        self._global_signal.disconnect(w)
                    except (TypeError, RuntimeError):
                        pass
                    removed_indices.append(i)
            for i in reversed(removed_indices):
                entries.pop(i)
            if not entries and event_type in self._subscriber_map:
                del self._subscriber_map[event_type]

    def publish(self, event_type: str, **kwargs) -> None:
        """
        发布事件
        :param event_type: 事件类型字符串
        :param kwargs: 事件参数，以关键字参数形式传入
        """
        self._global_signal.emit(event_type, kwargs)

class _EventBusProxy:
    """
    模块级事件总线代理：懒创建 + 线程安全 + 与原 API 完全兼容。

    为什么要代理而不是直接模块级 EventBus()：
      - 模块 import 时立刻构造 QObject 有 Qt 时序风险（主线程 / QApplication
        尚未创建）；懒加载可以让首次 publish/subscribe 时才真正实例化。
      - 代理本身不做 QObject，没有线程亲和性约束，可被任何线程安全访问。
    """

    __slots__ = ("_impl", "_lock")

    def __init__(self):
        self._impl: "EventBus | None" = None
        self._lock = threading.Lock()

    def _ensure(self) -> EventBus:
        if self._impl is None:
            with self._lock:
                if self._impl is None:
                    self._impl = EventBus()
        return self._impl

    def subscribe(self, event_type: str, slot: Callable[[dict], Any]) -> None:
        return self._ensure().subscribe(event_type, slot)

    def unsubscribe(self, event_type: str, slot: Callable[[dict], Any]) -> None:
        return self._ensure().unsubscribe(event_type, slot)

    def publish(self, event_type: str, **kwargs) -> None:
        return self._ensure().publish(event_type, **kwargs)

# 全局事件类型常量定义
class EventType:
    # 节假日相关
    HOLIDAY_UPDATED = "holiday_updated"          # 节假日数据更新，参数：data: dict
    # 纪念日相关
    MEMORIAL_CHANGED = "memorial_changed"        # 纪念日数据变更
    # 窗口控制相关
    WINDOW_SHOW = "window_show"                  # 显示主窗口
    WINDOW_QUIT = "window_quit"                  # 退出应用
    WINDOW_TOGGLE_TOPMOST = "window_toggle_topmost"  # 切换置顶，参数：enable: bool
    # 设置相关
    OPEN_SETTINGS = "open_settings"              # 打开设置对话框
    # SETTINGS_CHANGED 目前仅 main._apply_settings 单向广播，
    # 尚无订阅方；保留事件名以便后续主题 / 字体等热更新订阅。
    SETTINGS_CHANGED = "settings_changed"        # 设置已变更
    # 数据管理相关
    BACKUP_MEMORIAL = "backup_memorial"          # 备份纪念日数据
    RESTORE_MEMORIAL = "restore_memorial"        # 恢复纪念日数据
    # 【P2-2】删除以下死事件（无发布方 / 无订阅方）：
    #   THEME_CHANGED = "theme_changed"
    #   REMIND_TRIGGERED = "remind_triggered"

# 全局单例代理
event_bus = _EventBusProxy()