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
        value = max(0.0, min(1.0, float(value)))
        self.window.setWindowOpacity(value)


    def set_topmost(self, enable: bool):
        was_visible = self.window.isVisible()
        geo = self.window.saveGeometry() if was_visible else None
        self.window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enable)
        if was_visible:
            self.window.show()
            if geo is not None:
                self.window.restoreGeometry(geo)

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
            screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
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
            event.accept()

    def close_event(self, event):
        """
        关闭窗口 → 最小化到托盘。
        无托盘场景由 main.py 的 closeEvent 分支负责调用 quit_app。
        注意：Qt 的 closeEvent 不使用返回值，这里的语义完全靠
        event.ignore() 表达。
        """
        event.ignore()
        self.window.hide()

    def save_position(self):
        geo = self.window.frameGeometry()
        self.config.set("pos_x", geo.left(), save=False)
        self.config.set("pos_y", geo.top(), save=False)
        self.config.flush()