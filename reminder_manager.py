# coding: utf-8
# ⚠️ 本文件有改动：P0-2 reschedule 默认 check_today=False；
#                  P1-2 预归一化；P1-3 O(1) 定位首个未来提醒时刻；
#                  P2-2 删除 MAX_LOOKAHEAD 别名
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

    # 【P2 修复】每个纪念日最多尝试的候选周期数。
    #
    # 触发场景：get_next_memorial_date 返回的候选日期在当前时刻已过
    # （例：今天命中但 remind_start_hour 已过），需要推进 search_base
    # 到下一周期重新取候选。
    #
    # 对每周/每月/每年重复，1 次推进足够；4 次是防御性冗余。
    #
    # 【FIX-5 与 memorial._LUNAR_*_LOOKAHEAD 的关系】语义正交，不可互相替代：
    # 那两个常量是"单次搜索的深度边界"（农历 13 个月 / 5 年），
    # 本常量是"候选已过后的推进次数"。
    # 换句话说：本常量不能扩展农历单次搜索的窗口深度。
    MAX_RETRY_PER_MEMORIAL = 4
    # 【P2-2】删除 MAX_LOOKAHEAD 别名（无外部引用）

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
    def _get_int_cfg(cfg, *keys, default: int, lo: int = None, hi: int = None):
        # [FIX] 兼容浮点/字符串等非严格 int 配置，避免静默回退默认值。
        # lo / hi 为可选边界：越界时夹取到边界（而非回退 default），
        # 保留用户"深夜/凌晨"等意图，与 normalize_memorial 的夹取风格一致。
        # [FIX-1] 新增 lo / hi 参数，供小时类字段防 25/-1 等越界值。
        val = cfg.get_nested(*keys, default=default)
        if isinstance(val, bool):
            # bool 是 int 子类，必须优先拦截，否则 True→1 / False→0
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
        """安全读取布尔配置，兼容数字/字符串/None等各种异常值"""
        val = cfg.get_nested(*keys, default=default)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        # int 是 bool 子类，上面已拦截；这里合并 int/float，
        # 避免 JSON 手改成 1.0 / 0.0 时静默回退 default（关不掉的提醒）。
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
    # 预归一化工具（P1-2）
    # ------------------------------------------------------------------ #
    def _normalized_enabled_list(self):
        """
        【P1-2】读取 memorial_days 并全表归一化一次，
        过滤掉非 dict / normalize 失败 / 已禁用 的条目。
        调用方循环内不必再 normalize。
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
            if n.get("enabled", True):
                result.append(n)
        return result

    # ------------------------------------------------------------------ #
    # 调度入口
    # ------------------------------------------------------------------ #
    def reschedule(self, force: bool = False, check_today: bool = False):
        """
        重新计算并调度下一次提醒
        :param force: 强制刷新，忽略防重入（配置变更时调用）
        :param check_today: 是否立刻执行一次"当日提醒检查"。
            【P0-2】默认 False —— 只有"用户显式动作"（如应用设置、
            从文件恢复）才需传入 True。启动、配置刷新等非用户主动
            场景静默重排，避免误弹提醒窗。
        """
        if self._is_scheduling and not force:
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
                # [FIX-2] 原实现同步调用 check_memorial()，其内部
                # MemorialRemindDialog.exec() 是模态阻塞，会把本函数的
                # 定时器重排推迟到用户关闭弹窗之后；期间若定时器到期，
                # 还会重入 check_memorial。改为投递到事件循环下一轮，
                # 让 reschedule 立即完成定时器重排，弹窗独立弹出。
                QTimer.singleShot(0, self.check_memorial)

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
    # 【P1-3】O(1) 定位首个未来提醒时刻
    # ------------------------------------------------------------------ #
    @staticmethod
    def _first_future_remind_ts(first_alert_qd, target_qd, remind_h, now_ms):
        """
        在 [first_alert_qd, target_qd] 内找"第一个未过的 remind_h:00"
        时间戳；全部已过返回 None。

        等价于原实现"逐日构造 datetime 并比较"的循环，但利用
        "提醒时刻固定为 remind_h:00"这一事实，用 O(1) 定位：
          start = max(first_alert_qd, today)
          若 start == today 且当前小时 >= remind_h，则 start += 1 天
        start > target_qd 表示全部错过。
        """
        now_dt = datetime.now()
        today_qd = QDate(now_dt.year, now_dt.month, now_dt.day)
        start = first_alert_qd if first_alert_qd > today_qd else today_qd
        if start == today_qd and now_dt.hour >= remind_h:
            start = start.addDays(1)
        if start > target_qd:
            return None
        dt = datetime(start.year(), start.month(), start.day(),
                      remind_h, 0, 0)
        ts = int(dt.timestamp() * 1000)
        return ts if ts > now_ms else None

    # ------------------------------------------------------------------ #
    # 下一个提醒时间戳
    # ------------------------------------------------------------------ #
    def _calc_next_timestamp(self):
        """计算所有纪念日最近的未来提醒时间戳(ms)，没有返回None"""
        candidates = []
        now_ms = int(datetime.now().timestamp() * 1000)
        today_q = QDate.currentDate()
        # [FIX-1] 加 lo/hi：remind_start_hour 若被配置文件改成 25/-1，
        # 会让 datetime(..., 25, 0, 0) 抛 ValueError，进而触发 reschedule
        # 的 except 分支停掉定时器，提醒永久停摆。
        remind_h = self._get_int_cfg(
            self.config, "memorial_cfg", "remind_start_hour",
            default=8, lo=0, hi=23,
        )

        # 【P1-2】全表先 normalize 一次，后续 get_next_memorial_date 全部
        # 传 normalized=True，避免每条纪念日被 normalize 3 遍。
        normalized = self._normalized_enabled_list()

        for mem in normalized:
            try:
                advance_days = max(0, int(mem.get("advance_days", 0)))
            except (TypeError, ValueError):
                advance_days = 0

            search_base = today_q
            for _ in range(self.MAX_RETRY_PER_MEMORIAL):
                target_date = get_next_memorial_date(
                    mem, search_base, include_base=True, normalized=True,
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
                target = QDate(target_date.year, target_date.month,
                               target_date.day)
                first_alert_day = target.addDays(-advance_days)
                if first_alert_day < today_q:
                    first_alert_day = today_q

                # 【P1-3】O(1) 定位首个未来提醒时刻
                ts = self._first_future_remind_ts(
                    first_alert_day, target, remind_h, now_ms)
                if ts is not None:
                    candidates.append(ts)
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
        # get("memorial_cfg", {}) 在“键存在但值为 None”时返回 None，
        # 下面 .get("last_remind_date") 会 AttributeError；
        # 显式做类型兜底，避免依赖上游 _migrate 一定跑过。
        memorial_cfg = self.config.get("memorial_cfg")
        if not isinstance(memorial_cfg, dict):
            memorial_cfg = {}
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

        # [FIX-1] 加 lo/hi：start 上限 23，end 上限 24（含"到 24 点"语义）。
        # 保证 start_h <= now_hour < end_h 的判断在越界配置下依然成立。
        start_h = self._get_int_cfg(
            self.config, "memorial_cfg", "remind_start_hour",
            default=8, lo=0, hi=23,
        )
        end_h = self._get_int_cfg(
            self.config, "memorial_cfg", "remind_end_hour",
            default=22, lo=0, hi=24,
        )
        now_hour = QTime.currentTime().hour()
        logger.debug(
            f"[提醒调试] 提醒时间范围：{start_h}:00 ~ {end_h}:00，当前小时：{now_hour}"
        )

        if not (start_h <= now_hour < end_h):
            logger.debug("[提醒调试] 当前不在提醒时间范围内，跳过")
            return

        hit_list = []
        # 【P1-2】全表先 normalize 一次，循环内传 normalized=True
        all_mem = self._normalized_enabled_list()
        logger.debug(f"[提醒调试] 共读取到 {len(all_mem)} 个纪念日配置，开始匹配...")

        for idx, mem in enumerate(all_mem):
            target_date = get_next_memorial_date(
                mem, today, include_base=True, normalized=True)
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
                name = mem.get("name", "未命名纪念日")
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