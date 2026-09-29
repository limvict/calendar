# coding: utf-8
from datetime import datetime
from PyQt6.QtCore import QObject, QDate, QTimer, QThread
from config import ConfigManager, load_holiday_cache, save_holiday_cache, get_logger
from network import HolidayNetWorker
from event_bus import event_bus, EventType

logger=get_logger()

class HolidayManager(QObject):
    """节假日数据管理：缓存、网络拉取、自动刷新、过期清理"""
    CACHE_EXPIRE_SEC = 7 * 24 * 3600
    REFRESH_INTERVAL_MS = 6 * 60 * 60 * 1000  # 6小时刷新

    def __init__(self, config: ConfigManager):
        super().__init__()
        self.config = config
        self.holiday_cache = load_holiday_cache()
        self._has_notified_error = False
        self._net_thread = None
        self._net_worker = None
        self._init_network()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(self.REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self.fetch_current_year)
        self._refresh_timer.start()

    def _init_network(self):
        self._net_thread = QThread()
        self._net_worker = HolidayNetWorker()
        self._net_worker.moveToThread(self._net_thread)
        self._net_worker.finished.connect(self._on_net_ready)
        self._net_worker.net_error.connect(self._on_net_error)
        self._net_thread.start()

    def apply_cached(self) -> dict:
        """清理过期缓存并返回有效节假日数据"""
        all_days = {}
        now_ts = datetime.now().timestamp()
        expired = []
        for year_str, year_data in self.holiday_cache.items():
            if not isinstance(year_data, dict) or "days" not in year_data or "ts" not in year_data:
                expired.append(year_str)
                continue
            if now_ts - year_data["ts"] > self.CACHE_EXPIRE_SEC:
                expired.append(year_str)
                continue
            all_days.update(year_data["days"])
        for y in expired:
            del self.holiday_cache[y]
        save_holiday_cache(self.holiday_cache)
        return all_days

    def fetch_current_year(self):
        """拉取当年节假日，12月自动预取下一年"""
        y = QDate.currentDate().year()
        self._net_worker.request_fetch.emit(y)
        if QDate.currentDate().month() == 12:
            QTimer.singleShot(2000, lambda: self._net_worker.request_fetch.emit(y + 1))

    def _on_net_ready(self, year: int, net_data: dict):
        if not net_data or year <= 0:
            return
        self.holiday_cache[str(year)] = {
            "ts": datetime.now().timestamp(),
            "days": net_data,
        }
        # 【Bug 17】原实现先 save_holiday_cache，再调 apply_cached()，
        # 而 apply_cached() 内部又会 save_holiday_cache，一次拉取写盘两次。
        # 这里直接复用 apply_cached() 的写盘，去掉冗余保存。
        event_bus.publish(EventType.HOLIDAY_UPDATED, data=self.apply_cached())

    def _on_net_error(self, err: str):
        if not self._has_notified_error:
            self._has_notified_error = True
            logger.warning(f"节假日网络错误: {err}")

    def shutdown(self):
        """安全关闭网络线程"""
        self._refresh_timer.stop()
        if self._net_worker:
            # 【Bug 19】worker 侧已改为 threading.Event，
            # 这里调用 set() 是线程安全的，不再依赖"程序收尾"的侥幸。
            self._net_worker.request_abort()
        if self._net_thread:
            self._net_thread.quit()
            if not self._net_thread.wait(3000):
                self._net_thread.terminate()
                self._net_thread.wait()