# coding: utf-8
from datetime import datetime
from PyQt6.QtCore import QObject, QTimer, QDate, QTime
from config import ConfigManager, get_logger
from constants import DEFAULT_THEME
from memorial import normalize_memorial, get_next_memorial_date
from dialogs import MemorialRemindDialog
from i18n import tr

logger = get_logger()


class ReminderManager(QObject):
    """提醒管理器：统一处理纪念日判定与调度。"""

    # QTimer 32 位 int 溢出保护：最大约 24.8 天，超过则按 24 天分段调度
    MAX_DELAY_MS = 24 * 24 * 60 * 60 * 1000

    # 每个纪念日最多尝试的候选周期数。用于 get_next_memorial_date 返回的
    # 候选日期在当前时刻已过（如今天命中但 remind_start_hour 已过）时，
    # 推进 search_base 到下一周期重新取候选。
    #
    # 与 memorial._LUNAR_*_LOOKAHEAD 语义正交：那两个常量是"单次搜索的
    # 深度边界"（农历 13 个月 / 5 年），本常量是"候选已过后的推进次数"，
    # 不能扩展单次搜索的窗口深度。
    MAX_RETRY_PER_MEMORIAL = 4

    def __init__(self, parent_widget, config: ConfigManager, sound_manager=None):
        super().__init__(parent_widget)
        self.parent = parent_widget
        self.config = config
        self.sound_mgr = sound_manager
        self._remind_timer = QTimer(self)
        self._remind_timer.setSingleShot(True)
        self._remind_timer.timeout.connect(self._on_trigger)
        self._is_scheduling = False  # 防重入（仅保护非 force 路径）

    # ------------------------------------------------------------------ #
    # 配置读取
    # ------------------------------------------------------------------ #
    @staticmethod
    def _get_int_cfg(cfg, *keys, default: int, lo: int = None, hi: int = None):
        """
        读取 int 配置，兼容浮点/字符串。lo / hi 越界时夹取到边界（而非
        回退 default），保留用户"深夜/凌晨"等意图，与 normalize_memorial
        的夹取风格一致。
        """
        val = cfg.get_nested(*keys, default=default)
        # bool 是 int 子类，必须优先拦截，否则 True→1 / False→0
        if isinstance(val, bool):
            return default
        try:
            v = int(val)
        except (TypeError, ValueError):
            return default
        if lo is not None and v < lo:
            return lo
        if hi is not None and v > hi:
            return hi
        return v

    @staticmethod
    def _get_bool_cfg(cfg, *keys, default: bool):
        """
        安全读取布尔配置。JSON 手改成 1.0 / 0.0 时不应静默回退 default
        （会导致关不掉的提醒）。
        """
        val = cfg.get_nested(*keys, default=default)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        if isinstance(val, str):
            low = val.strip().lower()
            if low in ("true", "1", "yes", "on"):
                return True
            if low in ("false", "0", "no", "off"):
                return False
        return default

    # ------------------------------------------------------------------ #
    # 预归一化
    # ------------------------------------------------------------------ #
    def _normalized_enabled_list(self):
        """
        全表归一化一次，过滤掉非 dict / normalize 失败 / 已禁用项。
        调用方循环内不必再 normalize。

        advance_days 在此统一夹取为合法非负 int 并写回，使
        _calc_next_timestamp / check_memorial 可直接信任该字段。
        """
        raw_list = self.config.get("memorial_days", [])
        result = []
        for mem in raw_list:
            if not isinstance(mem, dict):
                continue
            try:
                n = normalize_memorial(mem)
            except Exception:
                logger.warning(
                    f"[提醒调试] 归一化失败，跳过：{mem!r}", exc_info=True)
                continue
            if not n.get("enabled", True):
                continue
            try:
                n["advance_days"] = max(0, int(n.get("advance_days", 0)))
            except (TypeError, ValueError):
                n["advance_days"] = 0
            result.append(n)
        return result

    # ------------------------------------------------------------------ #
    # 调度入口
    # ------------------------------------------------------------------ #
    def reschedule(self, force: bool = False, check_today: bool = False):
        """
        :param force: 强制刷新，跳过防重入。用于"用户显式动作"（应用设置、
            恢复数据）。此路径不参与 _is_scheduling 状态机，也不修改它
            —— 否则会与并发的非 force 调用互相干扰（A 恢复成 False 后
            B 仍在执行，C 误判可重入）。
        :param check_today: 是否立刻执行一次当日提醒检查。默认 False，
            只有"用户显式动作"才传 True；启动、配置刷新等场景静默重排，
            避免误弹提醒窗。
        """
        if not force:
            if self._is_scheduling:
                logger.debug("提醒调度进行中，忽略重复请求")
                return
            self._is_scheduling = True
        try:
            enable_remind = self._get_bool_cfg(
                self.config, "memorial_cfg", "enable_remind", default=True)
            if not enable_remind:
                self._remind_timer.stop()
                logger.debug("[提醒调试] 提醒总开关关闭，定时器停止")
                return

            if check_today:
                # 投递到事件循环下一轮，让本函数先完成定时器重排，
                # 避免弹窗阻塞把重排推迟。
                QTimer.singleShot(0, self.check_memorial)

            next_ts = self._calc_next_timestamp()
            if next_ts is None:
                self._remind_timer.stop()
                logger.debug("[提醒调试] 无未来提醒事件，定时器已停止")
                return

            now_ms = int(datetime.now().timestamp() * 1000)
            delta_ms = next_ts - now_ms

            if delta_ms > self.MAX_DELAY_MS:
                # 分段调度：分段触发只重算时间，不做当日提醒
                self._remind_timer.start(self.MAX_DELAY_MS)
                logger.debug("[提醒调试] 下次提醒间隔超过24天，采用分段调度")
                return

            delay = max(0, delta_ms)
            self._remind_timer.start(delay)
            next_time = datetime.fromtimestamp(
                next_ts / 1000).strftime("%Y-%m-%d %H:%M:%S")
            logger.debug(
                f"[提醒调试] 下一次提醒已调度：{next_time}，"
                f"延迟 {delay / 1000:.0f} 秒")

        except Exception:
            logger.exception("[提醒调试] reschedule调度失败")
            self._remind_timer.stop()
        finally:
            if not force:
                self._is_scheduling = False

    # ------------------------------------------------------------------ #
    @staticmethod
    def _first_future_remind_ts(first_alert_qd, target_qd, remind_h, now_dt):
        """
        返回 [first_alert_day, target_day] 区间内第一个未到来的提醒时刻
        （毫秒时间戳）；无候选返回 None。
        """
        now_ms = int(now_dt.timestamp() * 1000)
        today_qd = QDate(now_dt.year, now_dt.month, now_dt.day)
        start = first_alert_qd if first_alert_qd > today_qd else today_qd
        if start == today_qd:
            today_remind = datetime(now_dt.year, now_dt.month, now_dt.day,
                                    remind_h, 0, 0)
            if int(today_remind.timestamp() * 1000) <= now_ms:
                start = start.addDays(1)  # 今天时刻已过 → 明天
        if start > target_qd:
            return None
        dt = datetime(start.year(), start.month(), start.day(), remind_h, 0, 0)
        ts = int(dt.timestamp() * 1000)
        return ts if ts > now_ms else None

    # ------------------------------------------------------------------ #
    # 下一个提醒时间戳
    # ------------------------------------------------------------------ #
    def _calc_next_timestamp(self):
        """计算所有纪念日最近的未来提醒时间戳(ms)，没有返回 None。"""
        candidates = []
        # now_dt / today_q 用同一时刻，避免跨秒/跨日微差
        now_dt = datetime.now()
        today_q = QDate(now_dt.year, now_dt.month, now_dt.day)
        remind_h = self._get_int_cfg(
            self.config, "memorial_cfg", "remind_start_hour",
            default=8, lo=0, hi=23)
        normalized = self._normalized_enabled_list()
        for mem in normalized:
            advance_days = mem.get("advance_days", 0)

            search_base = today_q
            for _ in range(self.MAX_RETRY_PER_MEMORIAL):
                target_date = get_next_memorial_date(
                    mem, search_base, include_base=True, normalized=True)
                if target_date is None:
                    logger.debug(
                        f"[提醒调试] {mem.get('name', '未命名')}："
                        f"从 {search_base} 起无可计算的候选日期，跳过")
                    break
                target = QDate(target_date.year, target_date.month,
                               target_date.day)
                first_alert_day = target.addDays(-advance_days)
                if first_alert_day < today_q:
                    first_alert_day = today_q

                ts = self._first_future_remind_ts(
                    first_alert_day, target, remind_h, now_dt)
                if ts is not None:
                    candidates.append(ts)
                    logger.trace(
                        f"[提醒调试] {mem.get('name', '未命名')}："
                        f"目标 {target.toString('yyyy-MM-dd')}，"
                        f"提醒时刻 "
                        f"{datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M')}")
                    break
                search_base = target.addDays(1)

        if not candidates:
            return None
        return min(candidates)

    # ------------------------------------------------------------------ #
    # 定时触发
    # ------------------------------------------------------------------ #
    def _on_trigger(self):
        """定时器到期回调。重排由 check_memorial 的 finally 统一负责。"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.debug(f"[提醒调试] 定时器触发，时间：{now_str}")
        try:
            self.check_memorial()
        except Exception:
            logger.exception("[提醒调试] check_memorial 异常")

    # ------------------------------------------------------------------ #
    # 当日提醒检查
    # ------------------------------------------------------------------ #
    def check_memorial(self):
        """
        检查当日纪念日提醒。

        finally 统一负责重排定时器，覆盖所有分支（早退 / 无命中 / 命中）。
        将来在本函数内新增 return 分支不会导致漏排。
        """
        logger.debug("[提醒调试] 开始执行当日纪念日检查")
        try:
            memorial_cfg = self.config.get("memorial_cfg")
            if not isinstance(memorial_cfg, dict):
                memorial_cfg = {}
            enable_remind = self._get_bool_cfg(
                self.config, "memorial_cfg", "enable_remind", default=True)
            if not enable_remind:
                logger.debug("[提醒调试] 提醒总开关关闭，跳过检查")
                return

            today = QDate.currentDate()
            today_str = today.toString("yyyy-MM-dd")
            last = memorial_cfg.get("last_remind_date", "")

            if last == today_str:
                logger.debug("[提醒调试] 今日已提醒过，跳过")
                return

            start_h = self._get_int_cfg(
                self.config, "memorial_cfg", "remind_start_hour",
                default=8, lo=0, hi=23)
            end_h = self._get_int_cfg(
                self.config, "memorial_cfg", "remind_end_hour",
                default=22, lo=0, hi=24)
            now_hour = QTime.currentTime().hour()

            if not (start_h <= now_hour < end_h):
                logger.debug(
                    f"[提醒调试] 当前 {now_hour} 点不在 {start_h}~{end_h} "
                    f"提醒窗口内，跳过")
                return

            hit_list = []
            all_mem = self._normalized_enabled_list()

            for idx, mem in enumerate(all_mem):
                target_date = get_next_memorial_date(
                    mem, today, include_base=True, normalized=True)
                if target_date is None:
                    logger.debug(
                        f"[提醒调试] {mem.get('name', '未命名')}："
                        f"无法计算目标日期，跳过")
                    continue

                target = QDate(target_date.year, target_date.month,
                               target_date.day)
                diff = today.daysTo(target)
                advance_days = mem.get("advance_days", 0)

                logger.trace(
                    f"[提醒调试] [{idx+1}] {mem.get('name', '未命名')}："
                    f"目标 {target.toString('yyyy-MM-dd')}，"
                    f"距今日 {diff} 天，提前 {advance_days} 天")

                if 0 <= diff <= advance_days:
                    name = mem.get("name") or tr("memorial.default_name")
                    if diff == 0:
                        hit_text = name
                    elif diff == 1:
                        hit_text = tr("memorial.remind.hit_fmt_one").format(
                            name=name)
                    else:
                        hit_text = tr("memorial.remind.hit_fmt").format(
                            name=name, days=diff)
                    hit_list.append(hit_text)
                    logger.debug(f"[提醒调试]  ✅ 命中提醒：{hit_text}")

            logger.debug(
                f"[提醒调试] 检查完成：共 {len(all_mem)} 条纪念日，"
                f"命中 {len(hit_list)} 条")

            if hit_list:
                theme = self.config.get("theme", DEFAULT_THEME) or DEFAULT_THEME
                # 先构造弹窗：构造失败（如主题缺字段、Qt 异常）不应
                # 消耗当天的提醒配额，让下一次调度能重试。
                try:
                    dlg = MemorialRemindDialog(hit_list, theme, self.parent)
                except Exception:
                    logger.exception(
                        "[提醒调试] 构造提醒弹窗失败，保留当日提醒配额")
                    return

                # 弹窗构造成功 → 落盘标记。取舍：若 exec 期间进程被强杀，
                # 标记已落盘、下次启动不重复弹；代价是弹窗异常时当天也
                # 不再提醒（可从日志感知）。反向做法在用户 kill 进程时
                # 会重弹，体验上比"漏弹一次"更糟，故不采用。
                self.config.set_nested(
                    "memorial_cfg", "last_remind_date", today_str, save=False)
                self.config.flush()
                logger.debug(f"[提醒调试] 已标记今日 {today_str} 为已提醒")

                sound_enable = self._get_bool_cfg(
                    self.config, "memorial_cfg", "sound_enable",
                    default=True)
                if sound_enable and self.sound_mgr:
                    self.sound_mgr.play("assets/alert.wav")

                dlg.exec()
                dlg.deleteLater()
            else:
                logger.debug("[提醒调试] 无命中提醒")
        finally:
            # 所有分支统一重排，避免定时器停摆。弹窗期间若定时器到期
            # 重入 check_memorial，会被 last_remind_date 早退拦截。
            try:
                self.reschedule(check_today=False)
            except Exception:
                logger.exception("[提醒调试] check_memorial 后重排失败")