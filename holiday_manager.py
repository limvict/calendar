# coding: utf-8
from datetime import datetime
from PyQt6.QtCore import QObject, QDate, QTimer, QThread
from config import ConfigManager, load_holiday_cache, save_holiday_cache, get_logger
from network import HolidayNetWorker
from event_bus import event_bus, EventType

logger = get_logger()


class HolidayManager(QObject):
    """节假日数据管理：缓存、网络拉取、自动刷新、过期清理。"""
    CACHE_EXPIRE_SEC = 7 * 24 * 3600
    REFRESH_INTERVAL_MS = 6 * 60 * 60 * 1000  # 6 小时刷新

    def __init__(self, config: ConfigManager):
        super().__init__()
        self.config = config
        self.holiday_cache = load_holiday_cache()
        self._has_notified_error = False
        self._net_thread = None
        self._net_worker = None
        self._shutting_down = False 
        self._init_network()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(self.REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self.fetch_current_year)
        self._refresh_timer.start()

    def _init_network(self):
        thread = None
        worker = None
        thread_started = False
        try:
            thread = QThread()
            worker = HolidayNetWorker()
            worker.moveToThread(thread)
            worker.finished.connect(self._on_net_ready)
            worker.net_error.connect(self._on_net_error)
            thread.finished.connect(worker.deleteLater)
            thread.start()
            thread_started = True
        except Exception as e:
            logger.warning(
                f"网络线程初始化失败，节假日将只用本地缓存: {e}",
                exc_info=True)
            if worker is not None:
                # 断开所有已建立的信号，避免回调悬挂到 self。
                for sig, slot in (
                    (worker.finished, self._on_net_ready),
                    (worker.net_error, self._on_net_error),
                ):
                    try:
                        sig.disconnect(slot)
                    except (TypeError, RuntimeError):
                        pass
                if not thread_started:
                    try:
                        worker.moveToThread(QThread.currentThread())
                    except Exception:
                        pass
            if thread_started and thread is not None:
                # 正常启动过的新线程需要 quit + wait，让它的 finished 触发
                # worker.deleteLater（此时 worker 已不在 thread 上，该
                # deleteLater 会排队到当前线程事件循环，无害）。
                try:
                    thread.quit()
                    thread.wait(1000)
                except Exception:
                    pass
                thread.deleteLater()
            self._net_thread = None
            self._net_worker = None
            return

        self._net_thread = thread
        self._net_worker = worker

    def apply_cached(self) -> dict:
        """清理过期缓存并返回有效节假日数据。

        返回合并后的 dict；缓存全部失效 / 为空时返回空 dict（绝不返回 None）。
        过期清理只在循环外统一执行，且仅在确实删掉条目时落盘，
        避免主窗口启动时无谓写盘。
        """
        all_days: dict = {}
        now_ts = datetime.now().timestamp()
        expired: list = []

        for year_str, year_data in self.holiday_cache.items():
            if not isinstance(year_data, dict):
                expired.append(year_str)
                continue
            days = year_data.get("days")
            ts = year_data.get("ts")
            # ts 必须是数值，days 必须是 dict，否则整条丢弃
            if not isinstance(days, dict) or not isinstance(ts, (int, float)):
                expired.append(year_str)
                continue
            if now_ts - ts > self.CACHE_EXPIRE_SEC:
                expired.append(year_str)
                continue
            all_days.update(days)

        # 循环外统一删除，避免"边遍历边改 dict"；
        # 只在真有失效项时落盘 —— 纯读取调用（主窗口启动）不触发磁盘 IO。
        if expired:
            for year_str in expired:
                self.holiday_cache.pop(year_str, None)
            save_holiday_cache(self.holiday_cache)

        return all_days

    def fetch_current_year(self):
        """拉取当年节假日，12 月自动预取下一年。"""
        if self._net_worker is None:
            # 初始化失败的降级路径：静默跳过，本地缓存 / chinese_calendar
            # 仍可提供服务。不刷 warning，避免 6 小时定时器反复报同一件事。
            return
        y = QDate.currentDate().year()
        self._net_worker.request_fetch.emit(y)
        if QDate.currentDate().month() == 12:
            self._net_worker.request_fetch.emit(y + 1)

    def _on_net_ready(self, year: int, net_data: dict):
        if self._shutting_down:           # ← 新增，第一行短路
            return
        if not net_data or year <= 0:
            return
        self.holiday_cache[str(year)] = {
            "ts": datetime.now().timestamp(),
            "days": net_data,
        }
        # apply_cached 只在清理过期项时落盘，新数据必须在此显式持久化，
        # 否则进程异常退出会丢失本次拉取结果。
        save_holiday_cache(self.holiday_cache)
        event_bus.publish(EventType.HOLIDAY_UPDATED, data=self.apply_cached())

    def _on_net_error(self, err: str):
        if self._shutting_down:
            return
        if not self._has_notified_error:
            self._has_notified_error = True
            logger.warning(f"节假日网络错误: {err}")

    def shutdown(self):
        """安全关闭网络线程。可重复调用（幂等）。"""
        # 幂等守卫：已 shutdown 或从未初始化。
        if self._net_thread is None and self._net_worker is None:
            return
        self._shutting_down = True
        self._refresh_timer.stop()

        if self._net_worker is not None:
            # 派发到 worker 线程执行 abort，真正中断挂起的 QNetworkReply，
            # 而不是只 set Event 等 8s 网络传输超时。
            self._net_worker.request_abort()

        thread = self._net_thread
        # 与 thread 同步清空，消除"引用还在但 C++ 对象已 delete"的窗口。
        self._net_thread = None
        self._net_worker = None

        if thread is None:
            return

        thread.quit()
        if thread.wait(3000):
            # worker 已被 thread.finished → worker.deleteLater 删除；
            # QThread 对象在主线程事件循环下一轮被删除。
            thread.deleteLater()
            return

        # 兜底：网络线程未在 3s 内退出。不再 terminate —— QThread.terminate()
        # 不执行栈展开，会遗留 QNetworkAccessManager 内部锁未释放，
        # 进程退出时可能死锁挂起，比"慢一点退出"更糟。
        logger.warning(
            "网络线程未在 3s 内退出，保留引用交由进程退出清理")