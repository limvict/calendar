# coding: utf-8
import os
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QStyle, QApplication
from config import ConfigManager
from event_bus import event_bus, EventType


class TrayManager(QObject):
    """系统托盘管理：图标、菜单、交互事件"""
    def __init__(self, parent, config: ConfigManager, get_resource_path):
        super().__init__(parent)
        self.parent = parent
        self.config = config
        self._get_resource = get_resource_path
        self.tray_icon = None
        self.act_topmost = None
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
                QStyle.StandardPixmap.SP_ComputerIcon
            )
        self.tray_icon.setIcon(icon)

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu{background-color:#f7f3ed;border:1px solid #d8d2c5;border-radius:12px;padding:6px;}
            QMenu::item{padding:6px 20px;background:transparent;border-radius:8px;color:#444;}
            QMenu::item:selected{background:#d9e2d6;}
        """)

        # 【P1-4】具名方法替代 lambda：
        # 1) 调试可在 _on_show 等处下断点；
        # 2) 与 main.py 的"具名方法订阅"风格一致；
        # 3) 若未来把这种模式搬到 event_bus.subscribe，unsubscribe 才不会失效。
        act_show = QAction("恢复窗口", self)
        act_show.triggered.connect(self._on_show)

        self.act_topmost = QAction("窗口置顶", self)
        self.act_topmost.setCheckable(True)
        self.act_topmost.setChecked(self.config.get("topmost", False))
        self.act_topmost.triggered.connect(self._on_toggle_topmost)

        act_backup = QAction("备份纪念日数据", self)
        act_backup.triggered.connect(self._on_backup)

        act_restore = QAction("恢复纪念日数据", self)
        act_restore.triggered.connect(self._on_restore)

        act_settings = QAction("设置", self)
        act_settings.triggered.connect(self._on_open_settings)

        act_quit = QAction("完全退出", self)
        act_quit.triggered.connect(self._on_quit)

        menu.addAction(act_show)
        menu.addAction(self.act_topmost)
        menu.addSeparator()
        menu.addAction(act_backup)
        menu.addAction(act_restore)
        menu.addSeparator()
        menu.addAction(act_settings)
        menu.addAction(act_quit)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_activated)
        self.tray_icon.show()

    # ===== 【P1-4】具名槽函数（注意：必须缩进到类内） =====
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

    def hide(self):
        if self.tray_icon:
            self.tray_icon.hide()

    @property
    def available(self) -> bool:
        return self.tray_icon is not None