# coding: utf-8
from datetime import date
from typing import Dict, Tuple

from PyQt6.QtCore import Qt, QDate, QRect, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QFont, QColor, QTextCharFormat, QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import QCalendarWidget, QLabel
from config import log_exception, get_logger
from utils import (
    get_lunar_by_datetime, lunar_to_gregorian, match_memorial_date,
    HAS_CHNCAL, HAS_CHINESE_CAL, is_holiday, is_workday, qdate_to_pydate,
    normalize_memorial, REPEAT_YEAR, REPEAT_MONTH, REPEAT_WEEK,
)
from constants import (
    LUNAR_FESTIVALS, SOLAR_FESTIVALS, FESTIVAL_NAME_MAP,
    RED_TEXT_SET, MONTH_CN, NUM_CN_MAP, UPCOMING_REMIND_DAYS,
)
logger=get_logger()

# 农历文字“类型”用显式常量代替布尔
_CELL_NORMAL = "normal"       # 普通农历文字
_CELL_MEMORIAL = "memorial"   # 纪念日（橙色高亮）
_CELL_RED = "red"             # 农历传统节日 / 除夕（红色高亮）


class ClickLabel(QLabel):
    """可点击的Label控件"""
    clicked = pyqtSignal()

    def __init__(self, text: str = ""):
        super().__init__(text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class LunarCalendarWidget(QCalendarWidget):
    """自定义农历日历控件：月份数据预计算缓存"""

    def __init__(self, parent, theme, memorial_list):
        super().__init__(parent)
        self._theme = theme
        self.memorial_list = memorial_list
        self.net_holiday_data: Dict[str, bool] = {}
        # 当月单元格数据缓存：key = QDate.toJulianDay()
        self._cell_cache: Dict[int, dict] = {}
        self._cached_year = -1
        self._cached_month = -1
        # 【日志改造】paintCell / get_lunar_cell_text 出真 bug 时每个 key
        # 只上报一次，避免 42 个单元格同时失败把日志刷爆。
        self._reported_errors: set = set()
        # 字体 + 尺寸集中到 _apply_theme
        self._apply_theme(theme)
        self._fix_week_header_color()
        self.currentPageChanged.connect(self._on_page_changed)
        self._rebuild_cell_cache(self.yearShown(), self.monthShown())

    # ---------------- 字体 + 尺寸应用集中到一处 ----------------
    def _apply_theme(self, theme: dict):
        """
        构造与换主题时共用：字体 + 尺寸常量。
        【Item 2】dot_size / tag_size / cell_radius 改为从主题读取。
        """
        font_family = theme.get("font_family", "微软雅黑").split(",")[0].strip()
        font_size = theme.get("font_size", 10)
        self._day_font = QFont(font_family, font_size)
        # 避免极小字号导致字体无法显示
        self._small_font = QFont(font_family, max(6, font_size - 4))

        self.dot_size = int(theme.get("dot_size", 6))
        self.tag_size = int(theme.get("tag_size", 14))
        self.cell_radius = int(theme.get("cell_corner_radius", 8))

    # ---------------- 【日志改造】异常去重上报 ----------------
    def _log_exception_once(self, key: str, message: str):
        """
        同一 key 的异常在整个 widget 生命周期内只上报一次。

        为什么需要：paintCell / get_lunar_cell_text 是逐单元格调用的，
        一次重绘就会跑 42 次。一旦出现真 bug，42 条 traceback 会淹没
        其它有用的日志。按 key 去重既保留了「有 bug 要发现」的能力，
        也不会刷屏。
        """
        if key in self._reported_errors:
            return
        self._reported_errors.add(key)
        log_exception(message)

    def _on_page_changed(self, year: int, month: int):
        """切换月份时预计算整月数据"""
        self._rebuild_cell_cache(year, month)

    def _rebuild_cell_cache(self, year: int, month: int):
        """预计算当月所有日期的单元格数据；相邻月由 paintCell 直接跳过"""
        self._cell_cache.clear()
        self._cached_year = year
        self._cached_month = month
        first = QDate(year, month, 1)
        days = first.daysInMonth()
        for day in range(1, days + 1):
            d = QDate(year, month, day)
            self._cell_cache[d.toJulianDay()] = self._calc_cell_data(d)

    def _calc_cell_data(self, qdate: QDate) -> dict:
        """计算单个日期的所有显示数据"""
        lunar_text, kind = self.get_lunar_cell_text(qdate)
        is_hol = self.is_date_holiday(qdate)
        is_weekend_work = self.is_weekend_workday(qdate)
        is_legal_hol = self._is_legal_holiday(qdate)
        return {
            "lunar_text": lunar_text,
            "kind": kind,
            "is_hol": is_hol,
            "is_weekend_work": is_weekend_work,
            "is_legal_hol": is_legal_hol,
        }

    def set_memorial_list(self, ml):
        """更新纪念日列表：重建缓存"""
        self.memorial_list = ml
        self._rebuild_cell_cache(self.yearShown(), self.monthShown())
        self.update()

    def update_theme(self, new_theme: dict):
        self._theme = new_theme
        self._apply_theme(new_theme)
        self._fix_week_header_color()
        self.update()

    def _fix_week_header_color(self):
        fmt = QTextCharFormat()
        color_str = self._theme.get("weekend_header_red", "#d62728")
        fmt.setForeground(QColor(color_str))
        self.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, fmt)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, fmt)

    def get_day_lunar_obj(self, qdate: QDate):
        if not HAS_CHNCAL:
            return None
        try:
            return get_lunar_by_datetime(
                (qdate.year(), qdate.month(), qdate.day())
            )
        except Exception:
            # 单点转换失败不影响整月渲染；cnlunar 本身失败时已返回 None，
            # 能走到这里基本是参数格式问题 —— 属预期降级，降到 debug。
            get_logger.debug(
                f"实时农历转换失败 date={qdate.toString('yyyy-MM-dd')}",
                exc_info=True,
            )
            return None

    def get_lunar_cell_text(self, qdate: QDate) -> Tuple[str, str]:
        """
        返回 (农历文字, 类型)。类型为 _CELL_NORMAL / _CELL_MEMORIAL / _CELL_RED。
        """
        if not HAS_CHNCAL:
            return "", _CELL_NORMAL
        try:
            lunar = self.get_day_lunar_obj(qdate)
            if not lunar:
                return "", _CELL_NORMAL
            lunar_month = getattr(lunar, 'lunarMonth', 0)
            lunar_day = getattr(lunar, 'lunarDay', 0)
            is_leap = getattr(lunar, 'isLunarLeapMonth', False)

            # 纪念日优先
            for mem in self.memorial_list:
                if not mem.get("enabled", True):
                    continue
                if match_memorial_date(mem, qdate):
                    return (mem.get("name") or "纪念日"), _CELL_MEMORIAL

            # 除夕（红色）
            if not is_leap and lunar_month == 12:
                next_lunar = self.get_day_lunar_obj(qdate.addDays(1))
                if (next_lunar and next_lunar.lunarMonth == 1
                        and next_lunar.lunarDay == 1):
                    return "除夕", _CELL_RED

            # 法定节日（名称映射后若在 RED_TEXT_SET 中则标红）
            f1 = lunar.get_legalHolidays()
            if f1:
                name = FESTIVAL_NAME_MAP.get(f1, f1)
                return name, (_CELL_RED if name in RED_TEXT_SET else _CELL_NORMAL)

            # 农历传统节日（全部红色）
            if not is_leap and (lunar_month, lunar_day) in LUNAR_FESTIVALS:
                return LUNAR_FESTIVALS[(lunar_month, lunar_day)], _CELL_RED

            # 公历节日（灰色）
            if (qdate.month(), qdate.day()) in SOLAR_FESTIVALS:
                return SOLAR_FESTIVALS[(qdate.month(), qdate.day())], _CELL_NORMAL

            # 节气
            term_name = getattr(lunar, "todaySolarTerms", "")
            if isinstance(term_name, list) and term_name:
                term_name = term_name[0]
            if term_name and term_name != "无":
                return term_name, _CELL_NORMAL

            # 普通农历日期
            if lunar_day == 1:
                prefix = "闰" if is_leap else ""
                return f"{prefix}{MONTH_CN[lunar_month]}", _CELL_NORMAL
            else:
                return NUM_CN_MAP.get(str(lunar_day), str(lunar_day)), _CELL_NORMAL
        except Exception:
            # 这里能触发说明是真正的 bug（KeyError / 类型错误等），
            # 但每个单元格都会重复 → 按 key 去重
            self._log_exception_once(
                "get_lunar_cell_text",
                f"解析农历文本失败 date={qdate.toString('yyyy-MM-dd')}",
            )
            return "", _CELL_NORMAL

    def is_date_holiday(self, qdate: QDate) -> bool:
        try:
            s_key = qdate.toString("yyyy-MM-dd")
            if s_key in self.net_holiday_data:
                return self.net_holiday_data[s_key]
            if HAS_CHINESE_CAL:
                return is_holiday(qdate_to_pydate(qdate))
            return qdate_to_pydate(qdate).weekday() >= 5
        except Exception:
            # chinese_calendar 对超出其支持范围的年份会抛错（已知限制），
            # 整月 42 个单元格都会触发 → 降到 debug。真需要排查时开 DEBUG。
            logger.debug(
                f"is_holiday 查询降级 date={qdate.toString('yyyy-MM-dd')}",
                exc_info=True,
            )
            return False

    def is_weekend_workday(self, qdate: QDate) -> bool:
        try:
            s_key = qdate.toString("yyyy-MM-dd")
            if qdate.dayOfWeek() not in (6, 7):
                return False
            if s_key in self.net_holiday_data:
                return self.net_holiday_data[s_key] is False
            if HAS_CHINESE_CAL:
                return is_workday(qdate_to_pydate(qdate))
            return False
        except Exception:
            # 同上：chinese_calendar 年份越界属已知降级路径
            logger.debug(
                f"is_workday 查询降级 date={qdate.toString('yyyy-MM-dd')}",
                exc_info=True,
            )
            return False

    def _is_legal_holiday(self, qdate: QDate) -> bool:
        s_key = qdate.toString("yyyy-MM-dd")
        if s_key in self.net_holiday_data:
            return self.net_holiday_data[s_key]
        if HAS_CHNCAL:
            lunar = self.get_day_lunar_obj(qdate)
            if lunar and lunar.get_legalHolidays():
                return True
        return False

    def paintCell(self, painter: QPainter, rect: QRect, date: QDate):
        # 【P0-1】painter.save() 与 finally 里的 restore() 严格配对。
        # 原实现在 try 内 save、try 内 restore，中间任何异常都会导致
        # restore 被跳过，画笔/字体/renderHint 泄漏到后续单元格。
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            is_current_month = (date.year() == self.yearShown()
                                and date.month() == self.monthShown())

            # ===== 相邻月：填充 + 绘制后直接 return，restore 由 finally 负责 =====
            if not is_current_month:
                path = QPainterPath()
                r = self.cell_radius
                path.addRoundedRect(QRectF(rect.adjusted(2, 2, -2, -2)), r, r)
                painter.fillPath(
                    path,
                    QColor(self._theme.get("adjacent_cell_bg", "#e9e6e1")),
                )
                painter.setFont(self._day_font)
                painter.setPen(
                    QColor(self._theme.get("adjacent_text_color", "#bbbbbb"))
                )
                painter.drawText(
                    rect.adjusted(4, 3, -4, -9),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    str(date.day()),
                )
                return

            # ===== 当前月：以下逻辑保持原样 =====
            is_selected = (date == self.selectedDate())
            is_today = (date == QDate.currentDate())

            key = date.toJulianDay()
            cell = self._cell_cache.get(key)
            if cell is None:
                cell = self._calc_cell_data(date)
                self._cell_cache[key] = cell

            kind = cell["kind"]
            is_hol = cell["is_hol"]
            is_weekend_work = cell["is_weekend_work"]
            is_legal_hol = cell["is_legal_hol"]
            lunar_text = cell["lunar_text"]

            path = QPainterPath()
            r = self.cell_radius
            path.addRoundedRect(QRectF(rect.adjusted(2, 2, -2, -2)), r, r)
            if is_today:
                painter.fillPath(path, QColor(self._theme.get("today_bg", "#e6f7ff")))
            elif is_selected:
                painter.fillPath(path, QColor(self._theme.get("select_bg", "#cce5ff")))
            else:
                painter.fillPath(path, QColor(self._theme.get("normal_cell_bg", "#ffffff")))

            # 公历数字
            painter.setFont(self._day_font)
            day_rect = rect.adjusted(4, 3, -4, -9)
            if is_today:
                painter.setPen(QColor(self._theme.get("today_text_color", "#0066cc")))
            elif is_selected:
                painter.setPen(QColor(self._theme.get("select_text_color", "#004085")))
            elif is_hol:
                painter.setPen(QColor(self._theme.get("festival_red", "#d62728")))
            elif is_weekend_work:
                painter.setPen(QColor(self._theme.get("workday_orange", "#ff7824")))
            else:
                painter.setPen(QColor(self._theme.get("normal_num_color", "#333333")))
            painter.drawText(
                day_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                str(date.day()),
            )

            # 农历小字
            painter.setFont(self._small_font)
            if kind == _CELL_MEMORIAL:
                painter.setPen(QColor(self._theme.get("memorial_orange", "#ff7824")))
            elif kind == _CELL_RED:
                painter.setPen(QColor(self._theme.get("festival_red", "#d62728")))
            elif is_weekend_work:
                painter.setPen(QColor(self._theme.get("workday_orange", "#ff7824")))
            else:
                painter.setPen(QColor(self._theme.get("normal_lunar_color", "#666666")))
            lunar_rect = rect.adjusted(4, 9, -4, -2)
            painter.drawText(
                lunar_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                lunar_text,
            )

            # 右上角「班」
            if is_weekend_work:
                tag_size = self.tag_size
                x = rect.right() - tag_size - 4
                y = rect.top() + 4
                painter.setBrush(QColor(self._theme.get("tag_bg", "#222222")))
                painter.setPen(QPen(Qt.PenStyle.NoPen))
                painter.drawRoundedRect(x, y, tag_size, tag_size, 4, 4)
                painter.setFont(self._small_font)
                painter.setPen(QColor(self._theme.get("tag_text_color", "#ffffff")))
                painter.drawText(
                    QRectF(x, y, tag_size, tag_size),
                    Qt.AlignmentFlag.AlignCenter,
                    "班",
                )

            # 圆点
            dot_color = None
            if kind == _CELL_MEMORIAL:
                dot_color = QColor(self._theme.get("memorial_orange", "#ff7824"))
            elif is_legal_hol:
                dot_color = QColor(self._theme.get("festival_red", "#d62728"))
            if dot_color is not None:
                painter.setBrush(dot_color)
                painter.setPen(QPen(Qt.PenStyle.NoPen))
                x = rect.right() - self.dot_size - 4
                y = rect.top() + 4
                painter.drawEllipse(x, y, self.dot_size, self.dot_size)

        except Exception:
            self._log_exception_once(
                "paintCell",
                f"paintCell单元格渲染异常 date={date.toString('yyyy-MM-dd')}",
            )
        finally:
            # 【修复】painter 若已被销毁（极端情况下 Qt 提前回收），
            # restore 会抛 RuntimeError 并掩盖原始异常，这里吞掉。
            try:
                painter.restore()
            except RuntimeError:
                pass
    def set_net_holiday(self, holiday_data: dict):
        try:
            self.net_holiday_data = holiday_data
            logger.info(f"加载网络节假日数据，共{len(holiday_data)}条")
            self._rebuild_cell_cache(self.yearShown(), self.monthShown())
            self.update()
        except Exception as e:
            log_exception(f"set_net_holiday 加载节假日数据失败: {e}")