# coding: utf-8
from PyQt6.QtGui import QFont
from config import ConfigManager
from constants import DEFAULT_THEME, load_theme


class StyleManager:
    """UI样式统一管理：主题加载、全控件样式刷新"""
    def __init__(self, config: ConfigManager):
        self.config = config
        self.theme = load_theme()
        if self.theme is None:
            self.theme = DEFAULT_THEME.copy()

    def refresh_all(self, window):
        """刷新主窗口所有控件样式"""
        th = self.theme
        window.content_widget.setStyleSheet(f"""
        QWidget#content_widget {{
            background-color:{th['bg_main']};
            border-radius:{th['corner_radius']}px;
        }}
        """)
        window.cal.setStyleSheet(f"""
        QCalendarWidget {{ background-color:{th["bg_main"]}; font-family:"{th["font_family"]}"; }}
        QCalendarWidget QTableView {{
            background-color:{th["bg_main"]};
            selection-background-color:transparent;
            selection-color:transparent;
            gridline-color:transparent;
        }}
        QCalendarWidget QTableView QHeaderView::section {{
            background-color:{th["calendar_header_bg"]};
            color:{th["calendar_header_text"]};
            border:none;
            padding:5px 0px;
            font-size:{th['week_header_font_size']}px;
        }}
        """)
        # 按钮样式走主题，缺省回退到莫兰迪绿
        btn_bg = th.get("btn_bg", "#b4c3b0")
        btn_hover = th.get("btn_hover", "#98aa93")
        btn_pressed = th.get("btn_pressed", "#82947d")
        btn_text = th.get("btn_text", "#ffffff")
        btn_style = f"""
        QPushButton{{
            background:{btn_bg};color:{btn_text};border:none;border-radius:10px;
            padding:6px;font-size:13px;
        }}
        QPushButton:hover{{background:{btn_hover};}}
        QPushButton:pressed{{background:{btn_pressed};}}
        """
        window.btn_prev.setStyleSheet(btn_style)
        window.btn_next.setStyleSheet(btn_style)
        window.btn_today.setStyleSheet(btn_style)

        # 更新日历控件主题
        window.cal.update_theme(th)
        window.cal.update()

    def get_global_font(self) -> QFont:
        """获取全局字体"""
        th = self.theme
        font_family = th["font_family"].split(",")[0].strip()
        font = QFont()
        font.setFamily(font_family)
        font.setPointSize(th["font_size"])
        return font

    @property
    def current_theme(self) -> dict:
        return self.theme