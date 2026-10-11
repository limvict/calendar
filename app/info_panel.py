# coding: utf-8
"""
日历选中日的详情组装。

把 main.py 里原本混在 on_calendar_select_changed 中的
"取农历 / 拼 HTML / 决定占位文案"三段拆成纯函数，方便单测。

设计要点：
- build_info_parts 只做数据提取，不接触 Qt 控件；
- render_html 只做 HTML 拼接，输入 InfoParts 输出 str | None；
- placeholder_key 只决定占位 i18n key，不直接 setText；
- lunar 对象与 HAS_CHNCAL 由调用方传入，本模块不 import
  lunar_mod，方便测试时绕过全局状态。
"""
import html
from dataclasses import dataclass
from typing import List, Optional

from i18n import tr


@dataclass(frozen=True)
class InfoParts:
    """选中日详情的数据快照。"""
    lunar_str: Optional[str] = None
    term_text: Optional[str] = None
    holiday_names: tuple = ()
    memorial_names: tuple = ()
    has_lunar_data: bool = False
    lunar_lib_available: bool = True


def _as_list(v) -> List[str]:
    """把 cnlunar 的"无 / 单值 / list"归一化为 list[str]。"""
    if v is None or v == "无":
        return []
    if isinstance(v, (list, tuple)):
        return [x for x in v if x and x != "无"]
    return [v] if v != "无" else []


def _extract_lunar_str(lunar) -> Optional[str]:
    """农历串：依赖 lunarYearCn / chineseYearZodiac /
    lunarMonthCn / lunarDayCn 四个属性，cnlunar 版本差异时可能缺
    某个。失败返回 None，只丢本段。"""
    if lunar is None:
        return None
    try:
        month_cn = (lunar.lunarMonthCn
                    .replace("大", "").replace("小", ""))
        return (f"{lunar.lunarYearCn}【{lunar.chineseYearZodiac}】 "
                f"{month_cn}{lunar.lunarDayCn}")
    except Exception:
        return None


def _extract_term_text(lunar) -> Optional[str]:
    """节气：getattr 兜底属性缺失；值为 list 时取首项。"""
    if lunar is None:
        return None
    solar_term = getattr(lunar, "todaySolarTerms", "")
    if isinstance(solar_term, list) and solar_term:
        solar_term = solar_term[0]
    if solar_term and solar_term != "无":
        return solar_term
    return None


def _extract_holidays(lunar) -> tuple:
    """节日列表：依赖 get_legalHolidays / get_otherHolidays 两个方法。
    失败只丢本段。去重且保序。"""
    if lunar is None:
        return ()
    try:
        holiday_list = [
            x for x in (_as_list(lunar.get_legalHolidays())
                        + _as_list(lunar.get_otherHolidays()))
            if x and x != "无"]
        return tuple(dict.fromkeys(holiday_list))
    except Exception:
        return ()


def build_info_parts(
    sel_date,
    memorial_names,
    lunar_obj,
    has_cnlunar: bool,
) -> InfoParts:
    """
    :param sel_date: QDate，仅用于语义占位（本函数不读取它）
    :param memorial_names: list[str]，由 calendar widget 提供
    :param lunar_obj: get_lunar_by_datetime 的返回值（None 表示无农历信息）
    :param has_cnlunar: lunar_mod.HAS_CHNCAL
    """
    return InfoParts(
        lunar_str=_extract_lunar_str(lunar_obj),
        term_text=_extract_term_text(lunar_obj),
        holiday_names=_extract_holidays(lunar_obj),
        memorial_names=tuple(memorial_names or ()),
        has_lunar_data=lunar_obj is not None,
        lunar_lib_available=bool(has_cnlunar),
    )


def render_html(parts: InfoParts) -> Optional[str]:
    """有内容返回 HTML 字符串；无任何内容返回 None。"""
    pieces = []
    if parts.lunar_str:
        pieces.append(
            f"<span style='color:#5A5A5A'>"
            f"{html.escape(parts.lunar_str)}</span>")
    if parts.term_text:
        pieces.append(
            f"<span style='color:#2E7D32'>"
            f"{html.escape(tr('info.solar_term'))}："
            f"{html.escape(parts.term_text)}</span>")
    if parts.holiday_names:
        joined = html.escape("".join(parts.holiday_names))
        pieces.append(
            f"<span style='color:#C96068'>"
            f"{html.escape(tr('info.festival'))}：{joined}</span>")
    if parts.memorial_names:
        joined = html.escape("、".join(parts.memorial_names))
        pieces.append(
            f"<span style='color:#D47026'>"
            f"{html.escape(tr('info.memorial'))}：{joined}</span>")
    if not pieces:
        return None
    return " &nbsp;｜&nbsp; ".join(pieces)


def placeholder_key(parts: InfoParts) -> str:
    """无内容时返回占位文案的 i18n key。"""
    if not parts.lunar_lib_available:
        return "info.no_cnlunar"
    if not parts.has_lunar_data:
        return "info.lunar_unavailable"
    return "info.no_events"