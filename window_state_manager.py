# coding: utf-8
from PyQt6.QtCore import Qt, QPoint, QEvent
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QWidget, QApplication
from config import ConfigManager


class WindowStateManager:
    """窗口状态管理：拖拽、置顶、透明度、位置记忆、边界限制"""
    def __init__(self, window: QWidget, config: ConfigManager):
        self.window = window
        self.config = config
        self._drag_pos = QPoint()
        self._is_dragging = False

        opacity = config.get("opacity", 0.92)
        self.window.setWindowOpacity(opacity)

        if config.get("topmost", False):
            self.set_topmost(True)

        px = config.get("pos_x")
        py = config.get("pos_y")
        if px is not None and py is not None:
            self.window.move(px, py)

    def set_opacity(self, value: float):
        self.window.setWindowOpacity(value)

    def set_topmost(self, enable: bool):
        flags = self.window.windowFlags()
        was_visible = self.window.isVisible()
        if enable:
            self.window.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.window.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
        if was_visible:
            self.window.show()

    def toggle_topmost(self):
        current = self.config.get("topmost", False)
        self.set_topmost(not current)
        self.config.set("topmost", not current, save=False)

    def mouse_press_event(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()
            self._is_dragging = True
            event.accept()

    def mouse_move_event(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self._is_dragging:
            new_pos = event.globalPosition().toPoint() - self._drag_pos
            # 【Bug 7】原实现固定用主屏几何做边界钳制，副屏在主屏右侧时
            # 窗口会被"吸回"主屏。这里按候选位置所在屏幕取几何；
            # 若光标不在任何屏幕（极端多屏间隙），退回主屏。
            screen = QApplication.screenAt(new_pos) or QApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                new_pos.setX(max(geo.left() + 100 - self.window.width(),
                                 min(new_pos.x(), geo.right() - 100)))
                new_pos.setY(max(geo.top() + 100 - self.window.height(),
                                 min(new_pos.y(), geo.bottom() - 100)))
            self.window.move(new_pos)
            event.accept()

    def mouse_release_event(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            geo = self.window.frameGeometry()
            self.config.set("pos_x", geo.left(), save=False)
            self.config.set("pos_y", geo.top(), save=False)
            self.config.save_debounced()

    def close_event(self, event):
        """关闭窗口最小化到托盘，无托盘则退出"""
        event.ignore()
        self.window.hide()
        return False

    def save_position(self):
        """手动保存当前位置"""
        geo = self.window.frameGeometry()
        self.config.set("pos_x", geo.left(), save=False)
        self.config.set("pos_y", geo.top(), save=False)