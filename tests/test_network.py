# coding: utf-8
import pytest

from network import HolidayNetWorker


def test_parse_holiday_json_holiday_cn():
    raw = """
    {
      "days": [
        {"date": "2024-01-01", "isOffDay": true},
        {"date": "2024-02-10", "isOffDay": false}
      ]
    }
    """
    result = HolidayNetWorker._parse_holiday_json(raw, 2024)
    assert result == {
        "2024-01-01": True,
        "2024-02-10": False,
    }


def test_parse_holiday_json_chinese_days():
    raw = '{"2024-01-01": true, "2024-02-10": false}'
    result = HolidayNetWorker._parse_holiday_json(raw, 2024)
    assert result == {
        "2024-01-01": True,
        "2024-02-10": False,
    }


def test_parse_holiday_json_list():
    raw = '[{"date": "2024-01-01", "isOffDay": true}]'
    result = HolidayNetWorker._parse_holiday_json(raw, 2024)
    assert result == {"2024-01-01": True}


def test_parse_holiday_json_invalid():
    with pytest.raises(ValueError):
        HolidayNetWorker._parse_holiday_json('{"foo": "bar"}', 2024)