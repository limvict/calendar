# coding: utf-8
"""
农历 / 节假日 / 公农历互转。

依赖：
- chinese_calendar：可选，节假日 / 工作日判断。
- cnlunar：可选，农历转换。

未安装依赖时降级，不抛导入错误。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple, Union

from config import get_logger

logger = get_logger()

__all__ = [
    "HAS_CHINESE_CAL",
    "HAS_CHNCAL",
    "is_holiday",
    "is_workday",
    "get_lunar_by_datetime",
    "lunar_to_gregorian",
    "qdate_to_pydate",
]

DateLike = Union[date, datetime, Tuple[int, int, int], List[int]]
LunarKey = Tuple[int, int, bool]

# ===================== 节假日本地库 =====================
HAS_CHINESE_CAL: bool

try:
    from chinese_calendar import is_holiday as _cc_is_holiday
    from chinese_calendar import is_workday as _cc_is_workday

    HAS_CHINESE_CAL = True
except Exception:  # noqa: BLE001
    logger.warning("未安装或加载 chinese_calendar 失败，使用周末降级判断")
    HAS_CHINESE_CAL = False

    def _to_date(d: Any) -> date:
        if isinstance(d, datetime):
            return d.date()
        if isinstance(d, date):
            return d
        if isinstance(d, (tuple, list)) and len(d) == 3:
            return date(int(d[0]), int(d[1]), int(d[2]))
        raise TypeError(f"不支持的日期类型: {type(d).__name__}")

    def _cc_is_holiday(d: Any, *args: Any, **kwargs: Any) -> bool:
        """降级：仅按周末判断，无法识别法定调休。"""
        return _to_date(d).weekday() >= 5

    def _cc_is_workday(d: Any, *args: Any, **kwargs: Any) -> bool:
        """降级：仅按周一至周五判断，无法识别法定调休。"""
        return _to_date(d).weekday() < 5


def is_holiday(d: Any, *args: Any, **kwargs: Any) -> bool:
    """判断是否为休息日。依赖可用时使用 chinese_calendar，否则按周末降级。"""
    return bool(_cc_is_holiday(d, *args, **kwargs))


def is_workday(d: Any, *args: Any, **kwargs: Any) -> bool:
    """判断是否为工作日。依赖可用时使用 chinese_calendar，否则按周末降级。"""
    return bool(_cc_is_workday(d, *args, **kwargs))


# ===================== 农历库 =====================
HAS_CHNCAL: bool

try:
    import cnlunar

    HAS_CHNCAL = True
except Exception:  # noqa: BLE001
    logger.warning("未安装或加载 cnlunar 失败，农历功能不可用")
    HAS_CHNCAL = False
    cnlunar = None  # type: ignore[assignment]


# ===================== 农历缓存 =====================
@lru_cache(maxsize=4096)
def _get_lunar_cached(y: int, m: int, d: int) -> Optional[Any]:
    """按公历年月日缓存农历对象。失败返回 None。"""
    if not HAS_CHNCAL or cnlunar is None:
        return None

    try:
        return cnlunar.Lunar(datetime(y, m, d), godType="8char")
    except Exception:  # noqa: BLE001
        logger.debug("农历转换降级 date=(%s, %s, %s)", y, m, d, exc_info=True)
        return None


def get_lunar_by_datetime(dt: DateLike) -> Optional[Any]:
    """
    获取公历日期对应的农历对象。

    :param dt: datetime.date / datetime.datetime / (y, m, d) 元组或列表
    :return: cnlunar.Lunar 对象；依赖不可用或转换失败时返回 None
    """
    if isinstance(dt, datetime):
        return _get_lunar_cached(dt.year, dt.month, dt.day)
    if isinstance(dt, date):
        return _get_lunar_cached(dt.year, dt.month, dt.day)

    if isinstance(dt, (tuple, list)) and len(dt) == 3:
        try:
            y, m, d = int(dt[0]), int(dt[1]), int(dt[2])
        except (TypeError, ValueError):
            logger.warning("get_lunar_by_datetime 元组参数无法转为整数: %r", dt)
            return None
        return _get_lunar_cached(y, m, d)

    logger.warning("get_lunar_by_datetime 参数类型不支持: %s", type(dt).__name__)
    return None


@lru_cache(maxsize=64)
# 【P3 修复】maxsize 32 → 64：跨年查询（如 12 月预取次年、
# 农历每年纪念日的 forward lookahead）会同时命中相邻两个农历年
# 的索引；扩到 64 减少换入换出，lru_cache 单条索引 ~400 天
# × 几十字节，内存开销可忽略。
def _build_lunar_index(lunar_year: int) -> Dict[LunarKey, date]:
    """
    构建"农历月/日/是否闰月 -> 公历 date"索引。

    农历年大致跨越公历 1 月中旬至次年 2 月下旬，因此扫描该区间。
    """
    if not HAS_CHNCAL:
        return {}

    index: Dict[LunarKey, date] = {}

    try:
        # 【P3 修复】起点从 1 月 15 日提前到 1 月 5 日。
        # 农历年最早的开始日（春节）历史极值在 1 月 21 日左右；
        # 提前到 1 月 5 日为极端年份（含闰月跨年）留更多余量，
        # 多扫描的天数在 lru_cache 命中下开销可忽略。
        start_date = date(lunar_year, 1, 5)
        end_date = date(lunar_year + 1, 2, 25)
    except ValueError:
        logger.warning("农历年份超出可处理范围: %s", lunar_year)
        return {}

    current = start_date
    while current <= end_date:
        lunar = _get_lunar_cached(current.year, current.month, current.day)
        if lunar is not None and getattr(lunar, "lunarYear", None) == lunar_year:
            try:
                key = (
                    int(getattr(lunar, "lunarMonth")),
                    int(getattr(lunar, "lunarDay")),
                    bool(getattr(lunar, "isLunarLeapMonth", False)),
                )
            except (AttributeError, TypeError, ValueError):
                current += timedelta(days=1)
                continue
            index.setdefault(key, current)
        current += timedelta(days=1)

    return index


@lru_cache(maxsize=1024)
def lunar_to_gregorian(
    lunar_year: int,
    lunar_month: int,
    lunar_day: int,
    is_leap_month: bool = False,
) -> Optional[date]:
    """
    农历转公历。

    :param lunar_year: 农历年
    :param lunar_month: 农历月（1-12）
    :param lunar_day: 农历日（1-30）
    :param is_leap_month: 是否为闰月
    :return: 对应公历 date；依赖不可用或找不到时返回 None
    """
    if not HAS_CHNCAL:
        return None

    try:
        y, m, d = int(lunar_year), int(lunar_month), int(lunar_day)
    except (TypeError, ValueError):
        logger.warning(
            "lunar_to_gregorian 参数无法转为整数: %r",
            (lunar_year, lunar_month, lunar_day),
        )
        return None

    if not (1 <= m <= 12 and 1 <= d <= 30):
        return None

    index = _build_lunar_index(y)
    return index.get((m, d, bool(is_leap_month)))


def qdate_to_pydate(qdate: Any) -> date:
    """
    将 Qt 的 QDate 转为 datetime.date。

    :raises TypeError: qdate 为 None 或缺少 year/month/day 方法
    :raises ValueError: 年月日不合法
    """
    if qdate is None:
        raise TypeError("qdate 不能为 None")

    try:
        return date(int(qdate.year()), int(qdate.month()), int(qdate.day()))
    except AttributeError as exc:
        raise TypeError(f"qdate 不是有效的 QDate: {type(qdate).__name__}") from exc