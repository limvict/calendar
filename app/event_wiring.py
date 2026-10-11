# coding: utf-8
"""
主窗口与 event_bus 的订阅声明。

订阅表集中在此模块，订阅/退订共用同一份，避免两处漏改不一致。
回调通过 bound method 从 window 上取，本模块不 import main_window，
避免循环依赖。
"""
from event_bus import event_bus, EventType
from config import get_logger

logger = get_logger()


def _subscriptions(window):
    """(事件类型, 回调) 声明表。"""
    return [
        (EventType.HOLIDAY_UPDATED,       window._on_holiday_updated),
        (EventType.MEMORIAL_CHANGED,      window._on_memorial_changed),
        (EventType.WINDOW_SHOW,           window._on_window_show),
        (EventType.WINDOW_QUIT,           window._on_window_quit),
        (EventType.WINDOW_TOGGLE_TOPMOST, window._on_tray_topmost),
        (EventType.OPEN_SETTINGS,         window._on_open_settings),
        (EventType.BACKUP_MEMORIAL,       window._on_backup_memorial),
        (EventType.RESTORE_MEMORIAL,      window._on_restore_memorial),
    ]


def connect(window) -> None:
    for evt, cb in _subscriptions(window):
        event_bus.subscribe(evt, cb)


def disconnect(window) -> None:
    """
    退出时主动解除事件订阅，避免闭包/引用悬挂到解释器退出。
    逐条 try：某条失败不影响其余清理。
    """
    for evt, cb in _subscriptions(window):
        try:
            event_bus.unsubscribe(evt, cb)
        except Exception as e:
            logger.warning(f"取消订阅 {evt} 失败: {e}")