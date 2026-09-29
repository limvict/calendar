# coding: utf-8
"""
农历 / 节假日 / 公农历互转。

从原 utils.py 拆分出来，utils.py 仍会重新导出下列所有符号以兼容旧代码。
"""
import calendar
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Optional

from config import get_logger, log_exception

logger=get_logger()

__all__ = [
    "HAS_CHINESE_CAL", "HAS_CHNCAL",
    "is_holiday", "is_workday",
    "get_lunar_by_datetime", "lunar_to_gregorian", "qdate_to_pydate",
]

# ===================== 节假日本地库 =====================
try:
    from chinese_calendar import is_holiday, is_workday
    HAS_CHINESE_CAL = True
except ImportError:
    logger.warning("未安装 chinese_calendar，本地节假日判断不可用")
    HAS_CHINESE_CAL = False

    def is_holiday(*args, **kwargs): return False
    def is_workday(*args, **kwargs): return True

# ===================== 农历库 =====================
try:
    import cnlunar
    HAS_CHNCAL = True
except ImportError:
    logger.warning("未安装 cnlunar，农历节气功能不可用")
    HAS_CHNCAL = False


# ===================== 农历缓存 =====================
@lru_cache(maxsize=512)
def _get_lunar_cached(y: int, m: int, d: int):
    if not HAS_CHNCAL:
        return None
    try:
        return cnlunar.Lunar(datetime(y, m, d), godType='8char')
    except Exception:
        logger.debug(f"农历转换降级 date={(y, m, d)}", exc_info=True)
        return None


def get_lunar_by_datetime(dt):
    """
    获取公历日期对应的农历对象。
    :param dt: datetime.date / datetime.datetime / (y, m, d) 元组
    """
    if isinstance(dt, (date, datetime)):
        return _get_lunar_cached(dt.year, dt.month, dt.day)
    if isinstance(dt, (tuple, list)) and len(dt) == 3:
        return _get_lunar_cached(int(dt[0]), int(dt[1]), int(dt[2]))
    log_exception(
        f"get_lunar_by_datetime 参数类型不支持: {type(dt).__name__}")
    return None


# ===================== 农历年反向索引 =====================
@lru_cache(maxsize=8)
def _build_lunar_index(lunar_year: int) -> dict:
    """
    为指定农历年构建反向索引：
        key   = (lunar_month, lunar_day, is_leap)
        value = gregorian date

    【修复】原实现 end_date 取 lunar_year+1 年 2 月末。若春节很晚
    （历史上出现过 2 月下旬甚至 3 月），农历 lunar_year 的腊月会
    延续到 lunar_year+1 年 2 月之后，导致腊月末尾几天漏掉。
    这里把扫描窗口放宽到 lunar_year+1 年 4 月末，确保覆盖完整。
    """
    if not HAS_CHNCAL:
        return {}

    index = {}
    start_date = date(lunar_year, 1, 1)
    end_date = date(
        lunar_year + 1, 4,
        calendar.monthrange(lunar_year + 1, 4)[1],
    )
    current = start_date
    while current <= end_date:
        lunar = _get_lunar_cached(current.year, current.month, current.day)
        if lunar is not None:
            key = (lunar.lunarMonth, lunar.lunarDay,
                   bool(lunar.isLunarLeapMonth))
            index.setdefault(key, current)
        current += timedelta(days=1)
    return index


def lunar_to_gregorian(lunar_year, lunar_month, lunar_day,
                       is_leap_month=False) -> Optional[date]:
    """
    农历转公历。
    """
    if not HAS_CHNCAL:
        return None

    index = _build_lunar_index(int(lunar_year))
    return index.get((int(lunar_month), int(lunar_day), bool(is_leap_month)))


def qdate_to_pydate(qdate) -> date:
    return date(qdate.year(), qdate.month(), qdate.day())