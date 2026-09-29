# coding: utf-8
import os
import sys
import ctypes  # 用于Windows DWM系统级修复
import datetime
from PyQt6.QtCore import Qt, QTimer, QDate, pyqtSlot
from PyQt6.QtGui import QFont, QIcon, QColor, QPainter
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QMenu, QMessageBox, QDialog, QLabel, QGraphicsDropShadowEffect,
)

# Windows 注册表（开机自启）；非 Windows 平台降级
try:
    import winreg
    HAS_WINREG = True
except ImportError:
    winreg = None
    HAS_WINREG = False

from config import config, get_resource_path, get_logger
from utils import (
    HAS_CHNCAL, HAS_CHINESE_CAL, init_config_defaults, match_memorial_date,
    get_lunar_by_datetime,          # 【P1-3】新增
)
from calendar_widget import ClickLabel, LunarCalendarWidget
from dialogs import msg_warn, SettingDialog
from sound_manager import SoundManager
from window_state_manager import WindowStateManager
from holiday_manager import HolidayManager
from memorial_data_manager import MemorialDataManager
from tray_manager import TrayManager
from style_manager import StyleManager
from reminder_manager import ReminderManager
from event_bus import event_bus, EventType


class DragCalendarWidget(QWidget):
    """主窗口：UI容器 + 跨模块调度"""
    def __init__(self):
        super().__init__()
        init_config_defaults(config)
        # 基础管理器
        self.style_mgr = StyleManager(config)
        self.sound_mgr = SoundManager(self, get_resource_path)
        self.window_state = WindowStateManager(self, config)
        self.holiday_mgr = HolidayManager(config)
        self.memorial_mgr = MemorialDataManager(self, config)
        self.reminder_mgr = ReminderManager(self, config, self.sound_mgr)
        self.tray_mgr = TrayManager(self, config, get_resource_path)

        self._setup_window()
        self.build_ui()
        self.style_mgr.refresh_all(self)
        self._connect_signals()

        # 初始化数据
        self.cal.set_net_holiday(self.holiday_mgr.apply_cached())
        self.cal.set_memorial_list(config.get("memorial_days", []))
        self.reminder_mgr.reschedule()

        self._check_dependencies()
        self.holiday_mgr.fetch_current_year()
        self.update_calendar_title()
        self.on_calendar_select_changed()

    def _setup_window(self):
        """窗口基础属性设置（修复黑边核心逻辑）"""
        th = self.style_mgr.current_theme
        self.setFixedSize(th["window_width"], th["window_height"])
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowSystemMenuHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setObjectName("MainWindow")
        self.setStyleSheet("#MainWindow { background: transparent; }")

        if sys.platform == "win32":
            self._fix_windows_dwm()
        self.setFont(self.style_mgr.get_global_font())

    def _fix_windows_dwm(self):
        try:
            dwmapi = ctypes.windll.dwmapi
            class MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth", ctypes.c_int),
                    ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int)
                ]
            margins = MARGINS(-1, -1, -1, -1)
            hwnd = int(self.winId())
            dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        except Exception:
            pass

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
        self.cal_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cal_title.setStyleSheet(
            "font-size:15px;font-weight:500;cursor:pointer;background:transparent;color:#444;"
        )
        self.btn_next = QPushButton(">")
        self.btn_next.setFixedWidth(36)
        self.btn_next.clicked.connect(self.next_month)
        top_layout.addWidget(self.btn_prev)
        top_layout.addWidget(self.cal_title, stretch=1)
        top_layout.addWidget(self.btn_next)
        cal_vl.addWidget(top_bar)

        self.calendar = LunarCalendarWidget(self, th, config.get("memorial_days", []))
        self.cal = self.calendar
        self.cal.selectionChanged.connect(self.on_calendar_select_changed)
        self.cal.setGridVisible(False)
        self.cal.setNavigationBarVisible(False)
        self.cal.setVerticalHeaderFormat(self.cal.VerticalHeaderFormat.NoVerticalHeader)
        cal_vl.addWidget(self.cal)

        self.info_label = QLabel()
        self.info_label.setFixedHeight(40)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("""
        QLabel{color:#444444;font-size:12px;padding:4px;}
        """)
        cal_vl.addWidget(self.info_label)

        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(10)
        self.btn_today = QPushButton("今天")
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

    # 【Bug 12】原 paintEvent 里 fillRect(transparent) 是 no-op，
    # WA_TranslucentBackground 已处理透明背景，这里只保留父类调用。
    def paintEvent(self, event):
        super().paintEvent(event)

    def _connect_signals(self):
        """
        【Bug 18】全部改为具名方法订阅。
        原来用 lambda 订阅，退出时无法 unsubscribe，会持续持有 self 引用；
        配合 Bug 2（unsubscribe 失效），长期运行后会隐性泄漏。
        """
        event_bus.subscribe(EventType.HOLIDAY_UPDATED, self._on_holiday_updated)
        event_bus.subscribe(EventType.MEMORIAL_CHANGED, self._on_memorial_changed)
        event_bus.subscribe(EventType.WINDOW_SHOW, self._on_window_show)
        event_bus.subscribe(EventType.WINDOW_QUIT, self._on_window_quit)
        event_bus.subscribe(EventType.WINDOW_TOGGLE_TOPMOST, self._on_tray_topmost)
        event_bus.subscribe(EventType.OPEN_SETTINGS, self._on_open_settings)
        event_bus.subscribe(EventType.BACKUP_MEMORIAL, self._on_backup_memorial)
        event_bus.subscribe(EventType.RESTORE_MEMORIAL, self._on_restore_memorial)

    def _disconnect_signals(self):
        """退出时主动解除事件订阅，避免闭包/引用悬挂到解释器退出"""
        event_bus.unsubscribe(EventType.HOLIDAY_UPDATED, self._on_holiday_updated)
        event_bus.unsubscribe(EventType.MEMORIAL_CHANGED, self._on_memorial_changed)
        event_bus.unsubscribe(EventType.WINDOW_SHOW, self._on_window_show)
        event_bus.unsubscribe(EventType.WINDOW_QUIT, self._on_window_quit)
        event_bus.unsubscribe(EventType.WINDOW_TOGGLE_TOPMOST, self._on_tray_topmost)
        event_bus.unsubscribe(EventType.OPEN_SETTINGS, self._on_open_settings)
        event_bus.unsubscribe(EventType.BACKUP_MEMORIAL, self._on_backup_memorial)
        event_bus.unsubscribe(EventType.RESTORE_MEMORIAL, self._on_restore_memorial)

    # ===== 事件总线回调：统一接收 dict，忽略参数 =====
    def _on_window_show(self, _data=None):
        self.show_normal()

    def _on_window_quit(self, _data=None):
        self.quit_app()

    def _on_open_settings(self, _data=None):
        self.open_settings_dialog()

    def _on_backup_memorial(self, _data=None):
        self.memorial_mgr.backup()

    def _on_restore_memorial(self, _data=None):
        self.memorial_mgr.restore()

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
        self.window_state.close_event(event)
        if not self.tray_mgr.available:
            self.quit_app()

    def contextMenuEvent(self, event):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu{background-color:#f7f3ed;border:1px solid #d8d2c5;border-radius:12px;padding:6px;}
            QMenu::item{padding:6px 20px;background:transparent;border-radius:8px;color:#444;}
            QMenu::item:selected{background:#d9e2d6;}
        """)
        act_min = menu.addAction("最小化")
        act_backup = menu.addAction("备份纪念日数据")
        act_restore = menu.addAction("恢复纪念日数据")
        act_set = menu.addAction("设置")
        act_exit = menu.addAction("完全退出")
        action = menu.exec(event.globalPos())

        if action == act_min:
            self.hide()
        elif action == act_backup:
            self.memorial_mgr.backup()
        elif action == act_restore:
            self.memorial_mgr.restore()
        elif action == act_set:
            self.open_settings_dialog()
        elif action == act_exit:
            self.quit_app()

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

    def update_calendar_title(self):
        self.cal_title.setText(f"{self.cal.yearShown()}年{self.cal.monthShown()}月")

    def open_settings_dialog(self):
        auto_start = self._check_auto_start()
        mem_remind = bool(config.get_nested("memorial_cfg", "enable_remind", default=True))
        mem_sound = bool(config.get_nested("memorial_cfg", "sound_enable", default=True))
        dlg = SettingDialog(
            config.raw, auto_start,
            config.get("topmost", False),
            config.get("opacity", 0.92),
            mem_remind, mem_sound, self,
        )
        dlg.preview_opacity_changed.connect(self.window_state.set_opacity)
        dlg.preview_topmost_changed.connect(self.window_state.set_topmost)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply_settings(dlg)
        else:
            self.window_state.set_opacity(config.get("opacity", 0.92))
            self.window_state.set_topmost(config.get("topmost", False))
            self.tray_mgr.update_topmost_check(bool(config.get("topmost", False)))

    def _apply_settings(self, dlg: SettingDialog):
        """应用设置变更"""
        config.set("topmost", dlg.get_topmost_status(), save=False)
        config.set("opacity", dlg.get_opacity(), save=False)
        config.set("memorial_days", dlg.get_memorial_list(), save=False)

        memorial_cfg = config.get("memorial_cfg", {})
        memorial_cfg["enable_remind"] = bool(dlg.get_mem_remind())
        memorial_cfg["sound_enable"] = bool(dlg.get_mem_sound())
        config.set("memorial_cfg", memorial_cfg, save=False)
        config.save_debounced()

        event_bus.publish(EventType.MEMORIAL_CHANGED)
        self.tray_mgr.update_topmost_check(dlg.get_topmost_status())

        want_auto = dlg.get_auto_start_status()
        if want_auto != self._check_auto_start():
            self._apply_auto_start(want_auto)
        event_bus.publish(EventType.SETTINGS_CHANGED)

    def _on_holiday_updated(self, data: dict):
        self.cal.set_net_holiday(data["data"])

    def _on_memorial_changed(self, _data: dict = None):
        self.cal.set_memorial_list(config.get("memorial_days", []))
        self.reminder_mgr.reschedule(force=True, check_today=False)

    def _on_tray_topmost(self, data: dict):
        enable = data["enable"]
        self.window_state.set_topmost(enable)
        config.set("topmost", enable, save=False)
        self.tray_mgr.update_topmost_check(enable)

    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _check_dependencies(self):
        warn_msgs = []
        if not HAS_CHNCAL:
            warn_msgs.append("cnlunar未安装，农历、节气功能不可用")
        if not HAS_CHINESE_CAL:
            warn_msgs.append("chinese_calendar未安装，本地节假日判断不可用")
        if warn_msgs:
            QTimer.singleShot(
                100,
                lambda: msg_warn(self, "依赖缺失",
                    "\n".join(warn_msgs) + "\npip install cnlunar chinese_calendar"
                )
            )

    def _check_auto_start(self) -> bool:
        if sys.platform != "win32" or not HAS_WINREG:
            return False
        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        reg_key = "DesktopLunarCalendarV3"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
                val, _ = winreg.QueryValueEx(key, reg_key)
                return bool(val)
        except FileNotFoundError:
            return False
        except Exception:
            return False

    def on_calendar_select_changed(self):
        if not HAS_CHNCAL:
            self.info_label.setText("cnlunar未安装，农历/节气不可用")
            return

        sel_date = self.cal.selectedDate()
        # 【P1-3】复用 lunar.py 的 LRU 缓存 + 内建降级，
        # 不再直接 cnlunar.Lunar(...)，避免每次选中重新构造对象。
        lunar = get_lunar_by_datetime(
            (sel_date.year(), sel_date.month(), sel_date.day())
        )
        # 【P0-2】原来任何异常都会把主窗口打崩，这里统一保护
        if lunar is None:
            self.info_label.setText("农历信息不可用")
            return

        try:
            month_cn = lunar.lunarMonthCn.replace("大", "").replace("小", "")
            lunar_str = (
                f"{lunar.lunarYearCn}【{lunar.chineseYearZodiac}】 "
                f"{month_cn}{lunar.lunarDayCn}"
            )

            solar_term = lunar.todaySolarTerms
            holiday_legal = lunar.get_legalHolidays()
            holiday_other = lunar.get_otherHolidays()
            term_text = solar_term if (solar_term and solar_term != "无") else None

            holiday_list = []
            for item in holiday_legal + holiday_other:
                if item and item != "无":
                    holiday_list.append(item)
            holiday_unique = list(dict.fromkeys(holiday_list))
        except Exception as e:
            # cnlunar 版本差异 / 属性缺失等，不应让用户看到崩溃
            logger.warning(f"解析农历详情失败: {e}")
            self.info_label.setText("农历信息不可用")
            return

        # 纪念日部分不依赖 lunar 对象，保持原样
        memorial_text = []
        for m in config.get("memorial_days", []):
            if not m.get("enabled", True):
                continue
            if match_memorial_date(m, sel_date):
                name = m.get("name", "")
                if name:
                    memorial_text.append(name)

        parts_html = [f"<span style='color:#5A5A5A'>{lunar_str}</span>"]
        if term_text:
            parts_html.append(f"<span style='color:#2E7D32'>节气：{term_text}</span>")
        if holiday_unique:
            parts_html.append(
                f"<span style='color:#C96068'>节日：{' '.join(holiday_unique)}</span>"
            )
        if memorial_text:
            parts_html.append(
                f"<span style='color:#D47026'>纪念日：{' '.join(memorial_text)}</span>"
            )

        self.info_label.setTextFormat(Qt.TextFormat.RichText)
        self.info_label.setText(" &nbsp;&nbsp;｜&nbsp;&nbsp; ".join(parts_html))

    def _apply_auto_start(self, enable: bool):
        if sys.platform != "win32" or not HAS_WINREG:
            QMessageBox.information(self, "提示", "开机自启仅支持Windows")
            return

        # 【Bug 5 修复】打包环境直接用 exe；源码环境显式拼接 python + script
        if getattr(sys, "_MEIPASS", None):
            cmd = f'"{sys.executable}"'
        else:
            script = os.path.abspath(sys.argv[0])
            cmd = f'"{sys.executable}" "{script}"'

        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        reg_key = "DesktopLunarCalendarV3"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_WRITE) as key:
                if enable:
                    winreg.SetValueEx(key, reg_key, 0, winreg.REG_SZ, cmd)
                    QMessageBox.information(self, "成功", "✅ 已开启开机自启")
                else:
                    try:
                        winreg.DeleteValue(key, reg_key)
                    except FileNotFoundError:
                        pass
                    QMessageBox.information(self, "成功", "✅ 已关闭开机自启")
        except PermissionError:
            QMessageBox.critical(self, "权限错误", "注册表权限不足，请尝试以管理员运行程序")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"设置开机自启失败：{str(e)}")

    def quit_app(self):
        # 【Bug 18】退出前解除所有事件订阅
        try:
            self._disconnect_signals()
        except Exception as e:
            logger.warning(f"解除事件订阅失败: {e}")
        self.window_state.save_position()
        try:
            self.holiday_mgr.shutdown()
        except Exception as e:
            logger.warning(f"关闭节假日线程失败: {e}")
        config._flush_save()
        QApplication.quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(get_resource_path("assets/app.ico")))
    w = DragCalendarWidget()
    w.show()
    sys.exit(app.exec())