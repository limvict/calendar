# coding: utf-8
"""
程序入口。

所有业务逻辑位于 app 包内，本文件只做 QApplication 装配。
"""
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from config import get_resource_path
from app.main_window import DragCalendarWidget


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(get_resource_path("assets/app.ico")))
    w = DragCalendarWidget()
    w.show()
    sys.exit(app.exec())