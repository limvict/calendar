# coding: utf-8
from datetime import datetime

from PyQt6.QtCore import QDate

from reminder_manager import ReminderManager


class FakeCfg:
    def __init__(self, data):
        self.data = data

    def get(self, key, default=None):
        return self.data.get(key, default)

    def get_nested(self, *keys, default=None):
        cur = self.data
        for k in keys:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(k)
            if cur is None:
                return default
        return cur


def test_get_int_cfg_clamps():
    cfg = FakeCfg({"memorial_cfg": {"remind_start_hour": 25}})
    assert (
        ReminderManager._get_int_cfg(
            cfg,
            "memorial_cfg",
            "remind_start_hour",
            default=8,
            lo=0,
            hi=23,
        )
        == 23
    )

    cfg = FakeCfg({"memorial_cfg": {"remind_start_hour": "bad"}})
    assert (
        ReminderManager._get_int_cfg(
            cfg,
            "memorial_cfg",
            "remind_start_hour",
            default=8,
            lo=0,
            hi=23,
        )
        == 8
    )


def test_get_bool_cfg_variants():
    cfg = FakeCfg({"memorial_cfg": {"enable_remind": "false"}})
    assert (
        ReminderManager._get_bool_cfg(
            cfg, "memorial_cfg", "enable_remind", default=True
        )
        is False
    )

    cfg = FakeCfg({"memorial_cfg": {"enable_remind": 0.0}})
    assert (
        ReminderManager._get_bool_cfg(
            cfg, "memorial_cfg", "enable_remind", default=True
        )
        is False
    )


def test_first_future_remind_ts(qapp):
    now_ms = int(datetime.now().timestamp() * 1000)
    today = QDate.currentDate()
    tomorrow = today.addDays(1)

    ts = ReminderManager._first_future_remind_ts(
        today,
        tomorrow,
        remind_h=23,
        now_ms=now_ms,
    )

    assert ts is not None
    assert ts > now_ms