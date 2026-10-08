# coding: utf-8
from datetime import date

from PyQt6.QtCore import QDate

import lunar as lunar_mod
import memorial as mem_mod


def test_qdate_to_pydate():
    from lunar import qdate_to_pydate

    assert qdate_to_pydate(QDate(2024, 2, 29)) == date(2024, 2, 29)


def test_normalize_invalid_repeat_and_week():
    m = mem_mod.normalize_memorial(
        {
            "name": "x",
            "repeat_type": "bad",
            "type": "lunar",
            "day": 99,
        }
    )
    assert m["repeat_type"] == mem_mod.REPEAT_YEAR

    m = mem_mod.normalize_memorial(
        {
            "name": "w",
            "repeat_type": mem_mod.REPEAT_WEEK,
            "type": "lunar",
            "day": 99,
        }
    )
    assert m["type"] == "solar"
    assert m["day"] == 7
    assert m["isleap"] is False


def test_normalize_advance_clamp():
    assert mem_mod.normalize_memorial({"advance_days": 999})["advance_days"] == 365
    assert mem_mod.normalize_memorial({"advance_days": -1})["advance_days"] == 0


def test_match_solar():
    m = mem_mod.normalize_memorial(
        {
            "name": "元旦",
            "type": "solar",
            "repeat_type": "year",
            "month": 1,
            "day": 1,
        }
    )
    assert mem_mod.match_memorial_date(m, date(2025, 1, 1), normalized=True)
    assert not mem_mod.match_memorial_date(m, date(2025, 1, 2), normalized=True)

    w = mem_mod.normalize_memorial(
        {
            "name": "周一",
            "type": "solar",
            "repeat_type": "week",
            "day": 1,
        }
    )
    assert mem_mod.match_memorial_date(w, date(2025, 1, 6), normalized=True)
    assert not mem_mod.match_memorial_date(w, date(2025, 1, 7), normalized=True)


def test_next_solar_yearly_include_base():
    m = mem_mod.normalize_memorial(
        {
            "name": "元旦",
            "type": "solar",
            "repeat_type": "year",
            "month": 1,
            "day": 1,
        }
    )

    assert (
        mem_mod.get_next_memorial_date(
            m, date(2025, 1, 1), include_base=True, normalized=True
        )
        == date(2025, 1, 1)
    )
    assert (
        mem_mod.get_next_memorial_date(
            m, date(2025, 1, 1), include_base=False, normalized=True
        )
        == date(2026, 1, 1)
    )


def test_next_week_strictly_future():
    m = mem_mod.normalize_memorial(
        {
            "name": "周一",
            "type": "solar",
            "repeat_type": "week",
            "day": 1,
        }
    )

    assert (
        mem_mod.get_next_memorial_date(
            m, date(2025, 1, 6), include_base=False, normalized=True
        )
        == date(2025, 1, 13)
    )


def test_lunar_dependency_absent(monkeypatch):
    monkeypatch.setattr(mem_mod, "HAS_CHNCAL", False)

    m = mem_mod.normalize_memorial(
        {
            "name": "农历",
            "type": "lunar",
            "repeat_type": "year",
            "month": 1,
            "day": 1,
        }
    )

    assert (
        mem_mod.get_next_memorial_date(m, date(2025, 1, 1), normalized=True)
        is None
    )