# coding: utf-8
"""
主窗口：UI 容器 + 跨模块调度。

瘦身后的职责：
  - 窗口基础属性（无边框、透明、字体、DWM 修复）
  - UI 构建（顶栏、日历、info_label、阴影）
  - Qt 事件重写（paint / mouse / close / contextMenu）
  - 事件总线回调（薄委托：一行转发给管理器或控制器）
  - i18n / 主题刷新入口
  - 退出清理

业务逻辑全部下沉到 manager / controller。判断标准：本类方法
超过 ~15 行通常就说明有东西该抽出去。
"""
from PyQt6.QtCore import Qt, QTimer, QDate
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QPushButton, QMenu, QLabel,
    QGraphicsDropShadowEffect,
)

import lunar as lunar_mod
from i18n import (
    set_language, tr, on_language_changed, off_language_changed,
)
from config import config, get_logger, get_resource_path
from utils import init_config_defaults
from calendar_widget import ClickLabel, LunarCalendarWidget
from dialogs import MonthYearPickerDialog
from sound_manager import SoundManager
from window_state_manager import WindowStateManager
from holiday_manager import HolidayManager
from memorial_data_manager import MemorialDataManager
from tray_manager import TrayManager
from style_manager import StyleManager
from reminder_manager import ReminderManager
from lunar import get_lunar_by_datetime

from app import dwm
from app import info_panel
from app import event_wiring
from app import settings_controller
from app.dependency_check import check_dependencies

logger = get_logger()


class DragCalendarWidget(QWidget):
    """主窗口：UI 容器 + 跨模块调度。"""

    def __init__(self):
        super().__init__()
        init_config_defaults(config)
        set_language(config.get("language", "zh_CN"))

        # 基础管理器
        self.style_mgr = StyleManager(config)
        self.sound_mgr = SoundManager(self, get_resource_path)
        self.window_state = WindowStateManager(self, config)
        self.holiday_mgr = HolidayManager(config)
        self.memorial_mgr = MemorialDataManager(self, config)
        self.reminder_mgr = ReminderManager(self, config, self.sound_mgr)
        self.tray_mgr = TrayManager(self, config, get_resource_path)

        self.style_mgr.theme_reloaded.connect(self._on_theme_reloaded)

        self._setup_window()
        self.build_ui()
        self.style_mgr.refresh_all(self)
        event_wiring.connect(self)

        # 语言切换后主窗口与托盘菜单同步刷新。
        # 注册时机放在 build_ui / event_wiring 之后：__init__ 开头的
        # set_language 只是读配置定初值，不应在控件尚未就绪时广播
        # 到本实例；而此刻控件已全部建好，后续任何 set_language 都能
        # 安全触发 retranslate_ui。
        on_language_changed(self._on_language_changed)

        # 初始化数据
        self.setWindowTitle(tr("app.title"))
        self.cal.set_net_holiday(self.holiday_mgr.apply_cached())
        self.cal.set_memorial_list(config.get("memorial_days", []))
        # 启动即检查当天命中：若启动时刻已过 remind_start_hour，
        # _calc_next_timestamp 会把候选推到下一周期，导致当天漏提醒。
        # 重复触发由 last_remind_date 守卫去重。
        self.reminder_mgr.reschedule(check_today=True)

        check_dependencies(
            self,
            has_cnlunar=lunar_mod.HAS_CHNCAL,
            has_chinese_cal=lunar_mod.HAS_CHINESE_CAL,
        )
        self.holiday_mgr.fetch_current_year()
        self.update_calendar_title()
        self.on_calendar_select_changed()
        # 异步预热农历年索引：首次构建约 400+ 天扫描，放在事件循环
        # 下一轮做，避免窗口首次显示时卡顿。失败静默（正式路径有降级）。
        QTimer.singleShot(0, self._warmup_lunar_cache)

    # ===== 启动预热 =====
    def _warmup_lunar_cache(self):
        try:
            if not lunar_mod.HAS_CHNCAL:
                return
            today = QDate.currentDate()
            # 农历年与公历年大致重合，预取当年与次年即可覆盖绝大多数
            # 用户翻页 / 纪念日计算的范围。
            lunar_mod.warmup_lunar_index(
                [today.year(), today.year() + 1])
        except Exception:
            logger.debug("农历索引预热失败", exc_info=True)

    # ===== 窗口基础属性 =====
    def _setup_window(self):
        """窗口基础属性设置（修复黑边核心逻辑）。"""
        th = self.style_mgr.current_theme
        self.setFixedSize(th["window_width"], th["window_height"])
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowSystemMenuHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setObjectName("MainWindow")
        self.setStyleSheet("#MainWindow { background: transparent; }")

        dwm.apply_dwm_fix(self)
        self.setFont(self.style_mgr.get_global_font())

    # ===== UI 构建 =====
    def build_ui(self):
        th = self.style_mgr.current_theme
        layout_main = QVBoxLayout(self)

        shadow_size = th["shadow_size"]
        margin = shadow_size if shadow_size > 0 else 1
        layout_main.setContentsMargins(margin, margin, margin, margin)
        layout_main.setSpacing(0)

        self.content_widget = QWidget()
        self.content_widget.setObjectName("content_widget")
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(8)

        self.stack = QStackedWidget()
        self.calendar_container = QWidget()
        cal_vl = QVBoxLayout(self.calendar_container)
        cal_vl.setContentsMargins(0, 0, 0, 0)
        cal_vl.setSpacing(8)

        top_bar = QWidget()
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(4, 4, 4, 4)
        self.btn_prev = QPushButton("<")
        self.btn_prev.setFixedWidth(36)
        self.btn_prev.clicked.connect(self.prev_month)
        self.cal_title = ClickLabel("")
        self.cal_title.setObjectName("cal_title")
        self.cal_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cal_title.clicked.connect(self.open_month_picker)
        self.btn_next = QPushButton(">")
        self.btn_next.setFixedWidth(36)
        self.btn_next.clicked.connect(self.next_month)
        top_layout.addWidget(self.btn_prev)
        top_layout.addWidget(self.cal_title, stretch=1)
        top_layout.addWidget(self.btn_next)
        cal_vl.addWidget(top_bar)

        self.calendar = LunarCalendarWidget(
            self, th, config.get("memorial_days", []))
        self.cal = self.calendar
        self.cal.selectionChanged.connect(self.on_calendar_select_changed)
        self.cal.setGridVisible(False)
        self.cal.setNavigationBarVisible(False)
        self.cal.setVerticalHeaderFormat(
            self.cal.VerticalHeaderFormat.NoVerticalHeader)
        cal_vl.addWidget(self.cal)

        self.info_label = QLabel()
        self.info_label.setObjectName("info_label")
        self.info_label.setFixedHeight(40)
        self.info_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.info_label.setWordWrap(True)
        cal_vl.addWidget(self.info_label)

        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(10)
        self.btn_today = QPushButton(tr("btn.today"))
        self.btn_today.clicked.connect(self.goto_today)
        row2_layout.addStretch(1)
        row2_layout.addWidget(self.btn_today)
        cal_vl.addLayout(row2_layout)

        self.stack.addWidget(self.calendar_container)
        content_layout.addWidget(self.stack)
        layout_main.addWidget(self.content_widget)

        if shadow_size > 0:
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(shadow_size)
            shadow.setColor(QColor(th["shadow_color"]))
            shadow.setOffset(0, 0)
            self.content_widget.setGraphicsEffect(shadow)
        else:
            self.content_widget.setGraphicsEffect(None)

    def paintEvent(self, event):
        # WA_TranslucentBackground 已处理透明背景，无需额外 fillRect
        super().paintEvent(event)

    # ===== 事件总线回调（薄委托） =====
    def _on_window_show(self, _data=None):
        self.show_normal()

    def _on_window_quit(self, _data=None):
        self.quit_app()

    def _on_open_settings(self, _data=None):
        settings_controller.open_settings_dialog(self)

    def _on_backup_memorial(self, _data=None):
        self.memorial_mgr.backup()

    def _on_restore_memorial(self, _data=None):
        self.memorial_mgr.restore()

    def _on_holiday_updated(self, data=None):
        if not isinstance(data, dict) or "data" not in data:
            logger.warning("HOLIDAY_UPDATED 收到非法 payload: %r", data)
            return
        self.cal.set_net_holiday(data["data"])

    def _on_memorial_changed(self, data: dict = None):
        self.cal.set_memorial_list(config.get("memorial_days", []))
        # payload 里带 check_today=True 表示"用户显式动作"（如恢复数据），
        # 需要立即检查今日命中；普通刷新走静默重排。
        check_today = (isinstance(data, dict)
                       and bool(data.get("check_today", False)))
        self.reminder_mgr.reschedule(force=True, check_today=check_today)

    def _on_tray_topmost(self, data=None):
        if not isinstance(data, dict) or "enable" not in data:
            logger.warning("WINDOW_TOGGLE_TOPMOST 收到非法 payload: %r", data)
            return
        enable = bool(data["enable"])
        self.window_state.set_topmost(enable)
        config.set("topmost", enable, save=True)
        self.tray_mgr.update_topmost_check(enable)

    # ===== Qt 事件重写 =====
    def mousePressEvent(self, event):
        self.window_state.mouse_press_event(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.window_state.mouse_move_event(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.window_state.mouse_release_event(event)
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):
        if not self.tray_mgr.available:
            self.quit_app()
            event.accept()
            return
        self.window_state.close_event(event)

    def contextMenuEvent(self, event):
        # 每次显示都新建 QMenu / QAction，所以 tr() 调用天然跟随当前
        # 语言，无需额外 retranslate。
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu{background-color:#f7f3ed;border:1px solid #d8d2c5;border-radius:12px;padding:6px;}
            QMenu::item{padding:6px 20px;background:transparent;border-radius:8px;color:#444;}
            QMenu::item:selected{background:#d9e2d6;}
        """)
        act_min    = menu.addAction(tr("ctxmenu.minimize"))
        act_backup = menu.addAction(tr("ctxmenu.backup"))
        act_restore= menu.addAction(tr("ctxmenu.restore"))
        act_set    = menu.addAction(tr("ctxmenu.settings"))
        act_exit   = menu.addAction(tr("ctxmenu.quit"))
        action = menu.exec(event.globalPos())

        if action == act_min:
            # 无托盘时 hide() 会导致窗口失联，改为最小化
            if self.tray_mgr.available:
                self.hide()
            else:
                self.showMinimized()
        elif action == act_backup:
            self.memorial_mgr.backup()
        elif action == act_restore:
            self.memorial_mgr.restore()
        elif action == act_set:
            settings_controller.open_settings_dialog(self)
        elif action == act_exit:
            self.quit_app()

    # ===== 月份导航 =====
    def goto_today(self):
        t = QDate.currentDate()
        self.cal.setSelectedDate(t)
        self.cal.showSelectedDate()
        self.update_calendar_title()

    def prev_month(self):
        self.cal.showPreviousMonth()
        self.update_calendar_title()

    def next_month(self):
        self.cal.showNextMonth()
        self.update_calendar_title()

    def open_month_picker(self):
        """点击日历标题 → 弹出年/月选择器，跳转到目标月。"""
        dlg = MonthYearPickerDialog(
            self.cal.yearShown(), self.cal.monthShown(), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        year, month = dlg.get_year_month()
        # setCurrentPage 触发 currentPageChanged → 自动重建缓存
        self.cal.setCurrentPage(year, month)
        self.update_calendar_title()

    def update_calendar_title(self):
        self.cal_title.setText(tr("cal.title_format").format(
            year=self.cal.yearShown(),
            month=self.cal.monthShown(),
        ))

    # ===== 选中日详情 =====
    def on_calendar_select_changed(self):
        sel_date = self.cal.selectedDate()
        memorial_names = self.cal.get_memorials_for_date(sel_date)
        lunar = get_lunar_by_datetime(
            (sel_date.year(), sel_date.month(), sel_date.day()))

        parts = info_panel.build_info_parts(
            sel_date=sel_date,
            memorial_names=memorial_names,
            lunar_obj=lunar,
            has_cnlunar=lunar_mod.HAS_CHNCAL,
        )
        html_text = info_panel.render_html(parts)
        if html_text is None:
            self.info_label.setTextFormat(Qt.TextFormat.PlainText)
            self.info_label.setText(tr(info_panel.placeholder_key(parts)))
            return
        self.info_label.setTextFormat(Qt.TextFormat.RichText)
        self.info_label.setText(html_text)

    # ===== 主题 / 语言 =====
    def _on_theme_reloaded(self, theme: dict):
        """主题热更新：只刷 QSS + 重绘，不重建 UI（避免闪烁和状态丢失）。"""
        try:
            self.setFont(self.style_mgr.get_global_font())
            self.style_mgr.refresh_all(self)
            logger.info("主题已应用")
        except Exception:
            logger.exception("主题热更新失败")

    def _on_language_changed(self, _lang: str):
        """
        i18n 语言切换回调。

        异常在此拦截并记录：i18n.set_language 已经对监听者做了隔离，
        但显式捕获 + 日志能让"某次刷新失败"在日志里留下明确足迹，
        而不是被 i18n 的通用 exception 掩盖。
        """
        try:
            self.retranslate_ui()
        except Exception:
            logger.exception("语言切换后刷新主窗口 UI 失败")

    def retranslate_ui(self):
        """
        刷新所有依赖 tr() 的静态文本。

        只 setText / setTitle：不影响当前月份、选中日期、滚动位置、
        控件输入值等状态，也不触发任何业务重排（除了 on_calendar_
        select_changed 会按新语言重建 info_label 的 HTML）。
        """
        self.setWindowTitle(tr("app.title"))
        self.btn_today.setText(tr("btn.today"))
        self.update_calendar_title()
        # info_label 的 HTML 由 tr 拼接，需要按新语言重建
        self.on_calendar_select_changed()

        # 托盘菜单：tray_manager.py 未同步更新时静默跳过（getattr 防御），
        # 保证即使侧向文件尚未跟进，主窗口自身的语言切换也不受影响。
        tray_retranslate = getattr(self.tray_mgr, "retranslate_ui", None)
        if callable(tray_retranslate):
            tray_retranslate()

    # ===== 其他 =====
    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ===== 退出 =====
    def quit_app(self):
        try:
            event_wiring.disconnect(self)
        except Exception as e:
            logger.warning(f"解除事件订阅失败: %r {e}")
        # 注销 i18n 监听：quit_app 后本实例不应再被语言切换回调触发。
        # 若进程就此退出，这是可选清理；但在测试/多实例场景下是必须的
        # ——否则已销毁的窗口会被 i18n._listeners 强引用住。
        try:
            off_language_changed(self._on_language_changed)
        except Exception as e:
            logger.warning(f"解除语言切换监听失败: {e}")
        self.window_state.save_position()
        try:
            self.holiday_mgr.shutdown()
        except Exception as e:
            logger.warning(f"关闭节假日线程失败: {e}")
        # 强制同步落盘：避免防抖定时器未触发就退出导致配置丢失/半写
        try:
            config.flush()
        except Exception as e:
            logger.warning(f"刷写配置失败: {e}")
        QTimer.singleShot(0, QApplication.quit)