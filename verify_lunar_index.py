# coding: utf-8
"""
回归测试：新版索引化 lunar_to_gregorian 与旧版线性实现结果一致。

运行方式：
    - 有 pytest：  pytest verify_lunar_index.py -v
    - 无 pytest：  python verify_lunar_index.py

覆盖 3 个年份 × 12 个月 × 4 个典型日 × 闰月/非闰月 = 288 组合。

【修正说明】
    上一版对照实现从 date(ly, 1, 1) 起线性扫描，但没校验
    lunar.lunarYear == ly，结果会命中"上一农历年"的腊月/正月尾
    （例如查 2024 农历年冬月廿九会命中 2024-01-10），
    造成与新版索引实现大面积 mismatch。
    新版索引内部有 lunarYear 过滤，才是正确语义；
    这里给对照基线补上同样的过滤，两者才具备可比性。
"""
import calendar
from datetime import date, timedelta

from lunar import _get_lunar_cached, lunar_to_gregorian


_TEST_YEARS = (2024, 2025, 2026)
_TEST_MONTHS = tuple(range(1, 13))
_TEST_DAYS = (1, 15, 29, 30)
_TEST_LEAPS = (False, True)


def _old_lunar_to_gregorian(ly, lm, ld, is_leap=False):
    """
    旧版线性实现的副本，作为对照基线。

    与新版索引实现保持同一语义：只接受"农历年 == ly"的日期。
    """
    start = date(ly, 1, 1)
    end = date(ly + 1, 2, calendar.monthrange(ly + 1, 2)[1])
    cur = start
    while cur <= end:
        lunar = _get_lunar_cached(cur.year, cur.month, cur.day)
        if (lunar is not None
                and getattr(lunar, "lunarYear", None) == ly      # ← 关键
                and lunar.lunarMonth == lm
                and lunar.lunarDay == ld
                and lunar.isLunarLeapMonth == is_leap):
            return cur
        cur += timedelta(days=1)
    return None


def test_lunar_index_matches_legacy():
    """新版索引化结果必须与旧版线性实现完全一致。"""
    mismatches = []
    checked = 0
    for y in _TEST_YEARS:
        for m in _TEST_MONTHS:
            for d in _TEST_DAYS:
                for leap in _TEST_LEAPS:
                    old = _old_lunar_to_gregorian(y, m, d, leap)
                    new = lunar_to_gregorian(y, m, d, leap)
                    checked += 1
                    if old != new:
                        mismatches.append((y, m, d, leap, old, new))

    assert not mismatches, (
        f"checked={checked}, mismatch={len(mismatches)}: "
        + "; ".join(
            f"y={y} m={m} d={d} leap={l}: old={o} new={n}"
            for y, m, d, l, o, n in mismatches[:10]
        )
    )


if __name__ == "__main__":
    test_lunar_index_matches_legacy()
    total = (len(_TEST_YEARS) * len(_TEST_MONTHS)
             * len(_TEST_DAYS) * len(_TEST_LEAPS))
    print(f"✅ 全部 {total} 组样本通过：索引化实现与旧版线性实现一致")