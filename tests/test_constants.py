# coding: utf-8
import calendar
import json

from constants import (
    DEFAULT_THEME,
    REFERENCE_LEAP_YEAR,
    load_theme,
)


def test_reference_leap_year_is_leap():
    assert calendar.isleap(REFERENCE_LEAP_YEAR)


def test_load_theme_missing_file_returns_default(tmp_path):
    theme = load_theme(str(tmp_path / "not_exists.json"))
    assert theme["bg_main"] == DEFAULT_THEME["bg_main"]


def test_load_theme_merges_and_ignores_unknown(tmp_path):
    p = tmp_path / "theme.json"
    p.write_text(
        json.dumps(
            {
                "bg_main": "#123456",
                "unknown_key": 1,
                "font_size": None,
            }
        ),
        encoding="utf-8",
    )

    theme = load_theme(str(p))

    assert theme["bg_main"] == "#123456"
    assert "unknown_key" not in theme
    assert theme["font_size"] == DEFAULT_THEME["font_size"]