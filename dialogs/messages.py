# coding: utf-8
"""
通用消息弹窗。

设计约束：本模块不依赖 i18n / config / 任何业务模块。
标题与正文由调用方通过 tr() 计算好后传入，本模块只负责
样式统一与图标区分，从而可被任意层安全 import。
"""
from PyQt6.QtWidgets import QMessageBox

__all__ = ["msg_info", "msg_warn", "msg_error"]


class _BaseMsgBox(QMessageBox):
    """消息弹窗基类：复用样式，仅按钮颜色区分。"""
    _BASE_STYLE = """
    QMessageBox{background-color:#f8f6f2;border-radius:12px;}
    QMessageBox QLabel{color:#333333;background:transparent;font-size:13px;}
    QMessageBox QPushButton{
        min-width:75px;padding:6px 12px;border:none;border-radius:8px;
        color:#ffffff;font-size:12px;
    }
    """

    def __init__(self, parent, title, text, icon, btn_color: str, btn_hover: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setText(text)
        self.setIcon(icon)
        self.setStyleSheet(self._BASE_STYLE + f"""
        QMessageBox QPushButton{{background:{btn_color};}}
        QMessageBox QPushButton:hover{{background:{btn_hover};}}
        """)


def msg_info(parent, title, text):
    box = _BaseMsgBox(parent, title, text, QMessageBox.Icon.Information,
                      "#a7b8a1", "#8fa089")
    box.exec()


def msg_warn(parent, title, text):
    box = _BaseMsgBox(parent, title, text, QMessageBox.Icon.Warning,
                      "#d4a76a", "#c99856")
    box.exec()


def msg_error(parent, title, text):
    box = _BaseMsgBox(parent, title, text, QMessageBox.Icon.Critical,
                      "#c87878", "#b45c5c")
    box.exec()