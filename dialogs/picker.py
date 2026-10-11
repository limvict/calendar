# coding: utf-8
"""
年 / 月快速跳转对话框。

由 main.py 的 cal_title.clicked 触发；仅依赖 base 与 i18n，
无业务模块耦合，可独立测试。
"""
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel, QSpinBox,
)

from i18n import tr

from .base import (
    RetranslatableDialog,
    # 公开别名：新代码统一使用公开名，逐步淘汰带下划线的旧名。
    make_button_box,
    retranslate_button_box,
)

__all__ = ["MonthYearPickerDialog"]


# ===================== 年/月快速跳转 =====================
class MonthYearPickerDialog(RetranslatableDialog, QDialog):
    """
    年/月快速跳转对话框。由 main.py 的 cal_title.clicked 触发。
    年份范围以"今天"为中心 ±YEAR_SPAN，避免滑出 QSpinBox 可承载的交互范围。
    """
    YEAR_SPAN = 50

    def __init__(self, current_year: int, current_month: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("btn.pick_month"))
        self.setFixedSize(280, 170)
        self.setStyleSheet("""
        QDialog{background-color:#f7f3ed;border-radius:16px;}
        QLabel{font-size:13px;color:#333333;background:transparent;}
        QSpinBox{border:1px solid #d8d2c5;border-radius:6px;
                 background:#fff;font-size:13px;padding:3px;}
        QPushButton{
            min-width:72px;padding:6px 12px;
            background:#a7b8a1;color:#ffffff;border:none;
            border-radius:8px;font-size:12px;
        }
        QPushButton:hover{background:#8fa089;}
        """)

        today = QDate.currentDate()
        lo = today.year() - self.YEAR_SPAN
        hi = today.year() + self.YEAR_SPAN

        self.spin_year = QSpinBox()
        self.spin_year.setRange(lo, hi)
        # clamp：外部传入的 year 可能因测试/异常数据越界
        self.spin_year.setValue(max(lo, min(hi, int(current_year))))

        self.spin_month = QSpinBox()
        self.spin_month.setRange(1, 12)
        self.spin_month.setValue(max(1, min(12, int(current_month))))

        # 具名：retranslate_ui 需要 setText
        self.lbl_year = QLabel(tr("setting.year_label"))
        self.lbl_month = QLabel(tr("setting.month_label"))

        form = QGridLayout()
        form.setSpacing(10)
        form.addWidget(self.lbl_year, 0, 0)
        form.addWidget(self.spin_year, 0, 1)
        form.addWidget(self.lbl_month, 1, 0)
        form.addWidget(self.spin_month, 1, 1)

        self._btn_box = make_button_box(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self._btn_box)

        # 焦点给年份，Tab → 月份 → 确认，符合"先大后小"直觉
        self.spin_year.setFocus()
        self.spin_year.selectAll()

        self.retranslate_ui()

    def retranslate_ui(self):
        """刷新标题、标签、按钮文本。不动 spin 数值。"""
        self.setWindowTitle(tr("btn.pick_month"))
        self.lbl_year.setText(tr("setting.year_label"))
        self.lbl_month.setText(tr("setting.month_label"))
        retranslate_button_box(self._btn_box)

    def get_year_month(self) -> tuple:
        return self.spin_year.value(), self.spin_month.value()