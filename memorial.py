# coding: utf-8
"""
纪念日归一化、日期匹配、下次发生日期计算。
"""
import calendar
from datetime import date, datetime, timedelta
from typing import Optional
from i18n import tr
from config import get_logger
from constants import REFERENCE_LEAP_YEAR, to_bool
import lunar as lunar_mod
from lunar import get_lunar_by_datetime, lunar_to_gregorian

logger = get_logger()

__all__ = [
    "REPEAT_YEAR", "REPEAT_MONTH", "REPEAT_WEEK",
    "normalize_memorial", "match_memorial_date", "get_next_memorial_date",
]

# 纪念日周期常量
REPEAT_YEAR = "year"
REPEAT_MONTH = "month"
REPEAT_WEEK = "week"

_VALID_REPEAT_TYPES = (REPEAT_YEAR, REPEAT_MONTH, REPEAT_WEEK)
_VALID_TYPES = ("solar", "lunar")

# 农历"每年重复"向后搜索的年份窗口。
#
# 农历闰月间隔可达 19 年（闰月周期近似 19 年 7 闰，但"特定月的闰月"
# 最长间隔可达 30+ 年）。3 年窗口会让"农历闰四月十五"这类配置在无
# 闰月年份里连续多次返回 None。5 年是覆盖常见闰月密集期的折中。
#
# 语义边界：本窗口是"单次搜索的深度边界"，窗口内找不到目标日即返回
# None；reminder_manager.MAX_RETRY_PER_MEMORIAL 是"候选日期已过后的
# 推进次数"，不能扩展本窗口的搜索深度。
_LUNAR_YEAR_LOOKAHEAD = 5

# 农历"每月重复"向后搜索的农历月窗口。13 个月足以跨过任何一年农历
# 循环（原 6 个月在连续若干小月 + 目标日为月尾 30 时可能取不到）。
# 语义边界同 _LUNAR_YEAR_LOOKAHEAD。
_LUNAR_MONTH_LOOKAHEAD = 13


def _to_pydate(qdate) -> date:
    """统一把 QDate / datetime / date 归一化为 datetime.date。"""
    if isinstance(qdate, datetime):
        return qdate.date()
    if isinstance(qdate, date):
        return qdate
    if hasattr(qdate, "toPyDate"):
        return qdate.toPyDate()
    return date(qdate.year(), qdate.month(), qdate.day())


def normalize_memorial(mem: dict) -> dict:
    mem = mem.copy()
    defaults = {
        "name": tr("memorial.default_name"),
        "type": "solar",
        "month": 1,
        "day": 1,
        "enabled": True,
        "advance_days": 0,
        "repeat_type": REPEAT_YEAR,
        "isleap": False,
    }
    for k, v in defaults.items():
        if k not in mem or mem[k] is None:
            mem[k] = v

    if mem["repeat_type"] not in _VALID_REPEAT_TYPES:
        logger.warning(
            f"纪念日 repeat_type 非法：{mem['repeat_type']!r}，"
            f"已回落为 {REPEAT_YEAR}")
        mem["repeat_type"] = REPEAT_YEAR

    # 每周重复是纯公历概念，强制 type='solar'，避免 UI 允许
    # "农历 + 每周重复"后行为与用户预期不符。
    if mem["repeat_type"] == REPEAT_WEEK:
        if mem.get("type") != "solar":
            logger.warning(
                f"纪念日 repeat_type=week 时 type 必须为 solar，"
                f"已从 {mem.get('type')!r} 修正为 'solar'")
        mem["type"] = "solar"
        mem["isleap"] = False

    if mem["type"] not in _VALID_TYPES:
        logger.warning(
            f"纪念日 type 非法：{mem['type']!r}，已回落为 'solar'")
        mem["type"] = "solar"

    try:
        mem["month"] = max(1, min(12, int(mem["month"])))
    except (TypeError, ValueError):
        mem["month"] = 1

    if mem["repeat_type"] == REPEAT_WEEK:
        try:
            mem["day"] = max(1, min(7, int(mem["day"])))  # 1=周一 ~ 7=周日
        except (TypeError, ValueError):
            mem["day"] = 1
    else:
        day_upper = 30 if mem["type"] == "lunar" else 31
        try:
            day = max(1, min(day_upper, int(mem["day"])))
        except (TypeError, ValueError):
            day = 1
        # 仅"公历 + 每年重复"时按实际月份天数收敛
        if mem["type"] == "solar" and mem["repeat_type"] == REPEAT_YEAR:
            try:
                _, last_day = calendar.monthrange(
                    REFERENCE_LEAP_YEAR, mem["month"])
                day = min(day, last_day)
            except Exception:
                day = min(day, 28)
        mem["day"] = day

    # advance_days 上限 365。UI 的 QSpinBox 已限制 30，但配置文件是
    # JSON，可被手工改成任意大值，而 ReminderManager._calc_next_timestamp
    # 会按 advance_days 逐个日期推进枚举；无上限时单条纪念日可让调度
    # 循环数万次。365 覆盖"提前一年提醒"的极端需求，同时把最坏复杂度
    # 钉死。
    try:
        mem["advance_days"] = max(0, min(365, int(mem["advance_days"])))
    except (TypeError, ValueError):
        mem["advance_days"] = 0

    mem["enabled"] = to_bool(mem.get("enabled"), default=True)
    mem["isleap"]  = to_bool(mem.get("isleap"), default=False)
    return mem


def match_memorial_date(mem: dict, qdate, normalized: bool = False) -> bool:
    """
    :param normalized: 若调用方已 normalize 过（同一次调度循环内），
        传 True 跳过重复 normalize（省去 copy + clamp 开销）。
    """
    if not normalized:
        mem = normalize_memorial(mem)
    repeat_type = mem["repeat_type"]
    day = mem["day"]

    qdate = _to_pydate(qdate)
    y, m, d = qdate.year, qdate.month, qdate.day

    if repeat_type == REPEAT_WEEK:
        return qdate.weekday() + 1 == day  # 1=周一 ~ 7=周日

    if repeat_type == REPEAT_MONTH:
        if mem["type"] == "solar":
            return d == day
        # 农历每月：只比农历日，不比月份
        lunar = get_lunar_by_datetime((y, m, d))
        if not lunar:
            return False
        return (lunar.lunarDay == day
                and lunar.isLunarLeapMonth == mem.get("isleap", False))

    # REPEAT_YEAR
    if mem["type"] == "solar":
        return m == mem["month"] and d == day
    lunar = get_lunar_by_datetime((y, m, d))
    if not lunar:
        return False
    return (lunar.lunarMonth == mem["month"]
            and lunar.lunarDay == day
            and lunar.isLunarLeapMonth == mem.get("isleap", False))


def _next_week_date(base_date: date, target_weekday: int) -> date:
    """
    返回严格大于 base_date 的下一个目标星期。

    必须严格大于（diff==0 时推 7 天）：否则 reminder_manager 中
    "今天还没到提醒时刻"的场景会被 break 跳过，当天提醒彻底丢失。
    """
    current = base_date.weekday() + 1
    diff = (target_weekday - current) % 7
    if diff == 0:
        diff = 7
    return base_date + timedelta(days=diff)


def _next_solar_monthly(base_date: date, day: int) -> Optional[date]:
    """公历"每月重复"：返回 > base_date 的下一次。"""
    for offset in (0, 1):
        total = base_date.month + offset - 1
        y = base_date.year + total // 12
        m = total % 12 + 1
        _, last_day = calendar.monthrange(y, m)
        target = date(y, m, min(day, last_day))
        if target > base_date:
            return target
    return None


def _next_solar_yearly(base_date: date, month: int, day: int) -> Optional[date]:
    """
    公历"每年重复"：返回严格 > base_date 的下一次。

    搜索窗口取 5 年：兼容"2/29 + base_date 恰为某年 2/29"这种需要跨到
    下一个闰年才有候选的情况（原 2 年窗口会返回 None），并覆盖
    monthrange 收敛引入的其它稀疏日期。
    """
    for offset in range(5):
        y = base_date.year + offset
        _, last_day = calendar.monthrange(y, month)
        target = date(y, month, min(day, last_day))
        if target > base_date:
            return target
    return None


def _next_lunar_monthly(base_date: date, day: int, is_leap: bool) -> Optional[date]:
    """农历"每月重复"：从基准农历月起向后找第一个农历 day 日。"""
    if not lunar_mod.HAS_CHNCAL:
        logger.debug(f"农历每月：cnlunar 未安装，{base_date} 的纪念日无法计算")
        return None
    lunar = get_lunar_by_datetime(
        (base_date.year, base_date.month, base_date.day))
    if lunar is None:
        logger.warning(f"农历每月：基准日 {base_date} 无农历信息，无法推进")
        return None
    base_ly = lunar.lunarYear
    base_lm = lunar.lunarMonth
    for offset in range(_LUNAR_MONTH_LOOKAHEAD):
        total = base_lm + offset - 1
        ly = base_ly + total // 12
        lm = total % 12 + 1
        g = lunar_to_gregorian(ly, lm, day, is_leap)
        if g is None:
            continue
        if g > base_date:
            return g
    logger.warning(
        f"农历每月：从 {base_date} 起 {_LUNAR_MONTH_LOOKAHEAD} 个农历月内"
        f"未找到农历{day} 日（isleap={is_leap}），返回 None")
    return None


def _next_lunar_yearly(base_date, month, day, is_leap):
    if not lunar_mod.HAS_CHNCAL:
        logger.debug(f"农历每年：cnlunar 未安装，{base_date} 的纪念日无法计算")
        return None

    # 不依赖基准日的农历年，从公历年 -1 开始试，覆盖跨农历年
    start_year = base_date.year - 1
    for gy in range(start_year, start_year + _LUNAR_YEAR_LOOKAHEAD):
        g = lunar_to_gregorian(gy, month, day, is_leap)
        if g is None:
            continue
        if g > base_date:
            return g

    logger.warning(
        f"农历每年：从 {base_date} 起 {_LUNAR_YEAR_LOOKAHEAD} 个农历年内"
        f"未找到农历{month}月{day} 日（isleap={is_leap}），返回 None")
    return None


def get_next_memorial_date(mem, base_date, include_base=False,
                           normalized=False):
    """
    :param normalized: 若调用方已 normalize 过，传 True 跳过重复 normalize；
        默认 False 兼容旧调用点。
    """
    if base_date is None:
        return None
    base_date = _to_pydate(base_date)

    if not normalized:
        mem = normalize_memorial(mem)
    repeat_type = mem["repeat_type"]
    day = mem["day"]

    if repeat_type == REPEAT_WEEK:
        if include_base and base_date.weekday() + 1 == day:
            return base_date
        return _next_week_date(base_date, day)

    if repeat_type == REPEAT_MONTH:
        if mem["type"] == "solar":
            if include_base and base_date.day == day:
                return base_date
            candidate = _next_solar_monthly(base_date, day)
        else:
            if include_base and _matches_lunar_monthly(
                    base_date, day, mem["isleap"]):
                return base_date
            candidate = _next_lunar_monthly(base_date, day, mem["isleap"])
        return candidate

    if mem["type"] == "solar":
        if (include_base and base_date.month == mem["month"]
                and base_date.day == day):
            return base_date
        candidate = _next_solar_yearly(base_date, mem["month"], day)
    else:
        if include_base and _matches_lunar_yearly(
                base_date, mem["month"], day, mem["isleap"]):
            return base_date
        candidate = _next_lunar_yearly(
            base_date, mem["month"], day, mem["isleap"])
    return candidate


def _matches_lunar_monthly(base_date, day, is_leap):
    lunar = get_lunar_by_datetime(
        (base_date.year, base_date.month, base_date.day))
    if lunar is None:
        return False
    if getattr(lunar, "lunarDay", None) != day:
        return False
    if bool(getattr(lunar, "isLunarLeapMonth", False)) != bool(is_leap):
        return False
    return True


def _matches_lunar_yearly(base_date, month, day, is_leap):
    lunar = get_lunar_by_datetime(
        (base_date.year, base_date.month, base_date.day))
    if lunar is None:
        return False
    if (getattr(lunar, "lunarMonth", None) != month
            or getattr(lunar, "lunarDay", None) != day):
        return False
    if bool(getattr(lunar, "isLunarLeapMonth", False)) != bool(is_leap):
        return False
    return True