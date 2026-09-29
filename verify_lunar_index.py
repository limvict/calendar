# coding: utf-8
"""校验 P2-1：新版索引化 lunar_to_gregorian 与旧版线性实现结果一致。"""
import calendar
from datetime import date, timedelta

from lunar import _get_lunar_cached, lunar_to_gregorian


def old_lunar_to_gregorian(ly, lm, ld, is_leap=False):
    """复制旧版线性实现做对照。"""
    start = date(ly, 1, 1)
    end = date(ly + 1, 2, calendar.monthrange(ly + 1, 2)[1])
    cur = start
    while cur <= end:
        lunar = _get_lunar_cached(cur.year, cur.month, cur.day)
        if lunar and (lunar.lunarMonth == lm
                      and lunar.lunarDay == ld
                      and lunar.isLunarLeapMonth == is_leap):
            return cur
        cur += timedelta(days=1)
    return None


if __name__ == "__main__":
    mismatch = 0
    checked = 0
    for year in (2024, 2025, 2026):
        for lm in range(1, 13):
            for ld in (1, 15, 29, 30):
                for leap in (False, True):
                    a = old_lunar_to_gregorian(year, lm, ld, leap)
                    b = lunar_to_gregorian(year, lm, ld, leap)
                    checked += 1
                    if a != b:
                        mismatch += 1
                        print(f"DIFF y={year} m={lm} d={ld} leap={leap}: "
                              f"old={a} new={b}")
    print(f"checked={checked}, mismatch={mismatch}")