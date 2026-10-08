# coding: utf-8
from PyQt6.QtCore import QDate

import calendar_widget as cw
from constants import DEFAULT_THEME


def _make_widget(memorials=None):
    return cw.LunarCalendarWidget(None, DEFAULT_THEME, memorials or [])


def test_build_memorial_index(qapp):
    w = _make_widget(
        [
            {
                "name": "元旦",
                "type": "solar",
                "repeat_type": "year",
                "month": 1,
                "day": 1,
                "enabled": True,
            },
            {
                "name": "周一",
                "type": "solar",
                "repeat_type": "week",
                "day": 1,
                "enabled": True,
            },
            {
                "name": "农历",
                "type": "lunar",
                "repeat_type": "year",
                "month": 1,
                "day": 1,
                "enabled": True,
            },
            {
                "name": "禁用",
                "enabled": False,
            },
        ]
    )

    assert w._memorial_index["solar_year"][(1, 1)][0]["name"] == "元旦"
    assert w._memorial_index["solar_week"][1][0]["name"] == "周一"
    assert w._memorial_index["lunar_year"][(1, 1, False)][0]["name"] == "农历"


def test_get_lunar_cell_text_solar_memorial(qapp):
    w = _make_widget(
        [
            {
                "name": "元旦",
                "type": "solar",
                "repeat_type": "year",
                "month": 1,
                "day": 1,
                "enabled": True,
            }
        ]
    )

    text, kind = w.get_lunar_cell_text(QDate(2025, 1, 1))

    assert text == "元旦"
    assert kind == cw._CELL_MEMORIAL


class _FakeLunar:
    lunarMonth = 1
    lunarDay = 1
    isLunarLeapMonth = False
    todaySolarTerms = "无"

    def get_legalHolidays(self):
        return ["元旦节"]


def test_legal_holiday_name_map_red(qapp, monkeypatch):
    monkeypatch.setattr(cw.lunar_mod, "HAS_CHNCAL", True)

    w = _make_widget([])
    text, kind = w.get_lunar_cell_text(
        QDate(2025, 1, 1),
        lunar=_FakeLunar(),
        legal_raw="元旦节",
    )

    assert text == "元旦"
    assert kind == cw._CELL_RED


def test_lunar_festival_red(qapp, monkeypatch):
    monkeypatch.setattr(cw.lunar_mod, "HAS_CHNCAL", True)

    class L:
        lunarMonth = 1
        lunarDay = 1
        isLunarLeapMonth = False
        todaySolarTerms = "无"

        def get_legalHolidays(self):
            return []

    w = _make_widget([])
    text, kind = w.get_lunar_cell_text(
        QDate(2025, 1, 29),
        lunar=L(),
        legal_raw=None,
    )

    assert text == "春节"
    assert kind == cw._CELL_RED


def test_chuxi_red(qapp, monkeypatch):
    monkeypatch.setattr(cw.lunar_mod, "HAS_CHNCAL", True)

    class L12:
        lunarMonth = 12
        lunarDay = 29
        isLunarLeapMonth = False
        todaySolarTerms = "无"

        def get_legalHolidays(self):
            return []

    class L1:
        lunarMonth = 1
        lunarDay = 1
        isLunarLeapMonth = False

    w = _make_widget([])
    monkeypatch.setattr(w, "get_day_lunar_obj", lambda qd: L1())

    text, kind = w.get_lunar_cell_text(
        QDate(2025, 1, 28),
        lunar=L12(),
        legal_raw=None,
    )

    assert text == "除夕"
    assert kind == cw._CELL_RED