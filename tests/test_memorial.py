# tests/test_memorial.py
# coding: utf-8
"""
memorial.py 的单元测试。

覆盖：
  * normalize_memorial —— 非法值回落、clamp 边界
  * match_memorial_date —— 公历/农历 × 年/月/周，datetime.date 兼容（Bug 1 回归）
  * get_next_memorial_date —— 跨年、月末回落、2/29 处理、农历窗口、闰月

农历相关测试通过 monkeypatch 用假农历表驱动，不依赖 cnlunar；
另有一组真实 cnlunar 集成测试，cnlunar 未安装时自动 skip。

运行：
    pytest tests/ -v

共享 fixture（fake_lunar_env）由 tests/conftest.py 提供，
测试辅助类（FakeLunar / FakeLunarEnv）来自 tests/_helpers.py。
"""
import sys
import os
from datetime import date, datetime

import pytest

# 让 tests/ 能 import 到项目根目录下的模块
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ===================== config 兜底 =====================
# config 模块可能依赖资源路径探测，测试环境里如果 import 失败，
# 就注入一个最小 stub，保证 memorial / lunar 能被导入。
try:
    import config  # noqa: F401
except Exception:
    import logging
    import types

    _stub = types.ModuleType("config")
    _stub.logger = logging.getLogger("test.config")
    _stub.log_exception = lambda msg: _stub.logger.exception(msg)
    _stub.get_resource_path = lambda name: name
    sys.modules["config"] = _stub


from _helpers import FakeLunar  # noqa: E402

import memorial  # noqa: E402
from memorial import (  # noqa: E402
    REPEAT_YEAR, REPEAT_MONTH, REPEAT_WEEK,
    normalize_memorial, match_memorial_date, get_next_memorial_date,
)


# ===================== normalize_memorial =====================
class TestNormalizeMemorial:

    def test_empty_dict_gets_defaults(self):
        mem = normalize_memorial({})
        assert mem["type"] == "solar"
        assert mem["repeat_type"] == REPEAT_YEAR
        assert mem["month"] == 1
        assert mem["day"] == 1
        assert mem["enabled"] is True
        assert mem["isleap"] is False
        assert mem["advance_days"] == 0
        assert mem["name"] == "未命名纪念日"

    def test_invalid_repeat_type_falls_back_to_year(self):
        mem = normalize_memorial({"repeat_type": "fortnight"})
        assert mem["repeat_type"] == REPEAT_YEAR

    def test_invalid_type_falls_back_to_solar(self):
        mem = normalize_memorial({"type": "mayan"})
        assert mem["type"] == "solar"

    def test_solar_yearly_day_clamped_to_month_length(self):
        # 2 月给 31 日 → 按 2024 闰年基准收敛到 29
        mem = normalize_memorial({
            "type": "solar", "repeat_type": REPEAT_YEAR,
            "month": 2, "day": 31,
        })
        assert mem["day"] == 29

    def test_solar_monthly_day_kept_to_31(self):
        # 公历每月：不按月份收敛，由计算阶段回落
        mem = normalize_memorial({
            "type": "solar", "repeat_type": REPEAT_MONTH, "day": 31,
        })
        assert mem["day"] == 31

    def test_lunar_day_clamped_to_30(self):
        mem = normalize_memorial({"type": "lunar", "month": 6, "day": 31})
        assert mem["day"] == 30

    def test_week_day_clamped_to_1_7(self):
        assert normalize_memorial(
            {"repeat_type": REPEAT_WEEK, "day": 99})["day"] == 7
        assert normalize_memorial(
            {"repeat_type": REPEAT_WEEK, "day": -5})["day"] == 1

    def test_month_clamped(self):
        assert normalize_memorial({"month": -3})["month"] == 1
        assert normalize_memorial({"month": 99})["month"] == 12

    def test_non_int_input_falls_back(self):
        mem = normalize_memorial({"month": "abc", "day": "xyz"})
        assert mem["month"] == 1
        assert mem["day"] == 1

    def test_advance_days_negative_clamped(self):
        assert normalize_memorial({"advance_days": -5})["advance_days"] == 0
        assert normalize_memorial({"advance_days": "oops"})["advance_days"] == 0


# ===================== match_memorial_date =====================
class TestMatchMemorialDate:

    def test_solar_yearly_hit(self):
        mem = {"type": "solar", "repeat_type": REPEAT_YEAR,
               "month": 3, "day": 15}
        assert match_memorial_date(mem, date(2025, 3, 15))
        assert match_memorial_date(mem, date(2024, 3, 15))
        assert not match_memorial_date(mem, date(2025, 3, 14))
        assert not match_memorial_date(mem, date(2025, 4, 15))

    def test_solar_monthly_hit(self):
        mem = {"type": "solar", "repeat_type": REPEAT_MONTH, "day": 15}
        for m in range(1, 13):
            assert match_memorial_date(mem, date(2025, m, 15))
        assert not match_memorial_date(mem, date(2025, 1, 16))

    def test_week_monday_hit(self):
        # 2025-09-29 是周一
        mem = {"repeat_type": REPEAT_WEEK, "day": 1}
        assert match_memorial_date(mem, date(2025, 9, 29))
        assert not match_memorial_date(mem, date(2025, 9, 30))

    def test_week_sunday_hit(self):
        # 2025-09-28 是周日
        mem = {"repeat_type": REPEAT_WEEK, "day": 7}
        assert match_memorial_date(mem, date(2025, 9, 28))
        assert not match_memorial_date(mem, date(2025, 9, 27))

    def test_accepts_datetime_datetime(self):
        """
        Bug 1 回归：datetime.datetime 也必须可用，
        原实现在 REPEAT_YEAR + solar 分支会调 qdate.month() 触发 TypeError。
        """
        mem = {"type": "solar", "repeat_type": REPEAT_YEAR,
               "month": 3, "day": 15}
        assert match_memorial_date(mem, datetime(2025, 3, 15, 10, 30))
        assert not match_memorial_date(mem, datetime(2025, 3, 14, 23, 59))

    def test_accepts_qdate_like_duck(self):
        """
        模拟 PyQt6 QDate 的鸭子类型：
        toPyDate() 可用，year/month/day 为方法。
        """
        class FakeQDate:
            def __init__(self, y, m, d):
                self._y, self._m, self._d = y, m, d

            def year(self): return self._y
            def month(self): return self._m
            def day(self): return self._d
            def toPyDate(self): return date(self._y, self._m, self._d)

        mem = {"type": "solar", "repeat_type": REPEAT_YEAR,
               "month": 3, "day": 15}
        assert match_memorial_date(mem, FakeQDate(2025, 3, 15))

    # -------- 农历（假表） --------

    def test_lunar_yearly_hit(self, fake_lunar_env):
        fake_lunar_env.add(date(2024, 2, 10), FakeLunar(2024, 1, 1))
        fake_lunar_env.add(date(2025, 1, 29), FakeLunar(2025, 1, 1))
        mem = {"type": "lunar", "repeat_type": REPEAT_YEAR,
               "month": 1, "day": 1}
        assert match_memorial_date(mem, date(2025, 1, 29))
        assert not match_memorial_date(mem, date(2025, 1, 28))

    def test_lunar_monthly_hit_ignores_month(self, fake_lunar_env):
        # 农历每月十五：不同农历月份只要日相同就命中
        fake_lunar_env.add(date(2025, 1, 14), FakeLunar(2024, 12, 15))
        fake_lunar_env.add(date(2025, 2, 12), FakeLunar(2025, 1, 15))
        mem = {"type": "lunar", "repeat_type": REPEAT_MONTH, "day": 15}
        assert match_memorial_date(mem, date(2025, 1, 14))
        assert match_memorial_date(mem, date(2025, 2, 12))
        assert not match_memorial_date(mem, date(2025, 1, 13))

    def test_lunar_leap_month_requires_matching_flag(self, strict_lunar_env):
        # 闰六月十五 vs 六月十五：isleap 不一致不应互中
        # 两个日期都已注册 → 用严格模式，防止以后漏配
        strict_lunar_env.add(date(2025, 6, 25), FakeLunar(2025, 6, 15, False))
        strict_lunar_env.add(date(2025, 7, 25), FakeLunar(2025, 6, 15, True))
        leap_mem = {"type": "lunar", "repeat_type": REPEAT_YEAR,
                    "month": 6, "day": 15, "isleap": True}
        plain_mem = {"type": "lunar", "repeat_type": REPEAT_YEAR,
                     "month": 6, "day": 15, "isleap": False}
        assert match_memorial_date(leap_mem, date(2025, 7, 25))
        assert not match_memorial_date(leap_mem, date(2025, 6, 25))
        assert match_memorial_date(plain_mem, date(2025, 6, 25))
        assert not match_memorial_date(plain_mem, date(2025, 7, 25))

    def test_lunar_missing_returns_false(self, fake_lunar_env):
        # 表里没有对应日期时返回 False，不抛异常
        mem = {"type": "lunar", "repeat_type": REPEAT_YEAR,
               "month": 1, "day": 1}
        assert match_memorial_date(mem, date(2030, 1, 1)) is False


# ===================== get_next_memorial_date — 公历 =====================
class TestGetNextMemorialDateSolar:

    def test_same_day_returns_self(self):
        mem = {"type": "solar", "repeat_type": REPEAT_YEAR,
               "month": 3, "day": 15}
        assert get_next_memorial_date(mem, date(2025, 3, 15)) == date(2025, 3, 15)

    def test_solar_yearly_after_date(self):
        mem = {"type": "solar", "repeat_type": REPEAT_YEAR,
               "month": 3, "day": 15}
        assert get_next_memorial_date(mem, date(2025, 3, 16)) == date(2026, 3, 15)

    def test_solar_yearly_cross_year(self):
        mem = {"type": "solar", "repeat_type": REPEAT_YEAR,
               "month": 3, "day": 15}
        assert get_next_memorial_date(mem, date(2025, 12, 1)) == date(2026, 3, 15)

    def test_new_year_boundary(self):
        mem = {"type": "solar", "repeat_type": REPEAT_YEAR,
               "month": 1, "day": 1}
        assert get_next_memorial_date(mem, date(2025, 12, 31)) == date(2026, 1, 1)

    def test_feb29_non_leap_falls_back_to_28(self):
        mem = {"type": "solar", "repeat_type": REPEAT_YEAR,
               "month": 2, "day": 29}
        # 2025 不是闰年 → 2-28
        assert get_next_memorial_date(mem, date(2025, 1, 1)) == date(2025, 2, 28)
        # 2028 是闰年 → 2-29
        assert get_next_memorial_date(mem, date(2028, 1, 1)) == date(2028, 2, 29)

    def test_monthly_day_31_february_clamps(self):
        mem = {"type": "solar", "repeat_type": REPEAT_MONTH, "day": 31}
        assert get_next_memorial_date(mem, date(2025, 2, 1)) == date(2025, 2, 28)
        # 闰年 2 月 → 29
        assert get_next_memorial_date(mem, date(2024, 2, 1)) == date(2024, 2, 29)

    def test_monthly_day_31_in_30day_month(self):
        mem = {"type": "solar", "repeat_type": REPEAT_MONTH, "day": 31}
        assert get_next_memorial_date(mem, date(2025, 4, 1)) == date(2025, 4, 30)
        assert get_next_memorial_date(mem, date(2025, 6, 1)) == date(2025, 6, 30)
        assert get_next_memorial_date(mem, date(2025, 9, 1)) == date(2025, 9, 30)

    def test_monthly_same_day_returns_self(self):
        mem = {"type": "solar", "repeat_type": REPEAT_MONTH, "day": 15}
        assert get_next_memorial_date(mem, date(2025, 1, 15)) == date(2025, 1, 15)

    def test_monthly_rolls_to_next_month(self):
        mem = {"type": "solar", "repeat_type": REPEAT_MONTH, "day": 15}
        assert get_next_memorial_date(mem, date(2025, 1, 20)) == date(2025, 2, 15)

    def test_monthly_december_rolls_to_january(self):
        mem = {"type": "solar", "repeat_type": REPEAT_MONTH, "day": 15}
        assert get_next_memorial_date(mem, date(2025, 12, 20)) == date(2026, 1, 15)

    def test_accepts_datetime_input(self):
        mem = {"type": "solar", "repeat_type": REPEAT_YEAR,
               "month": 3, "day": 15}
        assert get_next_memorial_date(
            mem, datetime(2025, 3, 16, 10, 0)) == date(2026, 3, 15)

    def test_none_base_returns_none(self):
        mem = {"type": "solar", "repeat_type": REPEAT_YEAR,
               "month": 3, "day": 15}
        assert get_next_memorial_date(mem, None) is None


# ===================== get_next_memorial_date — 每周 =====================
class TestGetNextMemorialDateWeekly:
    # 参考：2025-09-29 周一，10-01 周三，10-03 周五，10-08 周三，09-28 周日

    def test_same_weekday_returns_self(self):
        mem = {"repeat_type": REPEAT_WEEK, "day": 1}  # 周一
        assert get_next_memorial_date(mem, date(2025, 9, 29)) == date(2025, 9, 29)

    def test_later_in_same_week(self):
        mem = {"repeat_type": REPEAT_WEEK, "day": 3}  # 周三
        assert get_next_memorial_date(mem, date(2025, 9, 29)) == date(2025, 10, 1)

    def test_wraps_to_next_week(self):
        mem = {"repeat_type": REPEAT_WEEK, "day": 3}  # 周三
        # base 周五 → +5 天到下周周三
        assert get_next_memorial_date(mem, date(2025, 10, 3)) == date(2025, 10, 8)

    def test_sunday_to_monday(self):
        mem = {"repeat_type": REPEAT_WEEK, "day": 1}  # 周一
        # base 周日 → +1 天
        assert get_next_memorial_date(mem, date(2025, 9, 28)) == date(2025, 9, 29)


# ===================== get_next_memorial_date — 农历（假表） =====================
class TestGetNextMemorialDateLunar:

    def test_yearly_next_spring_festival(self, fake_lunar_env):
        # 春节每年正月初一
        fake_lunar_env.add(date(2024, 2, 10), FakeLunar(2024, 1, 1))
        fake_lunar_env.add(date(2025, 1, 29), FakeLunar(2025, 1, 1))
        fake_lunar_env.add(date(2026, 2, 17), FakeLunar(2026, 1, 1))
        mem = {"type": "lunar", "repeat_type": REPEAT_YEAR,
               "month": 1, "day": 1}
        # base 早于 2025 春节 → 取 2025 春节
        assert get_next_memorial_date(mem, date(2025, 1, 1)) == date(2025, 1, 29)
        # base 晚于 2025 春节 → 取 2026 春节
        assert get_next_memorial_date(mem, date(2025, 2, 1)) == date(2026, 2, 17)

    def test_yearly_same_day_returns_self(self, fake_lunar_env):
        fake_lunar_env.add(date(2025, 1, 29), FakeLunar(2025, 1, 1))
        fake_lunar_env.add(date(2026, 2, 17), FakeLunar(2026, 1, 1))
        mem = {"type": "lunar", "repeat_type": REPEAT_YEAR,
               "month": 1, "day": 1}
        assert get_next_memorial_date(mem, date(2025, 1, 29)) == date(2025, 1, 29)

    def test_yearly_leap_month_only(self, fake_lunar_env):
        # 闰六月十五只匹配闰月
        fake_lunar_env.add(date(2025, 8, 8), FakeLunar(2025, 6, 15, True))
        fake_lunar_env.add(date(2026, 7, 28), FakeLunar(2026, 6, 15, False))
        mem = {"type": "lunar", "repeat_type": REPEAT_YEAR,
               "month": 6, "day": 15, "isleap": True}
        assert get_next_memorial_date(mem, date(2025, 1, 1)) == date(2025, 8, 8)
        # base 在 2025 闰六月之后 → 表里没有下一个闰六月 → None
        assert get_next_memorial_date(mem, date(2025, 9, 1)) is None

    def test_yearly_leap_not_matched_by_plain(self, fake_lunar_env):
        # 表里只有普通六月，没有闰月；闰月纪念日应找不到
        fake_lunar_env.add(date(2025, 6, 25), FakeLunar(2025, 6, 15, False))
        mem = {"type": "lunar", "repeat_type": REPEAT_YEAR,
               "month": 6, "day": 15, "isleap": True}
        assert get_next_memorial_date(mem, date(2025, 1, 1)) is None

    def test_monthly_within_year(self, strict_lunar_env):
        # 农历每月十五：base 之后的下一个十五
        # 所有作为 base_date 传入的日期都必须注册 → 用严格模式
        strict_lunar_env.add(date(2025, 1, 14), FakeLunar(2024, 12, 15))
        strict_lunar_env.add(date(2025, 1, 15), FakeLunar(2024, 12, 16))
        strict_lunar_env.add(date(2025, 2, 12), FakeLunar(2025, 1, 15))
        strict_lunar_env.add(date(2025, 2, 13), FakeLunar(2025, 1, 16))
        strict_lunar_env.add(date(2025, 3, 14), FakeLunar(2025, 2, 15))
        mem = {"type": "lunar", "repeat_type": REPEAT_MONTH, "day": 15}
        assert get_next_memorial_date(mem, date(2025, 1, 14)) == date(2025, 1, 14)
        assert get_next_memorial_date(mem, date(2025, 1, 15)) == date(2025, 2, 12)
        assert get_next_memorial_date(mem, date(2025, 2, 13)) == date(2025, 3, 14)

    def test_monthly_across_lunar_new_year(self, strict_lunar_env):
        # 农历每月初一：base 在腊月 → 下次是正月
        # base_date=2025-01-25 必须注册 → 严格模式
        strict_lunar_env.add(date(2025, 1, 25), FakeLunar(2024, 12, 26))
        strict_lunar_env.add(date(2024, 12, 31), FakeLunar(2024, 12, 1))
        strict_lunar_env.add(date(2025, 1, 29), FakeLunar(2025, 1, 1))
        mem = {"type": "lunar", "repeat_type": REPEAT_MONTH, "day": 1}
        assert get_next_memorial_date(mem, date(2025, 1, 25)) == date(2025, 1, 29)

    def test_monthly_skips_missing_days_in_small_months(self, fake_lunar_env):
        """
        农历每月三十：连续 5 个农历小月（29 天）没有「三十」，
        验证 6 个月窗口足以跨过，在第 5 次迭代命中。
        """
        fake_lunar_env.add(date(2025, 1, 1), FakeLunar(2024, 12, 1))
        # 2025 农历 5 月 30 日 → 2025-06-25
        fake_lunar_env.add(date(2025, 6, 25), FakeLunar(2025, 5, 30))
        mem = {"type": "lunar", "repeat_type": REPEAT_MONTH, "day": 30}
        assert get_next_memorial_date(mem, date(2025, 1, 1)) == date(2025, 6, 25)

    def test_lunar_unavailable_returns_none(self, monkeypatch):
        """没有农历库（或底层返回 None）时应安全返回 None。"""
        monkeypatch.setattr(memorial, "get_lunar_by_datetime", lambda dt: None)
        monkeypatch.setattr(memorial, "lunar_to_gregorian", lambda *a, **k: None)
        monkeypatch.setattr(memorial, "HAS_CHNCAL", False)
        mem = {"type": "lunar", "repeat_type": REPEAT_YEAR,
               "month": 1, "day": 1}
        assert get_next_memorial_date(mem, date(2025, 1, 1)) is None
        # match 也不应崩
        assert match_memorial_date(mem, date(2025, 1, 1)) is False

    def test_base_lunar_lookup_returns_none(self, fake_lunar_env):
        # base 日期在假表里查不到 → 农历每月分支直接返回 None
        mem = {"type": "lunar", "repeat_type": REPEAT_MONTH, "day": 15}
        assert get_next_memorial_date(mem, date(2025, 5, 5)) is None


# ===================== 真实 cnlunar 集成测试（可选） =====================
try:
    import cnlunar  # noqa: F401
    _HAS_CNLUNAR = True
except ImportError:
    _HAS_CNLUNAR = False


@pytest.mark.skipif(not _HAS_CNLUNAR, reason="cnlunar 未安装")
class TestWithRealCnlunar:
    """
    不 mock 农历库，验证真实集成。
    使用公开可查的农历春节日期作为参照。
    """

    def test_spring_festival_2025(self):
        from lunar import get_lunar_by_datetime
        lunar = get_lunar_by_datetime(date(2025, 1, 29))
        assert lunar is not None
        assert lunar.lunarMonth == 1
        assert lunar.lunarDay == 1
        assert lunar.isLunarLeapMonth is False

    def test_next_spring_festival_after_2025(self):
        mem = {"type": "lunar", "repeat_type": REPEAT_YEAR,
               "month": 1, "day": 1, "isleap": False}
        # 2025 春节（1-29）之后的下一个春节是 2026-02-17
        assert get_next_memorial_date(mem, date(2025, 2, 1)) == date(2026, 2, 17)

    def test_match_spring_festival_2025(self):
        mem = {"type": "lunar", "repeat_type": REPEAT_YEAR,
               "month": 1, "day": 1, "isleap": False}
        assert match_memorial_date(mem, date(2025, 1, 29))
        assert not match_memorial_date(mem, date(2025, 1, 28))