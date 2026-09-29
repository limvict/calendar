# coding: utf-8
import weakref
import threading
from typing import Callable, Any, Dict, List, Tuple
from PyQt6.QtCore import QObject, pyqtSignal


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
    全局事件总线：发布-订阅模式，解耦各模块间通信
    所有跨模块交互均通过事件总线中转，避免模块间直接依赖
    """
    _instance: "EventBus" = None
    # 【Bug 3 修复】类级初始化锁，避免多线程首次构造时状态被覆盖
    _init_lock = threading.Lock()

    # 通用事件信号：(事件类型标识, 事件参数字典)
    _global_signal = pyqtSignal(str, dict)

    def __new__(cls):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._subscriber_map: Dict[str, List[Tuple[Callable, Callable]]] = {}
                    inst._lock = threading.RLock()
                    cls._instance = inst
        return cls._instance

    def subscribe(self, event_type: str, slot: Callable[[dict], Any]) -> None:
        """
        订阅指定事件
        :param event_type: 事件类型字符串
        :param slot: 回调槽函数，接收一个dict参数
        """
        def _wrapper(etype: str, data: dict):
            if etype == event_type:
                slot(data)

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
            # 【Bug 2 修复】用 _same_callable 判断，并清理所有重复订阅项（不 break）
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
    SETTINGS_CHANGED = "settings_changed"        # 设置已变更
    # 数据管理相关
    BACKUP_MEMORIAL = "backup_memorial"          # 备份纪念日数据
    RESTORE_MEMORIAL = "restore_memorial"        # 恢复纪念日数据
    # 提醒相关
    REMIND_TRIGGERED = "remind_triggered"        # 提醒触发
    # 主题相关
    THEME_CHANGED = "theme_changed"              # 主题变更


# 全局单例实例
event_bus = EventBus()