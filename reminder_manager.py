# coding: utf-8
from datetime import datetime
from PyQt6.QtCore import QObject, QTimer, QDate, QTime
from config import ConfigManager, get_logger
from constants import DEFAULT_THEME
from utils import get_next_memorial_date
from dialogs import MemorialRemindDialog

logger=get_logger()

class ReminderManager(QObject):
    """提醒管理器：统一处理纪念日判定与调度"""

    # QTimer 32位int溢出保护：最大约24.8天，超过则按24天分段调度
    MAX_DELAY_MS = 24 * 24 * 60 * 60 * 1000
    # 单次调度中每个纪念日最多枚举的未来周期数，防止异常数据死循环
    MAX_LOOKAHEAD = 4

    def __init__(self, parent_widget, config: ConfigManager, sound_manager=None):
        super().__init__(parent_widget)
        self.parent = parent_widget
        self.config = config
        self.sound_mgr = sound_manager
        self._remind_timer = QTimer(self)
        self._remind_timer.setSingleShot(True)
        self._remind_timer.timeout.connect(self._on_trigger)
        self._is_scheduling = False  # 防重入标记

    @staticmethod
    def _get_int_cfg(cfg, *keys, default: int):
        val = cfg.get_nested(*keys, default)
        if val is None or not isinstance(val, int):
            return default
        return int(val)

    @staticmethod
    def _get_bool_cfg(cfg, *keys, default: bool):
        """安全读取布尔配置，兼容数字/字符串/None等各种异常值"""
        val = cfg.get_nested(*keys, default=default)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        return default

    def reschedule(self, force: bool = False, check_today: bool = True):
        """
        重新计算并调度下一次提醒
        :param force: 强制刷新，忽略防重入（配置变更时调用）
        :param check_today: 是否立刻执行一次"当日提醒检查"
        """
        if self._is_scheduling and not force:
            logger.debug("提醒调度进行中，忽略重复请求")
            return
        self._is_scheduling = True
        try:
            enable_remind = self._get_bool_cfg(
                self.config, "memorial_cfg", "enable_remind", default=True
            )
            logger.debug(f"[提醒调试] 读取总开关状态：{enable_remind}")
            if not enable_remind:
                self._remind_timer.stop()
                logger.debug("[提醒调试] 提醒总开关已关闭，定时器已停止")
                return

            if check_today:
                self.check_memorial()

            next_ts = self._calc_next_timestamp()
            if next_ts is None:
                self._remind_timer.stop()
                logger.debug("[提醒调试] 无未来提醒事件，定时器已停止")
                return

            now_ms = int(datetime.now().timestamp() * 1000)
            delay = max(0, next_ts - now_ms)

            if delay > self.MAX_DELAY_MS:
                delay = self.MAX_DELAY_MS
                logger.debug("[提醒调试] 下次提醒间隔超过24天，采用分段调度")

            self._remind_timer.start(delay)

            next_time = datetime.fromtimestamp(
                next_ts / 1000).strftime("%Y-%m-%d %H:%M:%S")
            logger.debug(
                f"[提醒调试] 下一次提醒已调度：{next_time}，"
                f"延迟 {delay / 1000:.0f} 秒"
            )
        except Exception as e:
            logger.error(f"[提醒调试] reschedule调度失败：{e}")
            import traceback
            logger.error(traceback.format_exc())
            self._remind_timer.stop()
        finally:
            self._is_scheduling = False

    def _calc_next_timestamp(self):
        """
        计算最近未来提醒事件的 UTC 毫秒时间戳。

        【修复】原实现以“纪念日当天”为推进粒度，当 advance_days 较大时，
        今年的“提前提醒窗口”一旦被越过就再也不会被枚举到。这里改为
        枚举未来 MAX_LOOKAHEAD 个纪念日周期，对每个周期计算 remind_date，
        取所有 >= base_date 中最小的那个。
        """
        candidates = []
        now_ms = int(datetime.now().timestamp() * 1000)
        today_q = QDate.currentDate()
        remind_h = self._get_int_cfg(
            self.config, "memorial_cfg", "remind_start_hour", default=8)

        now_hour = QTime.currentTime().hour()
        base_date = today_q.addDays(1) if now_hour >= remind_h else today_q

        for mem in self.config.get("memorial_days", []):
            if not isinstance(mem, dict):
                continue
            if not mem.get("enabled", True):
                continue

            try:
                advance_days = max(0, int(mem.get("advance_days", 0)))
            except (TypeError, ValueError):
                advance_days = 0

            # 枚举未来若干个发生日：以 base_date 为起点，每次推进到
            # “上一个发生日的次日”，确保不重复也不遗漏。
            search_base = base_date
            seen = set()
            for _ in range(self.MAX_LOOKAHEAD):
                target_date = get_next_memorial_date(mem, search_base)
                if target_date is None:
                    break
                if target_date in seen:
                    break
                seen.add(target_date)

                target = QDate(
                    target_date.year, target_date.month, target_date.day)
                remind_date = target.addDays(-advance_days)
                if remind_date >= base_date:
                    remind_dt = datetime(
                        remind_date.year(), remind_date.month(),
                        remind_date.day(), remind_h, 0, 0
                    )
                    ts = int(remind_dt.timestamp() * 1000)
                    if ts > now_ms:
                        candidates.append(ts)
                    # 找到第一个落在 base_date 之后的提醒日即可，
                    # 更远的周期不可能更早。
                    break

                # 提醒日仍早于 base_date：跳过当前周期，推进到次日
                search_base = target.addDays(1)

        return min(candidates) if candidates else None

    def _on_trigger(self):
        """定时触发：执行检查并重调度"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.debug(f"[提醒调试] 定时器触发，时间：{now_str}")
        self.check_memorial()
        self.reschedule()

    def check_memorial(self):
        """检查当日纪念日提醒"""
        logger.debug("[提醒调试] 开始执行当日纪念日检查")
        memorial_cfg = self.config.get("memorial_cfg", {})
        enable_remind = self._get_bool_cfg(
            self.config, "memorial_cfg", "enable_remind", default=True
        )
        logger.debug(f"[提醒调试] 提醒总开关：{enable_remind}")
        if not enable_remind:
            logger.debug("[提醒调试] 提醒总开关关闭，跳过检查")
            return

        today = QDate.currentDate()
        today_str = today.toString("yyyy-MM-dd")
        last = memorial_cfg.get("last_remind_date", "")
        logger.debug(f"[提醒调试] 今日日期：{today_str}，上次提醒日期：{last}")
        if last == today_str:
            logger.debug("[提醒调试] 今日已提醒过，跳过")
            return

        start_h = self._get_int_cfg(
            self.config, "memorial_cfg", "remind_start_hour", default=8)
        end_h = self._get_int_cfg(
            self.config, "memorial_cfg", "remind_end_hour", default=22)
        now_hour = QTime.currentTime().hour()
        logger.debug(
            f"[提醒调试] 提醒时间范围：{start_h}:00 ~ {end_h}:00，"
            f"当前小时：{now_hour}"
        )
        if not (start_h <= now_hour < end_h):
            logger.debug("[提醒调试] 当前不在提醒时间范围内，跳过")
            return

        hit_list = []
        all_mem = self.config.get("memorial_days", [])
        logger.debug(
            f"[提醒调试] 共读取到 {len(all_mem)} 个纪念日配置，开始匹配...")
        for idx, mem in enumerate(all_mem):
            if not isinstance(mem, dict):
                logger.debug(f"[提醒调试] [{idx+1}] 空配置项，跳过")
                continue
            if not mem.get("enabled", True):
                logger.debug(
                    f"[提醒调试] [{idx+1}] "
                    f"{mem.get('name', '未命名')}：已禁用，跳过"
                )
                continue

            # include_base=True：今天就是纪念日时也要命中
            target_date = get_next_memorial_date(mem, today, include_base=True)
            if target_date is None:
                logger.debug(
                    f"[提醒调试] [{idx+1}] "
                    f"{mem.get('name', '未命名')}：无法计算目标日期，跳过"
                )
                continue

            target = QDate(
                target_date.year, target_date.month, target_date.day)
            diff = today.daysTo(target)
            advance_days = mem.get("advance_days", 0)
            target_str = target.toString("yyyy-MM-dd")
            logger.debug(
                f"[提醒调试] [{idx+1}] {mem.get('name', '未命名')}："
                f"目标日期{target_str}，距离今日{diff}天，"
                f"提前提醒{advance_days}天"
            )

            if 0 <= diff <= advance_days:
                hit_text = (
                    mem["name"] if diff == 0
                    else f"{mem['name']}，还有{diff}天"
                )
                hit_list.append(hit_text)
                logger.debug(f"[提醒调试]  ✅ 命中提醒：{hit_text}")

        logger.debug(
            f"[提醒调试] 匹配完成，共命中 {len(hit_list)} 个提醒：{hit_list}")
        if hit_list:
            sound_enable = self._get_bool_cfg(
                self.config, "memorial_cfg", "sound_enable", default=True
            )
            logger.debug(
                f"[提醒调试] 声音开关：{sound_enable}，"
                f"声音管理器是否可用：{self.sound_mgr is not None}"
            )
            if sound_enable and self.sound_mgr:
                logger.debug("[提醒调试] 🔊 播放提醒音效")
                self.sound_mgr.play("assets/alert.wav")

            theme = self.config.get("theme", DEFAULT_THEME) or DEFAULT_THEME
            logger.debug("[提醒调试] 🪟 弹出提醒对话框")
            dlg = MemorialRemindDialog(hit_list, theme, self.parent)
            try:
                dlg.exec()
            finally:
                memorial_cfg["last_remind_date"] = today_str
                self.config.set("memorial_cfg", memorial_cfg, save=False)
                self.config.save_debounced()
                logger.debug(f"[提醒调试] 已标记今日 {today_str} 为已提醒")
                logger.debug(
                    "========== [提醒调试] 本次检查结束 ==========\n")
        else:
            logger.debug("[提醒调试] 无命中提醒，本次检查结束\n")