# coding: utf-8
import json
import threading
from collections import deque
from PyQt6.QtCore import QObject, pyqtSignal, QUrl, QTimer, pyqtSlot
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from config import get_logger
from constants import to_bool

logger = get_logger()


class HolidayNetWorker(QObject):
    """
    网络节假日数据拉取器：多 CDN 降级 + 退避重试 + 自动跟随重定向 +
    年份排队。

    【线程亲和性不变式】本类被 moveToThread 到独立 QThread；除
    request_abort() 之外，所有方法都必须在 worker 线程执行：
      * fetch_year_holiday 只能通过 request_fetch 信号跨线程触发
        （QueuedConnection → 槽体仍在 worker 线程执行）；
      * 其余方法仅由 worker 内的 QTimer / QNetworkReply 信号驱动。
    因此 self.is_fetching / target_year / try_idx / _pending_years
    无需额外锁保护。跨线程的中止语义由 threading.Event 承担。
    若要新增从主线程直接调用的方法，请显式通过信号槽投递。
    """

    finished = pyqtSignal(int, dict)
    net_error = pyqtSignal(str)
    request_fetch = pyqtSignal(int)
    abort_requested = pyqtSignal()  

    CDN_LIST = [
        "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
        "https://fastly.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
        "https://mirror.ghproxy.com/https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
        "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
        "https://cdn.jsdelivr.net/npm/chinese-days/dist/years/{year}.json",
    ]
    RETRY_DELAY_MS = 200

    def __init__(self):
        super().__init__()
        self.manager: QNetworkAccessManager = None
        self.reply: QNetworkReply = None
        self.try_idx = 0
        self.target_year = 0
        self.is_fetching = False
        # 用 Event 而非裸 bool：跨线程读写语义清晰
        self._abort_event = threading.Event()
        self._pending_years = deque()
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._request_next_cdn)
        self.request_fetch.connect(self.fetch_year_holiday)
        self.abort_requested.connect(self._do_abort)

    def request_abort(self):
        """线程安全地请求中止当前拉取。可在主线程调用（如 shutdown）。"""
        self.abort_requested.emit()
        
    @pyqtSlot()
    def _do_abort(self):
        """在 worker 线程执行：set Event + 立即中断挂起的 reply。"""
        self._abort_event.set()
        self._abort_current_reply(mark_abort=False)
        
    def _setup_manager(self):
        """仅在子线程初始化网络管理器，保证线程亲和性。"""
        if not self.manager:
            self.manager = QNetworkAccessManager(self)

    @pyqtSlot(int)
    def fetch_year_holiday(self, year: int):
        """拉取单年节假日；若正在拉取则入队，完成后自动取下一个。"""
        if self._abort_event.is_set():
            logger.info(f"已请求中止，忽略 {year} 年拉取")
            # 清空队列，避免残留
            self._pending_years.clear()
            return      
        if self.is_fetching:
            if year not in self._pending_years:
                self._pending_years.append(year)
            logger.info(f"节假日拉取中，{year}年已入队等待")
            return
        self.is_fetching = True
        self._abort_event.clear()
        self.target_year = year
        self.try_idx = 0

        self._setup_manager()
        self._abort_current_reply(mark_abort=False)
        self._request_next_cdn()

    def fetch_years_holiday(self, years: list):
        """批量拉取多年数据（依次排队）。"""
        if not years:
            return
        for year in years:
            self.request_fetch.emit(year)

    def _abort_current_reply(self, mark_abort: bool = True):
        """
        :param mark_abort: True 表示本次是"中止"语义；False 表示只是
            清理旧请求。
        """
        self._retry_timer.stop()
        if self.reply is not None:
            reply = self.reply
            self.reply = None
            if mark_abort:
                self._abort_event.set()
            try:
                reply.finished.disconnect(self.on_reply)
            except (TypeError, RuntimeError):
                pass
            reply.abort()
            reply.deleteLater()

    def _request_next_cdn(self):
        if self._abort_event.is_set():
            self._finish_with_result({})
            return

        if self.try_idx >= len(self.CDN_LIST):
            err_msg = (f"所有CDN获取{self.target_year}年节假日全部失败，"
                       f"将使用本地库兜底")
            logger.warning(err_msg)
            self.net_error.emit(err_msg)
            self._finish_with_result({})
            return

        url_str = self.CDN_LIST[self.try_idx].format(year=self.target_year)
        req = QNetworkRequest(QUrl(url_str))
        req.setTransferTimeout(8000)
        req.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        self.reply = self.manager.get(req)
        self.reply.finished.connect(self.on_reply)

    def _finish_with_result(self, result: dict):
        next_year = None
        if self._pending_years:
            next_year = self._pending_years.popleft()
        self.is_fetching = False
        self.finished.emit(self.target_year, result)
        if next_year is not None and not self._abort_event.is_set():
            self.request_fetch.emit(next_year)

    @staticmethod
    def _parse_holiday_json(raw: str, default_year: int) -> dict:
        """
        兼容多种源：
        1. NateScarlet/holiday-cn:
           {"year":2024,"days":[{"date":"2024-01-01","isOffDay":true}, ...]}
        2. chinese-days:
           {"2024-01-01": true, ...} 或 {"days": {"2024-01-01": true, ...}}
        3. list of {"date":..., "isOffDay":...}
        """
        j = json.loads(raw)
        result = {}

        if isinstance(j, dict):
            days = j.get("days")
            if isinstance(days, list):
                for item in days:
                    if isinstance(item, dict) and item.get("date"):
                       result[item["date"]] = to_bool(item.get("isOffDay", False), default=False)
                return result

            if isinstance(days, dict):
                for date_str, is_off in days.items():
                    result[date_str] = to_bool(is_off, default=False)
                return result

            date_like = [k for k in j.keys()
                         if isinstance(k, str) and len(k) == 10 and k[4] == "-"]
            if date_like:
                for date_str in date_like:
                    result[date_str] = to_bool(j[date_str], default=False)
                return result

        if isinstance(j, list):
            for item in j:
                if isinstance(item, dict) and item.get("date"):
                    result[item["date"]] = to_bool(item.get("isOffDay", False), default=False)
            return result

        raise ValueError(f"无法识别的节假日JSON结构，year={default_year}")

    @pyqtSlot()
    def on_reply(self):
        # 防御：reply 已被清理或已 abort
        if self._abort_event.is_set() or self.reply is None:
            return

        reply = self.reply
        try:
            reply.finished.disconnect(self.on_reply)
        except (TypeError, RuntimeError):
            pass

        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                raw = reply.readAll().data().decode("utf-8")
                result = self._parse_holiday_json(raw, self.target_year)
                logger.info(
                    f"网络获取{self.target_year}节假日成功，共{len(result)}条")
                self.reply = None
                reply.deleteLater()
                self._finish_with_result(result)
            else:
                logger.warning(f"CDN[{self.try_idx}]失败: {reply.errorString()}")
                self.reply = None
                reply.deleteLater()
                self.try_idx += 1
                self._retry_timer.start(self.RETRY_DELAY_MS)
        except Exception as e:
            err_msg = f"节假日解析异常: {e}"
            logger.error(err_msg)
            self.net_error.emit(err_msg)
            self.reply = None
            reply.deleteLater()
            self.try_idx += 1
            if self.try_idx >= len(self.CDN_LIST):
                self._finish_with_result({})
            else:
                self._retry_timer.start(self.RETRY_DELAY_MS)