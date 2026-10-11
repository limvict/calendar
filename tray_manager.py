# coding: utf-8
import os
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QStyle, QApplication
from config import ConfigManager, get_logger
from event_bus import event_bus, EventType
from i18n import tr

logger = get_logger()


class TrayManager(QObject):
    """系统托盘管理：图标、菜单、交互事件。"""

    def __init__(self, parent, config: ConfigManager, get_resource_path):
        super().__init__(parent)
        self.parent = parent
        self.config = config
        self._get_resource = get_resource_path
        self.tray_icon = None
        self.act_topmost = None
        # 需要重翻菜单文本的 QAction 引用。
        # 之前是局部变量，语言切换时拿不到；提升为实例属性后
        # retranslate_ui 才能覆盖全部菜单项。
        # 托盘不可用时这些字段保持 None，retranslate_ui 会整体短路。
        self._act_show = None
        self._act_backup = None
        self._act_restore = None
        self._act_settings = None
        self._act_quit = None
        self._init_tray()

    def _init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray_icon = QSystemTrayIcon(self.parent)
        icon_path = self._get_resource("assets/app.ico")
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
        else:
            icon = QApplication.style().standardIcon(
                QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray_icon.setIcon(icon)

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu{background-color:#f7f3ed;border:1px solid #d8d2c5;border-radius:12px;padding:6px;}
            QMenu::item{padding:6px 20px;background:transparent;border-radius:8px;color:#444;}
            QMenu::item:selected{background:#d9e2d6;}
        """)

        # 具名方法而非 lambda：便于断点调试，与 main.py 的订阅风格一致，
        # 未来若搬到 event_bus.subscribe 时 unsubscribe 才不会失效。
        self._act_show = QAction(tr("tray.show"), self)
        self._act_show.triggered.connect(self._on_show)

        self.act_topmost = QAction(tr("tray.topmost"), self)
        self.act_topmost.setCheckable(True)
        self.act_topmost.setChecked(self.config.get("topmost", False))
        self.act_topmost.triggered.connect(self._on_toggle_topmost)

        self._act_backup = QAction(tr("tray.backup"), self)
        self._act_backup.triggered.connect(self._on_backup)

        self._act_restore = QAction(tr("tray.restore"), self)
        self._act_restore.triggered.connect(self._on_restore)

        self._act_settings = QAction(tr("tray.settings"), self)
        self._act_settings.triggered.connect(self._on_open_settings)

        self._act_quit = QAction(tr("tray.quit"), self)
        self._act_quit.triggered.connect(self._on_quit)

        menu.addAction(self._act_show)
        menu.addAction(self.act_topmost)
        menu.addSeparator()
        menu.addAction(self._act_backup)
        menu.addAction(self._act_restore)
        menu.addSeparator()
        menu.addAction(self._act_settings)
        menu.addAction(self._act_quit)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_activated)
        self.tray_icon.show()

    def _on_show(self):
        event_bus.publish(EventType.WINDOW_SHOW)

    def _on_toggle_topmost(self, enable: bool):
        event_bus.publish(EventType.WINDOW_TOGGLE_TOPMOST, enable=enable)

    def _on_backup(self):
        event_bus.publish(EventType.BACKUP_MEMORIAL)

    def _on_restore(self):
        event_bus.publish(EventType.RESTORE_MEMORIAL)

    def _on_open_settings(self):
        event_bus.publish(EventType.OPEN_SETTINGS)

    def _on_quit(self):
        event_bus.publish(EventType.WINDOW_QUIT)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            event_bus.publish(EventType.WINDOW_SHOW)

    def update_topmost_check(self, checked: bool):
        if self.act_topmost:
            self.act_topmost.setChecked(checked)

    def retranslate_ui(self):
        """
        语言切换后刷新菜单项文本。

        托盘不可用时（_init_tray 提前 return）所有 _act_* 为 None，
        整体短路返回，不需要逐项判空。
        """
        if self._act_show is None:
            return
        self._act_show.setText(tr("tray.show"))
        if self.act_topmost:
            self.act_topmost.setText(tr("tray.topmost"))
        if self._act_backup:
            self._act_backup.setText(tr("tray.backup"))
        if self._act_restore:
            self._act_restore.setText(tr("tray.restore"))
        if self._act_settings:
            self._act_settings.setText(tr("tray.settings"))
        if self._act_quit:
            self._act_quit.setText(tr("tray.quit"))

    def hide(self):
        if self.tray_icon:
            self.tray_icon.hide()

    @property
    def available(self) -> bool:
        # 若系统在运行期禁用了托盘（Linux 下可由用户/桌面环境动态改），
        # isVisible() 会翻 False，此时主窗口 closeEvent 应走"真正退出"
        # 分支而不是最小化到托盘 —— 否则窗口会失联。
        return self.tray_icon is not None and self.tray_icon.isVisible()