# coding: utf-8
# ⚠️ 本文件有改动：P1-1 消除 get_legalHolidays() 重复调用
from datetime import date
from typing import Dict, Tuple, List, Any, Optional

from PyQt6.QtCore import Qt, QDate, QRect, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QFont, QColor, QTextCharFormat, QPainter, QPen,
)
from PyQt6.QtWidgets import QCalendarWidget, QLabel
from config import log_exception, get_logger

# [FIX-4] 用 `import lunar as lunar_mod` 而非 `from utils import HAS_CHNCAL`：
#   * 原实现拿到的是导入期快照，运行时 monkeypatch lunar.HAS_CHNCAL
#     不会反映到本模块，测试无法模拟"无 cnlunar"环境。
#   * 用 as lunar_mod 而非 lunar，避免与 get_lunar_cell_text 的参数
#     名 `lunar` 冲突。
import lunar as lunar_mod
from utils import (
    get_lunar_by_datetime, match_memorial_date,
    is_holiday, is_workday, qdate_to_pydate,
)
# 【索引构建需要】normalize_memorial 与 REPEAT_* 来自 memorial.py，
# 经 utils 的 `from memorial import *` 已可见；这里直接 import 更清晰。
from memorial import (
    normalize_memorial, REPEAT_YEAR, REPEAT_MONTH, REPEAT_WEEK,
)
from constants import (
    LUNAR_FESTIVALS, SOLAR_FESTIVALS, FESTIVAL_NAME_MAP,
    RED_TEXT_SET, MONTH_CN, NUM_CN_MAP,
)

logger = get_logger()

# 农历文字“类型”用显式常量代替布尔
_CELL_NORMAL = "normal"       # 普通农历文字
_CELL_MEMORIAL = "memorial"   # 纪念日（橙色高亮）
_CELL_RED = "red"             # 农历传统节日 / 除夕（红色高亮）

# 【P1-1】哨兵：区分"尚未查询"与"确实没有法定节日"两种语义
_UNSET = object()

# 单元格绘制用到的所有颜色键 → 默认值。
# 集中在此，避免 paintCell 每次重绘都做 theme.get + QColor(str) 解析。
# 注意：必须覆盖 paintCell / _fix_week_header_color 里访问的所有键，
# 否则换主题后会 KeyError。
_COLOR_DEFAULTS = {
    "weekend_header_red":    "#d62728",
    "calendar_header_text":  "#000000",
    "adjacent_cell_bg":      "#e9e6e1",
    "adjacent_text_color":   "#bbbbbb",
    "today_bg":              "#e6f7ff",
    "select_bg":             "#cce5ff",
    "normal_cell_bg":        "#ffffff",
    "today_text_color":      "#0066cc",
    "select_text_color":     "#004085",
    "festival_red":          "#d62728",
    "workday_orange":        "#ff7800",
    "normal_num_color":      "#333333",
    "memorial_orange":       "#ff7824",
    "normal_lunar_color":    "#666666",
    "tag_bg":                "#222222",
    "tag_text_color":        "#ffffff",
}

class ClickLabel(QLabel):
    """可点击的Label控件，【当前模块未被使用，保留供后续扩展】"""
    clicked = pyqtSignal()

    def __init__(self, text: str = ""):
        super().__init__(text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

class LunarCalendarWidget(QCalendarWidget):
    """自定义农历日历控件：月份数据预计算缓存"""

    def __init__(self, parent, theme: Dict[str, Any],
                 memorial_list: List[Dict[str, Any]]):
        super().__init__(parent)
        self._theme = theme
        self.memorial_list = memorial_list
        self._memorial_index = self._build_memorial_index(memorial_list)
        self.net_holiday_data: Dict[str, bool] = {}

        # 当月单元格数据缓存：key = QDate.toJulianDay()
        self._cell_cache: Dict[int, dict] = {}
        self._cached_year = -1
        self._cached_month = -1

        # 异常上报去重集合，key 示例 paintCell:2025-01-01
        self._reported_errors: set = set()

        self._apply_theme(theme)
        self._fix_week_header_color()
        self.currentPageChanged.connect(self._on_page_changed)
        self._rebuild_cell_cache(self.yearShown(), self.monthShown())

    # ---------------- 纪念日索引 ----------------
    def _build_memorial_index(
        self, memorial_list: List[Dict[str, Any]]
    ) -> Dict[str, Dict[Any, List[Dict[str, Any]]]]:
        """
        构建纪念日索引，把"逐日遍历整表"（42×N）降为"逐日 O(1) 查表"。

        索引结构（值均为已 normalize 的 dict 列表，保留输入顺序）：
          solar_year[(month, day)]           → [...]   # 公历每年重复
          solar_month[day]                   → [...]   # 公历每月重复
          solar_week[weekday 1..7]           → [...]   # 每周重复（强制公历）
          lunar_year[(month, day, isleap)]   → [...]   # 农历每年重复
          lunar_month[(day, isleap)]         → [...]   # 农历每月重复

        说明：
        - normalize_memorial 会修正非法 type/repeat_type、clamp 数值，
          保证入库的 key 合法。
        - 未启用项直接跳过。
        - 非 dict 项、normalize 失败项静默忽略，不中断整表构建。
        - 桶内保留输入顺序；多个纪念日命中同一天时返回桶内第一条。
        """
        idx: Dict[str, Dict[Any, List[Dict[str, Any]]]] = {
            "solar_year": {},
            "solar_month": {},
            "solar_week": {},
            "lunar_year": {},
            "lunar_month": {},
        }
        if not isinstance(memorial_list, (list, tuple)):
            return idx

        for mem in memorial_list:
            if not isinstance(mem, dict):
                continue
            if not mem.get("enabled", True):
                continue
            try:
                m = normalize_memorial(mem)
            except Exception:
                # 单条坏数据不影响整表
                continue

            rep = m["repeat_type"]
            typ = m["type"]

            if rep == REPEAT_WEEK:
                # normalize_memorial 已强制 type=solar / isleap=False
                idx["solar_week"].setdefault(m["day"], []).append(m)
            elif typ == "solar":
                if rep == REPEAT_YEAR:
                    key = (m["month"], m["day"])
                    idx["solar_year"].setdefault(key, []).append(m)
                else:  # REPEAT_MONTH
                    idx["solar_month"].setdefault(m["day"], []).append(m)
            else:  # typ == "lunar"
                leap = bool(m.get("isleap", False))
                if rep == REPEAT_YEAR:
                    key = (m["month"], m["day"], leap)
                    idx["lunar_year"].setdefault(key, []).append(m)
                else:  # REPEAT_MONTH
                    key = (m["day"], leap)
                    idx["lunar_month"].setdefault(key, []).append(m)

        return idx

    # ---------------- 字体 + 尺寸应用集中到一处 ----------------
    def _apply_theme(self, theme: dict):
        """
        构造与换主题时共用：字体 + 尺寸 + 颜色缓存 + 无画笔。
        """
        font_family = theme.get("font_family", "微软雅黑").split(",")[0].strip()
        font_size = theme.get("font_size", 10)
        small_font_size = theme.get("small_font_size", 7)

        day_font = QFont(font_family, font_size)
        day_font.setPixelSize(font_size)
        small_font = QFont(font_family, small_font_size)
        small_font.setPixelSize(small_font_size)

        self._day_font = day_font
        self._small_font = small_font
        self.dot_size = int(theme.get("dot_size", 6))
        self.tag_size = int(theme.get("tag_size", 14))
        self.cell_radius = int(theme.get("cell_corner_radius", 8))

        # 合并主题颜色和默认颜色：paintCell 直接用 self._colors[key]，
        # 省下每次重绘 ~200 次 QColor(str) hex 解析。
        self._colors: Dict[str, QColor] = {}
        for k, default_val in _COLOR_DEFAULTS.items():
            self._colors[k] = QColor(theme.get(k, default_val))

        # NoPen 也预构造（Qt 的 QPen 不是轻量值类型）。
        self._no_pen = QPen(Qt.PenStyle.NoPen)

    # ---------------- 异常去重上报 ----------------
    def _log_exception_once(self, key: str, message: str):
        """
        同一 key 在整个 widget 生命周期内只上报一次。
        paintCell / get_lunar_cell_text 逐单元格调用，防止大量
        相同异常刷屏日志。
        """
        if key in self._reported_errors:
            return
        self._reported_errors.add(key)
        log_exception(message)

    def _on_page_changed(self, year: int, month: int):
        """切换月份时预计算整月数据"""
        self._rebuild_cell_cache(year, month)

    def _rebuild_cell_cache(self, year: int, month: int):
        """预计算当月所有日期的单元格数据；相邻月由 paintCell 直接跳过。"""
        # 错误集合超限清理，避免内存持续上涨
        if len(self._reported_errors) > 2000:
            self._reported_errors.clear()

        self._cell_cache.clear()
        self._cached_year = year
        self._cached_month = month

        first = QDate(year, month, 1)
        days = first.daysInMonth()
        for day in range(1, days + 1):
            d = QDate(year, month, day)
            self._cell_cache[d.toJulianDay()] = self._calc_cell_data(d)

    # ---------------- 【P1-1】法定节日一次性提取 ----------------
    @staticmethod
    def _first_legal_holiday_raw(lunar) -> Optional[str]:
        """
        取 lunar.get_legalHolidays() 的第一个有效名称；
        无结果 / 全部无效 / lunar 为空时返回 None。

        【P1-1】集中此逻辑，供 get_lunar_cell_text 与 _is_legal_holiday
        共用。调用方通过 _calc_cell_data 预取一次后向下传递，避免
        cnlunar 在单个单元格上被调用两次。
        """
        if lunar is None:
            return None
        try:
            f_list = lunar.get_legalHolidays()
        except Exception:
            return None
        if not f_list:
            return None
        raw = f_list[0] if isinstance(f_list, (list, tuple)) else f_list
        if not raw or raw == "无":
            return None
        return raw

    def _calc_cell_data(self, qdate: QDate) -> dict:
        """
        计算单个日期的所有显示数据。
        农历对象只查询一次，向下传给需要它的子函数，减少重复调用。
        """
        lunar = self.get_day_lunar_obj(qdate)
        # 【P1-1】预取一次法定节日，向下传，避免 get_lunar_cell_text
        # 与 _is_legal_holiday 各调一次 get_legalHolidays()
        legal_raw = self._first_legal_holiday_raw(lunar)
        lunar_text, kind = self.get_lunar_cell_text(
            qdate, lunar=lunar, legal_raw=legal_raw)
        is_hol = self.is_date_holiday(qdate)
        is_weekend_work = self.is_weekend_workday(qdate)
        is_legal_hol = self._is_legal_holiday(
            qdate, lunar=lunar, legal_raw=legal_raw)
        return {
            "lunar_text": lunar_text,
            "kind": kind,
            "is_hol": is_hol,
            "is_weekend_work": is_weekend_work,
            "is_legal_hol": is_legal_hol,
        }

    def set_memorial_list(self, ml: List[Dict[str, Any]]):
        """更新纪念日列表：重建索引 + 重建缓存。"""
        self.memorial_list = ml
        self._memorial_index = self._build_memorial_index(ml)
        self._rebuild_cell_cache(self.yearShown(), self.monthShown())
        self.update()

    def update_theme(self, new_theme: dict):
        """更新主题，只更新绘制属性，不重新计算农历/纪念日缓存"""
        self._theme = new_theme
        self._apply_theme(new_theme)
        self._fix_week_header_color()
        self.update()

    def _fix_week_header_color(self):
        """
        星期表头颜色：周一~周五用 calendar_header_text，
        周六~周日用 weekend_header_red。
        """
        red_fmt = QTextCharFormat()
        red_fmt.setForeground(self._colors["weekend_header_red"])
        normal_fmt = QTextCharFormat()
        normal_fmt.setForeground(self._colors["calendar_header_text"])

        for dow in (Qt.DayOfWeek.Monday, Qt.DayOfWeek.Tuesday,
                    Qt.DayOfWeek.Wednesday, Qt.DayOfWeek.Thursday,
                    Qt.DayOfWeek.Friday):
            self.setWeekdayTextFormat(dow, normal_fmt)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, red_fmt)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, red_fmt)

    def get_day_lunar_obj(self, qdate: QDate) -> Optional[Any]:
        """获取某一天农历对象，失败返回 None"""
        # [FIX-4] 动态读取 lunar_mod.HAS_CHNCAL，而非导入期快照
        if not lunar_mod.HAS_CHNCAL:
            return None
        try:
            return get_lunar_by_datetime(
                (qdate.year(), qdate.month(), qdate.day())
            )
        except Exception:
            logger.debug(
                f"实时农历转换失败 date={qdate.toString('yyyy-MM-dd')}",
                exc_info=True,
            )
            return None

    def get_lunar_cell_text(self, qdate: QDate, lunar=None,
                            legal_raw=_UNSET) -> Tuple[str, str]:
        """
        返回 (显示文本, 单元格类型)。

        - 公历纪念日匹配放在最前，且不依赖 cnlunar，保证无农历库时
          纯公历纪念日仍能正常显示。
        - lunar 为可选预取对象，由 _calc_cell_data 一次取好后传入。
        - legal_raw 为可选预取"法定节日原始名"，同样由 _calc_cell_data
          传入；_UNSET 表示未预取，本函数自行查询一次。
        - 命中优先级（与原实现一致）：公历纪念日 → 农历纪念日 →
          除夕 → 法定节日 → 农历传统节日 → 公历节日 → 节气 → 农历日期。
        """
        try:
            # ---------- 公历纪念日（无需农历对象）----------
            mems = self._memorial_index["solar_year"].get(
                (qdate.month(), qdate.day()))
            if mems:
                return (mems[0].get("name") or "纪念日"), _CELL_MEMORIAL

            mems = self._memorial_index["solar_week"].get(qdate.dayOfWeek())
            if mems:
                return (mems[0].get("name") or "纪念日"), _CELL_MEMORIAL

            mems = self._memorial_index["solar_month"].get(qdate.day())
            if mems:
                return (mems[0].get("name") or "纪念日"), _CELL_MEMORIAL

            # ---------- 以下需要农历对象 ----------
            # [FIX-4] 动态读取，测试可 monkeypatch lunar.HAS_CHNCAL 模拟无库
            if not lunar_mod.HAS_CHNCAL:
                return "", _CELL_NORMAL
            if lunar is None:
                lunar = self.get_day_lunar_obj(qdate)
            if not lunar:
                return "", _CELL_NORMAL

            lunar_month = getattr(lunar, 'lunarMonth', 0)
            lunar_day = getattr(lunar, 'lunarDay', 0)
            is_leap = bool(getattr(lunar, 'isLunarLeapMonth', False))

            # 农历纪念日
            mems = self._memorial_index["lunar_year"].get(
                (lunar_month, lunar_day, is_leap))
            if mems:
                return (mems[0].get("name") or "纪念日"), _CELL_MEMORIAL

            mems = self._memorial_index["lunar_month"].get(
                (lunar_day, is_leap))
            if mems:
                return (mems[0].get("name") or "纪念日"), _CELL_MEMORIAL

            # 除夕（红色）：腊月最后一天，次日为正月初一
            if not is_leap and lunar_month == 12:
                next_lunar = self.get_day_lunar_obj(qdate.addDays(1))
                if (next_lunar
                        and getattr(next_lunar, "lunarMonth", None) == 1
                        and getattr(next_lunar, "lunarDay", None) == 1):
                    return "除夕", _CELL_RED

            # 法定节日（名称映射后若在 RED_TEXT_SET 中则标红）
            # 【P1-1】legal_raw 已由 _calc_cell_data 预取；未预取则本地查询
            if legal_raw is _UNSET:
                legal_raw = self._first_legal_holiday_raw(lunar)
            if legal_raw is not None:
                name = FESTIVAL_NAME_MAP.get(legal_raw, legal_raw)
                return name, (_CELL_RED if name in RED_TEXT_SET
                              else _CELL_NORMAL)

            # 农历传统节日（全部红色；闰月不算传统节日）
            if not is_leap and (lunar_month, lunar_day) in LUNAR_FESTIVALS:
                return LUNAR_FESTIVALS[(lunar_month, lunar_day)], _CELL_RED

            # 公历节日（灰色）
            if (qdate.month(), qdate.day()) in SOLAR_FESTIVALS:
                return SOLAR_FESTIVALS[(qdate.month(), qdate.day())], _CELL_NORMAL

            # 节气（灰色）
            term_name = getattr(lunar, "todaySolarTerms", "")
            if isinstance(term_name, list) and term_name:
                term_name = term_name[0]
            if term_name and term_name != "无":
                return term_name, _CELL_NORMAL

            # 普通农历日期
            if lunar_day == 1:
                prefix = "闰" if is_leap else ""
                return f"{prefix}{MONTH_CN[lunar_month]}", _CELL_NORMAL
            return NUM_CN_MAP.get(str(lunar_day), str(lunar_day)), _CELL_NORMAL

        except Exception:
            date_str = qdate.toString('yyyy-MM-dd')
            self._log_exception_once(
                f"get_lunar_cell_text:{date_str}",
                f"解析农历文本失败 date={date_str}",
            )
            return "", _CELL_NORMAL

    def is_date_holiday(self, qdate: QDate) -> bool:
        """判断是否节假日（网络数据优先，其次chinese_calendar，降级周末判断）"""
        try:
            s_key = qdate.toString("yyyy-MM-dd")
            if s_key in self.net_holiday_data:
                return self.net_holiday_data[s_key]
            # [FIX-4] 动态读取 HAS_CHINESE_CAL
            if lunar_mod.HAS_CHINESE_CAL:
                return is_holiday(qdate_to_pydate(qdate))
            # 降级：周六周日视为节假日
            return qdate_to_pydate(qdate).weekday() >= 5
        except Exception:
            logger.debug(
                f"is_holiday 查询降级 date={qdate.toString('yyyy-MM-dd')}",
                exc_info=True,
            )
            return False

    def is_weekend_workday(self, qdate: QDate) -> bool:
        """判断是否周末调休工作日（班）"""
        try:
            s_key = qdate.toString("yyyy-MM-dd")
            # 非周末直接返回 False；避免非周末被网络数据误判为"班"
            if qdate.dayOfWeek() not in (6, 7):
                return False
            if s_key in self.net_holiday_data:
                return self.net_holiday_data[s_key] is False
            # [FIX-4] 动态读取 HAS_CHINESE_CAL
            if lunar_mod.HAS_CHINESE_CAL:
                return is_workday(qdate_to_pydate(qdate))
            return False
        except Exception:
            logger.debug(
                f"is_workday 查询降级 date={qdate.toString('yyyy-MM-dd')}",
                exc_info=True,
            )
            return False

    def _is_legal_holiday(self, qdate: QDate, lunar=None,
                          legal_raw=_UNSET) -> bool:
        """
        判断是否农历库识别的法定节假日。
        【P1-1】可传入预取的 lunar 与 legal_raw，避免重复调用
        cnlunar.get_legalHolidays()。
        """
        s_key = qdate.toString("yyyy-MM-dd")
        if s_key in self.net_holiday_data:
            return self.net_holiday_data[s_key]
        # [FIX-4] 动态读取
        if not lunar_mod.HAS_CHNCAL:
            return False
        if legal_raw is _UNSET:
            if lunar is None:
                lunar = self.get_day_lunar_obj(qdate)
            legal_raw = self._first_legal_holiday_raw(lunar)
        return legal_raw is not None

    def paintCell(self, painter: QPainter, rect: QRect, qdate: QDate):
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            is_current_month = (qdate.year() == self.yearShown()
                                and qdate.month() == self.monthShown())
            r = self.cell_radius
            bg_rect = QRectF(rect.adjusted(2, 2, -2, -2))

            # ===== 相邻月 =====
            if not is_current_month:
                painter.setBrush(self._colors["adjacent_cell_bg"])
                painter.setPen(self._no_pen)
                painter.drawRoundedRect(bg_rect, r, r)
                painter.setFont(self._day_font)
                painter.setPen(self._colors["adjacent_text_color"])
                painter.drawText(
                    rect.adjusted(4, 3, -4, -9),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    str(qdate.day()),
                )
                return

            # ===== 当前月 =====
            is_selected = (qdate == self.selectedDate())
            is_today = (qdate == QDate.currentDate())
            key = qdate.toJulianDay()
            cell = self._cell_cache.get(key)
            # 兜底：极端情况下缓存缺失，现场计算并回填
            if cell is None:
                cell = self._calc_cell_data(qdate)
                self._cell_cache[key] = cell

            kind = cell["kind"]
            is_hol = cell["is_hol"]
            is_weekend_work = cell["is_weekend_work"]
            is_legal_hol = cell["is_legal_hol"]
            lunar_text = cell["lunar_text"]

            # 绘制背景
            if is_today:
                bg = self._colors["today_bg"]
            elif is_selected:
                bg = self._colors["select_bg"]
            else:
                bg = self._colors["normal_cell_bg"]
            painter.setBrush(bg)
            painter.setPen(self._no_pen)
            painter.drawRoundedRect(bg_rect, r, r)

            # 公历数字
            painter.setFont(self._day_font)
            day_rect = rect.adjusted(4, 3, -4, -9)
            if is_today:
                painter.setPen(self._colors["today_text_color"])
            elif is_selected:
                painter.setPen(self._colors["select_text_color"])
            elif is_hol:
                painter.setPen(self._colors["festival_red"])
            elif is_weekend_work:
                painter.setPen(self._colors["workday_orange"])
            else:
                painter.setPen(self._colors["normal_num_color"])
            painter.drawText(
                day_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                str(qdate.day()),
            )

            # 农历小字
            painter.setFont(self._small_font)
            if kind == _CELL_MEMORIAL:
                painter.setPen(self._colors["memorial_orange"])
            elif kind == _CELL_RED:
                painter.setPen(self._colors["festival_red"])
            elif is_weekend_work:
                painter.setPen(self._colors["workday_orange"])
            else:
                painter.setPen(self._colors["normal_lunar_color"])

            lunar_rect = rect.adjusted(4, 9, -4, -2)
            painter.drawText(
                lunar_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                lunar_text,
            )

            # 右上角「班」标签
            if is_weekend_work:
                tag_size = self.tag_size
                x = rect.right() - tag_size - 4
                y = rect.top() + 4
                painter.setBrush(self._colors["tag_bg"])
                painter.setPen(self._no_pen)
                painter.drawRoundedRect(x, y, tag_size, tag_size, 4, 4)
                painter.setFont(self._small_font)
                painter.setPen(self._colors["tag_text_color"])
                painter.drawText(
                    QRectF(x, y, tag_size, tag_size),
                    Qt.AlignmentFlag.AlignCenter,
                    "班",
                )

            # 圆点标记：纪念日 / 法定节假日
            dot_color = None
            if kind == _CELL_MEMORIAL:
                dot_color = self._colors["memorial_orange"]
            elif is_legal_hol:
                dot_color = self._colors["festival_red"]
            if dot_color is not None:
                painter.setBrush(dot_color)
                painter.setPen(self._no_pen)
                # 如果画了班标签，圆点放到左上角，否则右上角
                x = (rect.left() + 4 if is_weekend_work
                     else rect.right() - self.dot_size - 4)
                y = rect.top() + 4
                painter.drawEllipse(x, y, self.dot_size, self.dot_size)

        except Exception:
            date_str = qdate.toString('yyyy-MM-dd')
            self._log_exception_once(
                f"paintCell:{date_str}",
                f"paintCell单元格渲染异常 date={date_str}",
            )
        finally:
            try:
                painter.restore()
            except RuntimeError:
                pass

    def set_net_holiday(self, holiday_data: Dict[str, bool]):
        """设置网络获取的节假日数据，重新生成单元格缓存并重绘"""
        try:
            self.net_holiday_data = holiday_data
            logger.info(f"加载网络节假日数据，共{len(holiday_data)}条")
            self._rebuild_cell_cache(self.yearShown(), self.monthShown())
            self.update()
        except Exception as e:
            log_exception(f"set_net_holiday 加载节假日数据失败: {e}")