# coding: utf-8
"""
纪念日归一化、日期匹配、下次发生日期计算。
"""
import calendar
from datetime import date, datetime, timedelta
from typing import Optional

from config import get_logger
from lunar import get_lunar_by_datetime, lunar_to_gregorian, HAS_CHNCAL

logger = get_logger()

__all__ = [
    "REPEAT_YEAR", "REPEAT_MONTH", "REPEAT_WEEK",
    "normalize_memorial", "match_memorial_date", "get_next_memorial_date",
]

# 纪念日周期常量
REPEAT_YEAR = "year"
REPEAT_MONTH = "month"
REPEAT_WEEK = "week"

# 合法取值白名单
_VALID_REPEAT_TYPES = (REPEAT_YEAR, REPEAT_MONTH, REPEAT_WEEK)
_VALID_TYPES = ("solar", "lunar")

# 【P0 修复】农历"每年重复"向后搜索的年份窗口。
# 农历新年最晚可到公历 2 月下旬，因此用「基准日的农历年」及「农历年+1」
# 两个窗口即可覆盖任何一次"下一次的该农历月日"。
_LUNAR_YEAR_LOOKAHEAD = 2

# 【P1 修复】农历"每月重复"向后搜索的农历月窗口。
# 原 6 个月在极端情况（连续若干小月 + 目标日为月尾 30）下可能取不到，
# 直接返回 None 导致整月不提醒。13 个月足以跨过任何一年农历循环。
_LUNAR_MONTH_LOOKAHEAD = 13


def _to_pydate(qdate) -> date:
    """
    统一把 QDate / datetime / date 归一化为 datetime.date。
    """
    if isinstance(qdate, datetime):
        return qdate.date()
    if isinstance(qdate, date):
        return qdate
    if hasattr(qdate, "toPyDate"):
        return qdate.toPyDate()
    # 兜底：鸭子类型
    return date(qdate.year(), qdate.month(), qdate.day())


def normalize_memorial(mem: dict) -> dict:
    mem = mem.copy()
    defaults = {
        "name": "未命名纪念日",
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

    # 类型白名单校验
    if mem["repeat_type"] not in _VALID_REPEAT_TYPES:
        logger.warning(
            f"纪念日 repeat_type 非法：{mem['repeat_type']!r}，"
            f"已回落为 {REPEAT_YEAR}"
        )
        mem["repeat_type"] = REPEAT_YEAR

    # 每周重复是纯公历概念，强制 type='solar'，避免 UI 允许
    # "农历 + 每周重复"后行为与用户预期不符。
    if mem["repeat_type"] == REPEAT_WEEK:
        if mem.get("type") != "solar":
            logger.warning(
                f"纪念日 repeat_type=week 时 type 必须为 solar，"
                f"已从 {mem.get('type')!r} 修正为 'solar'"
            )
        mem["type"] = "solar"
        mem["isleap"] = False

    if mem["type"] not in _VALID_TYPES:
        logger.warning(
            f"纪念日 type 非法：{mem['type']!r}，已回落为 'solar'"
        )
        mem["type"] = "solar"

    try:
        mem["month"] = max(1, min(12, int(mem["month"])))
    except (TypeError, ValueError):
        mem["month"] = 1

    if mem["repeat_type"] == REPEAT_WEEK:
        # 周：1=周一 ~ 7=周日
        try:
            mem["day"] = max(1, min(7, int(mem["day"])))
        except (TypeError, ValueError):
            mem["day"] = 1
    else:
        # 农历日上限 30；公历日上限 31
        day_upper = 30 if mem["type"] == "lunar" else 31
        try:
            day = max(1, min(day_upper, int(mem["day"])))
        except (TypeError, ValueError):
            day = 1
        # 仅「公历 + 每年重复」时按实际月份天数收敛
        if mem["type"] == "solar" and mem["repeat_type"] == REPEAT_YEAR:
            try:
                _, last_day = calendar.monthrange(2024, mem["month"])
                day = min(day, last_day)
            except Exception:
                day = min(day, 28)
        mem["day"] = day

    # 【#8】advance_days 上限 365。
    # UI 的 QSpinBox 已限制 30，但配置文件是 JSON，可被手工改成任意大值，
    # 而 ReminderManager._calc_next_timestamp 会按 advance_days 逐个
    # 日期推进枚举；无上限时单条纪念日可让调度循环数万次。
    # 365 覆盖"提前一年提醒"的极端需求，同时把最坏复杂度钉死。
    try:
        mem["advance_days"] = max(0, min(365, int(mem["advance_days"])))
    except (TypeError, ValueError):
        mem["advance_days"] = 0

    mem["enabled"] = bool(mem.get("enabled", True))
    mem["isleap"] = bool(mem.get("isleap", False))
    return mem


def match_memorial_date(mem: dict, qdate) -> bool:
    """
    判断纪念日是否命中指定日期（支持年/月/周，公历/农历）。

    :param mem:   纪念日配置（内部会 normalize）
    :param qdate: PyQt6.QtCore.QDate / datetime.date / datetime.datetime
    """
    mem = normalize_memorial(mem)
    repeat_type = mem["repeat_type"]
    day = mem["day"]

    qdate = _to_pydate(qdate)
    y, m, d = qdate.year, qdate.month, qdate.day

    if repeat_type == REPEAT_WEEK:
        # 1=周一 ~ 7=周日
        return qdate.weekday() + 1 == day

    if repeat_type == REPEAT_MONTH:
        if mem["type"] == "solar":
            return d == day
        # 农历每月：只比农历日，不比月份（每月循环）
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
    【修复】返回严格大于 base_date 的下一个目标星期。

    原实现 `diff = (day - current) % 7` 在 day==current 时返回 base_date
    本身，导致 reminder_manager 里"今天还没到提醒时刻"的场景被 break
    跳过，该纪念日当天提醒彻底丢失。
    """
    current = base_date.weekday() + 1  # 1=周一 ~ 7=周日
    diff = (target_weekday - current) % 7
    if diff == 0:
        diff = 7
    return base_date + timedelta(days=diff)


def _next_solar_monthly(base_date: date, day: int) -> Optional[date]:
    """公历"每月重复"：返回 >= base_date（或 > base_date）的下一次。"""
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
    """公历"每年重复"：返回 >= base_date（或 > base_date）的下一次。"""
    for y in (base_date.year, base_date.year + 1):
        _, last_day = calendar.monthrange(y, month)
        target = date(y, month, min(day, last_day))
        if target > base_date:
            return target
    return None


def _next_lunar_monthly(base_date: date, day: int, is_leap: bool) -> Optional[date]:
    """农历"每月重复"：从基准农历月起向后找第一个农历 day 日。"""
    if not HAS_CHNCAL:
        logger.debug(
            f"农历每月：cnlunar 未安装，{base_date} 的纪念日无法计算"
        )
        return None
    lunar = get_lunar_by_datetime(
        (base_date.year, base_date.month, base_date.day)
    )
    if lunar is None:
        logger.warning(
            f"农历每月：基准日 {base_date} 无农历信息，无法推进"
        )
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
        f"未找到农历{day} 日（isleap={is_leap}），返回 None"
    )
    return None


def _next_lunar_yearly(base_date: date, month: int, day: int,
                       is_leap: bool) -> Optional[date]:
    """
    【P0 修复】农历"每年重复"：固定农历月 month，从基准农历年起查找。

    原实现误把"每月"逻辑复制到这里：只用 base_lm 起算、忽略 mem["month"]，
    于是"农历五月初五 端午"被算成"下个初五"（可能只是下个月），
    提醒日期完全错位。这里改为固定 month，仅推进农历年。
    """
    if not HAS_CHNCAL:
        logger.debug(
            f"农历每年：cnlunar 未安装，{base_date} 的纪念日无法计算"
        )
        return None
    lunar = get_lunar_by_datetime(
        (base_date.year, base_date.month, base_date.day)
    )
    if lunar is None:
        logger.warning(
            f"农历每年：基准日 {base_date} 无农历信息，无法推进"
        )
        return None
    base_ly = lunar.lunarYear
    for ly in range(base_ly, base_ly + _LUNAR_YEAR_LOOKAHEAD):
        g = lunar_to_gregorian(ly, month, day, is_leap)
        if g is None:
            continue
        if g > base_date:
            return g
    logger.warning(
        f"农历每年：从 {base_date} 起 {_LUNAR_YEAR_LOOKAHEAD} 个农历年内"
        f"未找到农历{month}月{day} 日（isleap={is_leap}），返回 None"
    )
    return None


def get_next_memorial_date(mem: dict, base_date,
                           include_base: bool = False) -> Optional[date]:
    """
    计算纪念日的下一个发生日期。

    :param base_date:    基准日期
    :param include_base: True 时允许返回 base_date 本身（命中当日）；
                         False（默认）时严格返回 > base_date 的日期。
    """
    if base_date is None:
        return None
    base_date = _to_pydate(base_date)

    mem = normalize_memorial(mem)
    repeat_type = mem["repeat_type"]
    day = mem["day"]

    # ===== 每周重复 =====
    if repeat_type == REPEAT_WEEK:
        if include_base and base_date.weekday() + 1 == day:
            return base_date
        return _next_week_date(base_date, day)

    # ===== 每月重复 =====
    if repeat_type == REPEAT_MONTH:
        if mem["type"] == "solar":
            candidate = _next_solar_monthly(base_date, day)
        else:
            candidate = _next_lunar_monthly(
                base_date, day, mem["isleap"]
            )
        if candidate is None:
            return None
        if include_base and candidate == base_date:
            return candidate
        return candidate if candidate > base_date else None

    # ===== 每年重复 =====
    if mem["type"] == "solar":
        candidate = _next_solar_yearly(base_date, mem["month"], day)
    else:
        candidate = _next_lunar_yearly(
            base_date, mem["month"], day, mem["isleap"]
        )
    if candidate is None:
        return None
    if include_base and candidate == base_date:
        return candidate
    return candidate if candidate > base_date else None