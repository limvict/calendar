# tests/test_memorial_next_date.py
from datetime import date
from memorial import (
    REPEAT_WEEK, REPEAT_MONTH, REPEAT_YEAR,
    get_next_memorial_date, normalize_memorial,
)


def test_weekly_strictly_after_base():
    """每周重复：base_date 命中当天时，返回下一个 7 天后，而非当天。"""
    mem = {"name": "x", "type": "solar", "repeat_type": REPEAT_WEEK,
           "day": 1, "month": 1}  # 周一
    base = date(2024, 1, 1)  # 2024-01-01 是周一
    nxt = get_next_memorial_date(mem, base)
    assert nxt == date(2024, 1, 8), f"expected 01-08, got {nxt}"


def test_weekly_include_base():
    mem = {"name": "x", "type": "solar", "repeat_type": REPEAT_WEEK,
           "day": 1, "month": 1}
    base = date(2024, 1, 1)
    nxt = get_next_memorial_date(mem, base, include_base=True)
    assert nxt == base


def test_weekly_forces_solar():
    mem = {"name": "x", "type": "lunar", "repeat_type": REPEAT_WEEK,
           "day": 3, "month": 5, "isleap": True}
    n = normalize_memorial(mem)
    assert n["type"] == "solar"
    assert n["isleap"] is False


def test_yearly_strictly_after_base():
    mem = {"name": "x", "type": "solar", "repeat_type": REPEAT_YEAR,
           "month": 1, "day": 1}
    base = date(2024, 1, 1)
    nxt = get_next_memorial_date(mem, base)
    assert nxt == date(2025, 1, 1)