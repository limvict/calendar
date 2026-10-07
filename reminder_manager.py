# coding: utf-8
from datetime import datetime
from PyQt6.QtCore import QObject, QTimer, QDate, QTime
from config import ConfigManager, get_logger
from constants import DEFAULT_THEME
from utils import get_next_memorial_date
from dialogs import MemorialRemindDialog
from memorial import normalize_memorial

logger = get_logger()


class ReminderManager(QObject):
    """提醒管理器：统一处理纪念日判定与调度"""
    # QTimer 32位int溢出保护：最大约24.8天，超过则按24天分段调度
    MAX_DELAY_MS = 24 * 24 * 60 * 60 * 1000

    # 【P2 修复】原 MAX_LOOKAHEAD 的语义含混：注释说是"每个纪念日最多
    # 枚举的未来周期数"，但实际循环体在 get_next_memorial_date 返回
    # None 时就 break —— 也就是"最多尝试几个候选目标日期"。重命名为
    # MAX_RETRY_PER_MEMORIAL 后语义与实现一致。
    # 保留 MAX_LOOKAHEAD 作为别名，避免外部（如有）引用失效。
    MAX_RETRY_PER_MEMORIAL = 4
    MAX_LOOKAHEAD = MAX_RETRY_PER_MEMORIAL
    
    def __init__(self, parent_widget, config: ConfigManager, sound_manager=None):
        super().__init__(parent_widget)
        self.parent = parent_widget
        self.config = config
        self.sound_mgr = sound_manager
        self._remind_timer = QTimer(self)
        self._remind_timer.setSingleShot(True)
        self._remind_timer.timeout.connect(self._on_trigger)
        self._is_scheduling = False  # 防重入标记

    # ------------------------------------------------------------------ #
    # 配置读取工具
    # ------------------------------------------------------------------ #
    @staticmethod
    def _get_int_cfg(cfg, *keys, default: int):
        # [FIX] 兼容浮点/字符串等非严格 int 配置，避免静默回退默认值
        val = cfg.get_nested(*keys, default=default)
        if isinstance(val, bool):
            return default
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _get_bool_cfg(cfg, *keys, default: bool):
        """安全读取布尔配置，兼容数字/字符串/None等各种异常值"""
        val = cfg.get_nested(*keys, default=default)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        if isinstance(val, int):
            return bool(val)
        if isinstance(val, str):
            low = val.strip().lower()
            if low in ("true", "1", "yes", "on"):
                return True
            if low in ("false", "0", "no", "off"):
                return False
        return default

    # ------------------------------------------------------------------ #
    # 调度入口
    # ------------------------------------------------------------------ #
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
            enable_remind = self._get_bool_cfg(self.config, "memorial_cfg", "enable_remind", default=True)
            if not enable_remind:
                self._remind_timer.stop()
                logger.debug("[提醒调试] 提醒总开关关闭，定时器停止")
                return

            if check_today:
                self.check_memorial()

            next_ts = self._calc_next_timestamp()
            if next_ts is None:
                self._remind_timer.stop()
                logger.debug("[提醒调试] 无未来提醒事件，定时器已停止")
                return

            now_ms = int(datetime.now().timestamp() * 1000)
            delta_ms = next_ts - now_ms

            if delta_ms > self.MAX_DELAY_MS:
                # 超过最大定时器时长，分段调度；分段触发只重算时间，不做当日提醒
                self._remind_timer.start(self.MAX_DELAY_MS)
                logger.debug("[提醒调试] 下次提醒间隔超过24天，采用分段调度")
                return

            delay = max(0, delta_ms)
            self._remind_timer.start(delay)
            next_time = datetime.fromtimestamp(next_ts / 1000).strftime("%Y-%m-%d %H:%M:%S")
            logger.debug(
                f"[提醒调试] 下一次提醒已调度：{next_time}，延迟 {delay / 1000:.0f} 秒"
            )

        except Exception as e:
            logger.error(f"[提醒调试] reschedule调度失败：{e}")
            import traceback
            logger.error(traceback.format_exc())
            self._remind_timer.stop()
        finally:
            self._is_scheduling = False

    # ------------------------------------------------------------------ #
    # 下一个提醒时间戳
    # ------------------------------------------------------------------ #
    def _calc_next_timestamp(self):
        """计算所有纪念日最近的未来提醒时间戳(ms)，没有返回None"""
        candidates = []
        now_ms = int(datetime.now().timestamp() * 1000)
        today_q = QDate.currentDate()
        remind_h = self._get_int_cfg(
            self.config, "memorial_cfg", "remind_start_hour", default=8
        )

        for mem in self.config.get("memorial_days", []):
            if not isinstance(mem, dict) or not mem.get("enabled", True):
                continue
            mem = normalize_memorial(mem) 
            try:
                advance_days = max(0, int(mem.get("advance_days", 0)))
            except (TypeError, ValueError):
                advance_days = 0

            search_base = today_q
            for _ in range(self.MAX_RETRY_PER_MEMORIAL):
                target_date = get_next_memorial_date(
                    mem, search_base, include_base=True
                )
                if target_date is None:
                    # 【P2 修复】原实现静默 break，导致"农历每年"因数据
                    # 异常无候选时，用户完全感知不到提醒被跳过。
                    # 这里补一条 debug，排查时开 DEBUG 即可定位。
                    logger.debug(
                        f"[提醒调试] {mem.get('name', '未命名')}："
                        f"从 {search_base} 起无可计算的候选日期，跳过"
                    )
                    break
                target = QDate(target_date.year, target_date.month, target_date.day)
                first_alert_day = target.addDays(-advance_days)
                if first_alert_day < today_q:
                    first_alert_day = today_q

                scheduled = False
                cur_day = first_alert_day
                while cur_day <= target:
                    dt = datetime(cur_day.year(), cur_day.month(), cur_day.day(),
                                  remind_h, 0, 0)
                    ts = int(dt.timestamp() * 1000)
                    if ts > now_ms:
                        candidates.append(ts)
                        scheduled = True
                        break
                    cur_day = cur_day.addDays(1)

                if scheduled:
                    break
                search_base = target.addDays(1)

        if not candidates:
            return None
        return min(candidates)

    # ------------------------------------------------------------------ #
    # 定时触发
    # ------------------------------------------------------------------ #
    def _on_trigger(self):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.debug(f"[提醒调试] 定时器触发，时间：{now_str}")
        try:
            self.check_memorial()
        except Exception:
            logger.exception("[提醒调试] check_memorial 异常，本次检查跳过")
        finally:
            # 无论 check 是否成功，都要重排，否则定时器停摆
            try:
                self.reschedule(check_today=False)
            except Exception:
                logger.exception("[提醒调试] reschedule 异常")

    # ------------------------------------------------------------------ #
    # 当日提醒检查
    # ------------------------------------------------------------------ #
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
            self.config, "memorial_cfg", "remind_start_hour", default=8
        )
        end_h = self._get_int_cfg(
            self.config, "memorial_cfg", "remind_end_hour", default=22
        )
        now_hour = QTime.currentTime().hour()
        logger.debug(
            f"[提醒调试] 提醒时间范围：{start_h}:00 ~ {end_h}:00，当前小时：{now_hour}"
        )

        if not (start_h <= now_hour < end_h):
            logger.debug("[提醒调试] 当前不在提醒时间范围内，跳过")
            return

        hit_list = []
        all_mem = self.config.get("memorial_days", [])
        logger.debug(f"[提醒调试] 共读取到 {len(all_mem)} 个纪念日配置，开始匹配...")

        for idx, mem in enumerate(all_mem):
            if not isinstance(mem, dict):
                logger.debug(f"[提醒调试] [{idx+1}] 空配置项，跳过")
                continue
            mem = normalize_memorial(mem)  
            if not mem.get("enabled", True):
                logger.debug(
                    f"[提醒调试] [{idx+1}] {mem.get('name', '未命名')}：已禁用，跳过"
                )
                continue

            target_date = get_next_memorial_date(mem, today, include_base=True)
            if target_date is None:
                logger.debug(
                    f"[提醒调试] [{idx+1}] {mem.get('name', '未命名')}：无法计算目标日期，跳过"
                )
                continue

            target = QDate(target_date.year, target_date.month, target_date.day)
            diff = today.daysTo(target)

            try:
                advance_days = max(0, int(mem.get("advance_days", 0)))
            except (TypeError, ValueError):
                advance_days = 0

            target_str = target.toString("yyyy-MM-dd")
            logger.debug(
                f"[提醒调试] [{idx+1}] {mem.get('name', '未命名')}：目标日期{target_str}，距离今日{diff}天，提前提醒{advance_days}天"
            )

            if 0 <= diff <= advance_days:
                name = mem.get("name", "未命名纪念日")   # ← 用 .get
                hit_text = name if diff == 0 else f"{name}，还有{diff}天"
                hit_list.append(hit_text)
                logger.debug(f"[提醒调试]  ✅ 命中提醒：{hit_text}")

        logger.debug(f"[提醒调试] 匹配完成，共命中 {len(hit_list)} 个提醒：{hit_list}")
        if hit_list:
            sound_enable = self._get_bool_cfg(
                self.config, "memorial_cfg", "sound_enable", default=True
            )
            logger.debug(
                f"[提醒调试] 声音开关：{sound_enable}，声音管理器是否可用：{self.sound_mgr is not None}"
            )
            if sound_enable and self.sound_mgr:
                logger.debug("[提醒调试] 🔊 播放提醒音效")
                self.sound_mgr.play("assets/alert.wav")

            theme = self.config.get("theme", DEFAULT_THEME) or DEFAULT_THEME
            # 先写入标记落盘，再弹窗；防止弹窗中关闭程序造成重复提醒
            self.config.set_nested("memorial_cfg", "last_remind_date", today_str, save=False)
            self.config.flush()
            logger.debug(f"[提醒调试] 已标记今日 {today_str} 为已提醒")
            logger.debug("[提醒调试] 🪟 弹出提醒对话框")

            dlg = MemorialRemindDialog(hit_list, theme, self.parent)
            try:
                dlg.exec()
            finally:
                logger.debug("========== [提醒调试] 本次检查结束 ==========\n")
        else:
            logger.debug("[提醒调试] 无命中提醒，本次检查结束\n")
