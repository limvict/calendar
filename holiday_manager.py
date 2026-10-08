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
        # 子线程亲和性 QObject 唯一可靠的清理路径：
        # QThread::finished 发出后，Qt 保证延迟删除事件仍会被处理
        # （见 Qt 文档 “No more events will be processed, except
        # deferred deletion events.”）。
        # shutdown() 里不再对 worker 调 deleteLater —— 那会把
        # DeferredDelete 投到已停的事件循环，等于永不执行。
        self._net_thread.finished.connect(self._net_worker.deleteLater)
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
        # 【#10】去掉 12 月的 QTimer.singleShot(2000, ...) 延迟。
        # HolidayNetWorker 内部用 _pending_years 队列串行处理，
        # 后 emit 的年份会自然排在当年之后执行；人为加 2 秒延迟只会
        # 让"当年请求失败重试期间下一年请求插队"的时序更难推理。
        y = QDate.currentDate().year()
        self._net_worker.request_fetch.emit(y)
        if QDate.currentDate().month() == 12:
            self._net_worker.request_fetch.emit(y + 1)

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

        if self._net_worker is not None:
            self._net_worker.request_abort()

        if self._net_thread is not None:
            self._net_thread.quit()
            clean_exit = self._net_thread.wait(3000)
            if not clean_exit:
                # terminate 路径下 Qt 不保证处理延迟删除事件，
                # 这时 worker 的 C++ 对象可能残存；
                # PyQt6 会在 Python 侧引用归零时由 GC 兜底销毁，
                # 记一条 warning 方便排查。
                logger.warning(
                    "网络线程未在 3s 内退出，强制终止；"
                    "worker 清理可能不完整"
                )
                self._net_thread.terminate()
                self._net_thread.wait()
            # _net_thread 的线程亲和性是主线程，deleteLater 由主线程
            # 事件循环处理，有效。
            self._net_thread.deleteLater()
            self._net_thread = None

        # worker 的 C++ 对象在正常退出路径下已由
        # thread.finished → deleteLater 处理；这里只丢弃 Python 引用，
        # 不重复调 deleteLater（子线程事件循环已停，会变死信）。
        self._net_worker = None