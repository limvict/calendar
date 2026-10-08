# coding: utf-8
from datetime import datetime

import holiday_manager as hm_mod


def test_apply_cached_removes_expired(monkeypatch):
    class HM(hm_mod.HolidayManager):
        def __init__(self):
            pass

    obj = HM()
    now_ts = datetime.now().timestamp()

    obj.holiday_cache = {
        "2024": {
            "ts": now_ts,
            "days": {"2024-01-01": True},
        },
        "2020": {
            "ts": 0,
            "days": {"2020-01-01": True},
        },
        "bad": "not-a-dict",
    }

    monkeypatch.setattr(hm_mod, "save_holiday_cache", lambda data: None)

    result = obj.apply_cached()

    assert result == {"2024-01-01": True}
    assert "2024" in obj.holiday_cache
    assert "2020" not in obj.holiday_cache
    assert "bad" not in obj.holiday_cache