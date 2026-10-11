# coding: utf-8
import threading
from typing import Callable, Any, Dict, List, Tuple
from PyQt6.QtCore import QObject, pyqtSignal, QThread, QCoreApplication
from config import get_logger

logger = get_logger()


def _same_callable(a, b) -> bool:
    """
    安全比较两个 callable 是否指向同一个绑定方法。

    绑定方法每次属性访问都会 new 一个对象，is 永远 False，需退化到
    比较 __self__ 和 __func__。
    """
    if a is b:
        return True
    sa = getattr(a, "__self__", None)
    sb = getattr(b, "__self__", None)
    fa = getattr(a, "__func__", None)
    fb = getattr(b, "__func__", None)
    if sa is None or sb is None or fa is None or fb is None:
        return a==b
    return sa is sb and fa is fb


class EventBus(QObject):
    """
    事件总线：发布-订阅模式，解耦各模块间通信。

    本类只做"订阅/发布"的真实工作，每次构造都是独立实例；全局唯一
    由模块级 _EventBusProxy 保证。API 与旧版一致：
    `from event_bus import event_bus` 拿到代理对象。
    """
    _global_signal = pyqtSignal(str, dict)

    def __init__(self):
        super().__init__()
        self._subscriber_map: Dict[str, List[Tuple[Callable, Callable]]] = {}
        self._lock = threading.RLock()

    def subscribe(self, event_type: str, slot: Callable[[dict], Any]) -> None:
        with self._lock:
            entries = self._subscriber_map.setdefault(event_type, [])
            # 幂等：同一 event_type 下同一 slot 不重复订阅。
            # 与 i18n.on_language_changed 的去重策略一致，防止
            # "构造 → 订阅 → 关闭 → 再构造"的循环里 publish 时
            # 同一 slot 被调用多次。
            for s, _ in entries:
                if _same_callable(s, slot):
                    return

            def _wrapper(etype: str, data: dict):
                if etype != event_type:
                    return
                # 单个订阅者抛异常不应吃掉后续订阅者
                try:
                    slot(data)
                except Exception:
                    logger.exception(
                        f"事件 {event_type} 的订阅者 {slot} 抛异常，已隔离")

            entries.append((slot, _wrapper))
            self._global_signal.connect(_wrapper)

    def unsubscribe(self, event_type: str, slot: Callable[[dict], Any]) -> None:
        with self._lock:
            entries = self._subscriber_map.get(event_type, [])
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
        self._global_signal.emit(event_type, kwargs)


class _EventBusProxy:
    """
    懒创建 + 线程安全的全局代理，API 与原 EventBus 完全兼容。

    用代理而非直接模块级 EventBus()：
      - import 期构造 QObject 有 Qt 时序风险（QApplication 尚未创建）；
      - 代理本身非 QObject，可被任何线程安全访问。
    """
    __slots__ = ("_impl", "_lock")

    def __init__(self):
        self._impl: "EventBus | None" = None
        self._lock = threading.Lock()

    def _ensure(self) -> EventBus:
        if self._impl is None:
            with self._lock:
                if self._impl is None:
                    app = QCoreApplication.instance()
                    # 说明：pyqtSignal 的 AutoConnection 按"emit 线程 vs
                    # 接收者（本 EventBus 实例）所属线程"判定。EventBus
                    # 一旦在子线程首次构造，后续从主线程 emit 时订阅者
                    # 会被排队到子线程执行 —— 这才是真正的隐患。
                    if (app is not None
                            and QThread.currentThread() is not app.thread()):
                        logger.warning(
                            "EventBus 在非主线程首次构造，"
                            "订阅者可能被投递到非主线程。"
                            "请确保首次 subscribe/publish 在主线程发生。")
                    self._impl = EventBus()
        return self._impl

    def subscribe(self, event_type, slot):
        app = QCoreApplication.instance()
        if app is None:
            logger.warning("EventBus.subscribe 在 QApplication 创建前调用")
        elif QThread.currentThread() is not app.thread():
            logger.warning(
                "EventBus.subscribe 从非主线程调用，"
                "订阅者槽可能在错误线程执行")
        return self._ensure().subscribe(event_type, slot)

    def unsubscribe(self, event_type, slot):
        app = QCoreApplication.instance()
        if app is not None and QThread.currentThread() is not app.thread():
            logger.warning("EventBus.unsubscribe 从非主线程调用")
        return self._ensure().unsubscribe(event_type, slot)

    def publish(self, event_type, **kwargs):
        return self._ensure().publish(event_type, **kwargs)


class EventType:
    HOLIDAY_UPDATED = "holiday_updated"
    MEMORIAL_CHANGED = "memorial_changed"
    WINDOW_SHOW = "window_show"
    WINDOW_QUIT = "window_quit"
    WINDOW_TOGGLE_TOPMOST = "window_toggle_topmost"
    OPEN_SETTINGS = "open_settings"
    # 目前仅 main._apply_settings 单向广播，保留给后续主题 / 字体热更新订阅
    SETTINGS_CHANGED = "settings_changed"
    BACKUP_MEMORIAL = "backup_memorial"
    RESTORE_MEMORIAL = "restore_memorial"


event_bus = _EventBusProxy()