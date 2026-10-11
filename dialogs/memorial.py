# coding: utf-8
"""
纪念日相关对话框：

- AddMemorialDialog     : 新增 / 编辑单个纪念日
- MemorialDialog        : 纪念日列表管理（增删改、批量启停）
- MemorialRemindDialog  : 提醒弹窗

依赖方向：本模块只依赖 base / messages / memorial / constants / i18n，
不反向依赖 _legacy 或 __init__，避免循环导入。
"""
import copy
import calendar
from datetime import date

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QCheckBox, QSpinBox,
    QListWidget, QListWidgetItem, QPushButton,
    QComboBox, QRadioButton, QButtonGroup,
)

from memorial import (
    REPEAT_YEAR, REPEAT_MONTH, REPEAT_WEEK,
    normalize_memorial, get_next_memorial_date,
)
from i18n import tr
from constants import REFERENCE_LEAP_YEAR
from config import get_logger

from .messages import msg_info, msg_warn
from .base import (
    RetranslatableDialog,
    make_button_box,
    retranslate_button_box,
)

logger = get_logger()

__all__ = [
    "AddMemorialDialog", "MemorialDialog", "MemorialRemindDialog",
]

# 无法计算下次发生日期的纪念日排到最后。
# 取值需远大于任何真实"距今天数"，避免与正常条目冲突。
_NO_NEXT_DATE_RANK = 10 ** 6


# ===================== 纪念日新增/编辑弹窗 =====================
class AddMemorialDialog(RetranslatableDialog, QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._saved_type_lunar = False
        self._saved_isleap = False
        self._last_repeat_type = None
        self.setWindowTitle(tr("memorial.title_new"))
        self.resize(340, 380)
        self.setStyleSheet("""
            QDialog{background-color:#f7f3ed;border-radius:16px;}
            QLabel{font-size:13px;color:#333333;background:transparent;}
            QLineEdit, QComboBox{padding:4px;border:1px solid #d8d2c5;border-radius:6px;background:#fff;font-size:13px;}
            QSpinBox{border:1px solid #d8d2c5;border-radius:6px;background:#fff;font-size:13px;}
            QCheckBox{font-size:13px;color:#333;padding:2px;}
            QRadioButton{font-size:13px;color:#333;padding:2px;}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText(tr("memorial.name_placeholder"))

        self.radio_solar = QRadioButton(tr("memorial.solar"))
        self.radio_lunar = QRadioButton(tr("memorial.lunar"))
        self.radio_solar.setChecked(True)
        self._type_group = QButtonGroup(self)
        self._type_group.addButton(self.radio_solar)
        self._type_group.addButton(self.radio_lunar)

        self.chk_leap = QCheckBox(tr("memorial.leap"))
        self.chk_leap.setEnabled(False)

        self.radio_solar.toggled.connect(self._on_type_changed)
        self.radio_lunar.toggled.connect(self._on_type_changed)

        self.combo_repeat = QComboBox()
        self.combo_repeat.addItem(tr("memorial.repeat_year"), REPEAT_YEAR)
        self.combo_repeat.addItem(tr("memorial.repeat_month"), REPEAT_MONTH)
        self.combo_repeat.addItem(tr("memorial.repeat_week"), REPEAT_WEEK)
        self.combo_repeat.currentIndexChanged.connect(self._update_day_range)

        self.spin_month = QSpinBox()
        self.spin_month.setRange(1, 12)
        self.spin_month.setValue(1)

        self.spin_day = QSpinBox()
        self.spin_day.setRange(1, 31)
        self.spin_day.setValue(1)

        self.spin_advance = QSpinBox()
        self.spin_advance.setRange(0, 30)
        self.spin_advance.setValue(3)

        self.chk_enabled = QCheckBox(tr("memorial.enabled"))
        self.chk_enabled.setChecked(True)

        # 具名 Label：retranslate_ui 需要 setText，匿名构造无法刷新
        self.lbl_name = QLabel(tr("memorial.name"))
        self.lbl_repeat = QLabel(tr("memorial.repeat"))
        self.lbl_month = QLabel(tr("memorial.month"))
        self.lbl_day = QLabel(tr("memorial.day"))
        self.lbl_advance = QLabel(tr("memorial.advance"))

        layout.addWidget(self.lbl_name)
        layout.addWidget(self.edit_name)
        layout.addWidget(self.radio_solar)
        layout.addWidget(self.radio_lunar)
        layout.addWidget(self.chk_leap)
        layout.addWidget(self.lbl_repeat)
        layout.addWidget(self.combo_repeat)
        layout.addWidget(self.lbl_month)
        layout.addWidget(self.spin_month)
        layout.addWidget(self.lbl_day)
        layout.addWidget(self.spin_day)
        layout.addWidget(self.lbl_advance)
        layout.addWidget(self.spin_advance)
        layout.addWidget(self.chk_enabled)

        self._btn_box = make_button_box(self, on_accept=self._on_accept)
        layout.addWidget(self._btn_box)

        # 首次文本填充（mixin 挂载监听时控件尚未创建，不会自动触发）
        self.retranslate_ui()

    def retranslate_ui(self):
        """
        刷新全部静态文本。

        不触碰 radio / checkbox 勾选状态、spin 数值、combo 当前项。
        combo_repeat 用 setItemText 逐项更新，保住 currentData。
        """
        self.setWindowTitle(tr("memorial.title_new"))
        self.edit_name.setPlaceholderText(tr("memorial.name_placeholder"))
        self.lbl_name.setText(tr("memorial.name"))
        self.radio_solar.setText(tr("memorial.solar"))
        self.radio_lunar.setText(tr("memorial.lunar"))
        self.chk_leap.setText(tr("memorial.leap"))
        self.lbl_repeat.setText(tr("memorial.repeat"))
        self.lbl_month.setText(tr("memorial.month"))
        self.lbl_day.setText(tr("memorial.day"))
        self.lbl_advance.setText(tr("memorial.advance"))
        self.chk_enabled.setText(tr("memorial.enabled"))

        for i, key in enumerate(("memorial.repeat_year",
                                 "memorial.repeat_month",
                                 "memorial.repeat_week")):
            self.combo_repeat.setItemText(i, tr(key))

        # day spin 的 suffix 依赖当前 repeat_type。只更新后缀，
        # 不调用 _update_day_range（那会重跑状态机，副作用更大）。
        if self.combo_repeat.currentData() == REPEAT_WEEK:
            self.spin_day.setSuffix(tr("memorial.weekday_suffix"))
        else:
            self.spin_day.setSuffix("")

        retranslate_button_box(self._btn_box)

    def _on_type_changed(self):
        is_solar = self.radio_solar.isChecked()
        self.chk_leap.setEnabled(not is_solar)
        # 不再清空 chk_leap：勾选状态是"用户意图记忆"，
        # 是否生效由 get_data() 按 type 决定。
        self._update_day_range()

    def _update_day_range(self, _idx: int = None):
        """根据重复类型更新日期输入范围。"""
        repeat_type = self.combo_repeat.currentData()
        was_week = self._last_repeat_type == REPEAT_WEEK
        is_week = repeat_type == REPEAT_WEEK

        if is_week and not was_week:
            # 刚进入 WEEK：快照用户当前的公/农历 + 闰月意图，
            # 切回其它周期时再恢复。用 not was_week 守卫，避免
            # WEEK 内部的重复调用（load_data 末尾那次）把快照冲掉。
            self._saved_type_lunar = self.radio_lunar.isChecked()
            self._saved_isleap = self.chk_leap.isChecked()

        if is_week:
            self.spin_day.setMinimum(1)
            self.spin_day.setMaximum(7)
            self.spin_day.setSuffix(tr("memorial.weekday_suffix"))
            self.spin_month.setEnabled(False)

            self.radio_solar.blockSignals(True)
            self.radio_lunar.blockSignals(True)
            try:
                self.radio_solar.setChecked(True)
            finally:
                self.radio_solar.blockSignals(False)
                self.radio_lunar.blockSignals(False)
            self.radio_lunar.setEnabled(False)
            self.chk_leap.setEnabled(False)
            self.chk_leap.setChecked(False)
        else:
            self.spin_day.setMinimum(1)
            self.spin_day.setMaximum(31)
            self.spin_day.setSuffix("")
            self.spin_month.setEnabled(repeat_type == REPEAT_YEAR)
            self.radio_lunar.setEnabled(True)

            # 从 WEEK 切回时恢复意图。必须阻塞信号：否则 setChecked
            # 会重入 _on_type_changed → _update_day_range，形成一轮
            # 无意义但依赖赋值顺序的递归。
            if was_week and self._saved_type_lunar:
                self.radio_lunar.blockSignals(True)
                try:
                    self.radio_lunar.setChecked(True)
                finally:
                    self.radio_lunar.blockSignals(False)

            if was_week and self.radio_lunar.isChecked() and self._saved_isleap:
                self.chk_leap.setChecked(True)
            self.chk_leap.setEnabled(self.radio_lunar.isChecked())

        self._last_repeat_type = repeat_type

    def _on_accept(self):
        if not self.edit_name.text().strip():
            msg_warn(self, tr("msg.hint"), tr("msg.name_empty"))
            return

        repeat_type = self.combo_repeat.currentData()
        is_solar = self.radio_solar.isChecked()
        if repeat_type == REPEAT_YEAR:
            month = self.spin_month.value()
            day = self.spin_day.value()
            if is_solar:
                _, last_day = calendar.monthrange(REFERENCE_LEAP_YEAR, month)
                if day > last_day:
                    msg_warn(
                        self, tr("msg.hint"),
                        tr("memorial.warn_solar_day").format(
                            month=month, day=day, max_day=last_day))
                    return
            else:
                if day > 30:
                    msg_warn(self, tr("msg.hint"),
                             tr("memorial.warn_lunar_day_max"))
                    return
                if self.chk_leap.isChecked():
                    reply = QMessageBox.question(
                        self, tr("msg.hint"),
                        tr("memorial.warn_leap_rare"),
                        QMessageBox.StandardButton.Yes
                        | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes,
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        return
        elif repeat_type == REPEAT_MONTH:
            day = self.spin_day.value()
            if is_solar:
                if day > 28:
                    reply = QMessageBox.question(
                        self, tr("msg.hint"),
                        tr("memorial.warn_day_overflow").format(day=day),
                        QMessageBox.StandardButton.Yes
                        | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes,
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        return
            else:
                if day > 30:
                    msg_warn(self, tr("msg.hint"),
                             tr("memorial.warn_lunar_day_max_short"))
                    return
        self.accept()

    def load_data(self, data: dict):
        self.edit_name.setText(data.get("name", ""))
        typ = data.get("type", "solar")
        if typ == "solar":
            self.radio_solar.setChecked(True)
        else:
            self.radio_lunar.setChecked(True)
        # 公历强制清闰月勾选；农历按数据恢复
        self.chk_leap.setChecked(
            bool(data.get("isleap", False)) if typ == "lunar" else False)
        repeat = data.get("repeat_type", REPEAT_YEAR)
        idx = self.combo_repeat.findData(repeat)
        if idx >= 0:
            self.combo_repeat.setCurrentIndex(idx)
        self.spin_month.setValue(data.get("month", 1))
        self.spin_day.setValue(data.get("day", 1))
        self.spin_advance.setValue(data.get("advance_days", 3))
        self.chk_enabled.setChecked(data.get("enabled", True))
        self._update_day_range()

    def get_data(self) -> dict:
        typ = "solar" if self.radio_solar.isChecked() else "lunar"
        repeat_type = self.combo_repeat.currentData()
        if repeat_type == REPEAT_WEEK:
            typ = "solar"  # 每周重复强制公历
        return {
            "name": self.edit_name.text().strip(),
            "type": typ,
            "month": self.spin_month.value(),
            "day": self.spin_day.value(),
            "isleap": self.chk_leap.isChecked() if typ == "lunar" else False,
            "advance_days": self.spin_advance.value(),
            "enabled": self.chk_enabled.isChecked(),
            "repeat_type": repeat_type,
        }


# ===================== 纪念日管理弹窗 =====================
class MemorialDialog(RetranslatableDialog, QDialog):
    def __init__(self, memorial_list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("memorial.title_manage"))
        self.resize(620, 420)
        self.memorial_list = copy.deepcopy(memorial_list)
        self.setStyleSheet("""
        QDialog{background-color:#f7f3ed;border-radius:16px;}
        QLabel{font-size:13px;color:#333333;background:transparent;}
        QListWidget{background:#fff;border:1px solid #d8d2c5;border-radius:8px;padding:4px;}
        QPushButton{
            min-width:80px;padding:7px 10px;
            background:#a7b8a1;color:white;border:none;border-radius:8px;font-size:12px;
        }
        QPushButton:hover{background:#8fa089;}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.list_widget = QListWidget()
        self.refresh_list()
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton(tr("btn.add"))
        self.btn_edit = QPushButton(tr("btn.edit"))
        self.btn_del = QPushButton(tr("btn.delete"))
        self.btn_all_enable = QPushButton(tr("btn.all_enable"))
        self.btn_all_disable = QPushButton(tr("btn.all_disable"))
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_edit)
        btn_layout.addWidget(self.btn_del)
        btn_layout.addWidget(self.btn_all_enable)
        btn_layout.addWidget(self.btn_all_disable)
        layout.addLayout(btn_layout)

        self._btn_box = make_button_box(self)
        layout.addWidget(self._btn_box)

        self.btn_add.clicked.connect(self.add_item)
        self.btn_edit.clicked.connect(self.edit_item)
        self.btn_del.clicked.connect(self.del_item)
        self.btn_all_enable.clicked.connect(self.batch_enable_all)
        self.btn_all_disable.clicked.connect(self.batch_disable_all)

        # 构造期已由 refresh_list 填充列表；这里只刷按钮 / 标题文本。
        # 为避免重跑 refresh_list（重新 normalize + sort），
        # retranslate_ui 里对列表项做了"只在文本确实变化时才重建"的处理。
        self.retranslate_ui()

    def retranslate_ui(self):
        """
        刷新全部静态文本。

        refresh_list() 会重建列表项文本；为保住当前选中行，先记录
        currentRow 再恢复。构造期调用时列表已由 __init__ 中的
        refresh_list 填好，本次刷新等价于幂等重建。
        """
        self.setWindowTitle(tr("memorial.title_manage"))
        self.btn_add.setText(tr("btn.add"))
        self.btn_edit.setText(tr("btn.edit"))
        self.btn_del.setText(tr("btn.delete"))
        self.btn_all_enable.setText(tr("btn.all_enable"))
        self.btn_all_disable.setText(tr("btn.all_disable"))
        retranslate_button_box(self._btn_box)

        row = self.list_widget.currentRow()
        self.refresh_list()
        if 0 <= row < self.list_widget.count():
            self.list_widget.setCurrentRow(row)

    def _sort_by_date(self):
        """
        三级排序：启用项优先 → 距下次发生日天数升序 → 无法计算的最后。
        单条数据异常不应中断整体排序，故 key 函数内 try/except。
        """
        today = date.today()

        def _sort_key(item: dict):
            disabled_rank = 0 if item.get("enabled", True) else 1
            try:
                target = get_next_memorial_date(
                    item, today, include_base=True, normalized=True)
            except Exception:
                target = None
            if target is None:
                return (disabled_rank, _NO_NEXT_DATE_RANK)
            return (disabled_rank, (target - today).days)

        self.memorial_list.sort(key=_sort_key)

    def refresh_list(self):
        self.list_widget.clear()
        normalized = []
        for m in self.memorial_list:
            if not isinstance(m, dict):
                continue
            try:
                normalized.append(normalize_memorial(m))
            except Exception:
                continue
        self.memorial_list = normalized
        self._sort_by_date()

        repeat_name_map = {
            REPEAT_YEAR: tr("memorial.manage.repeat_prefix_year"),
            REPEAT_MONTH: tr("memorial.manage.repeat_prefix_month"),
            REPEAT_WEEK: tr("memorial.manage.repeat_prefix_week"),
        }

        for item in self.memorial_list:
            tname = (tr("memorial.manage.type_solar")
                     if item["type"] == "solar"
                     else tr("memorial.manage.type_lunar"))
            leap = (tr("memorial.manage.leap_prefix")
                    if item.get("isleap", False) else "")
            advance = item.get("advance_days", 0)
            enabled = item.get("enabled", True)
            repeat = repeat_name_map.get(
                item.get("repeat_type", REPEAT_YEAR),
                tr("memorial.manage.repeat_prefix_year"))
            status_text = (tr("memorial.manage.status_enabled") if enabled
                           else tr("memorial.manage.status_disabled"))

            if item.get("repeat_type") == REPEAT_WEEK:
                # normalize 已夹取到 1..7，这里再夹一次以防手工改过配置
                try:
                    wd = max(1, min(7, int(item.get("day", 1))))
                except (TypeError, ValueError):
                    wd = 1
                week_key = f"weekday.short.{wd}"
                week_text = tr(week_key)
                # tr 三级回退会在缺 key 时返回 key 本身；此时退化为数字，
                # 比让用户看到 "weekday.short.6" 更体面。
                if week_text == week_key:
                    week_text = str(wd)
                date_text = tr("memorial.manage.week_fmt").format(week=week_text)
            else:
                date_text = tr("memorial.manage.date_fmt").format(
                    month=item["month"], day=item["day"])

            text = (f"{status_text} | {item['name']} | {repeat} | "
                    f"{tname}{leap}{date_text} | "
                    f"{tr('memorial.manage.advance_fmt').format(advance=advance)}")
            QListWidgetItem(text, self.list_widget)

    def add_item(self):
        dlg = AddMemorialDialog(self)
        if dlg.exec():
            new_item = dlg.get_data()
            self.memorial_list.append(new_item)
            self.refresh_list()
            # 排序后位置不定，按字段反查行号定位光标。
            # TODO(known-issue): 同名 + 同 type/repeat_type/month/day 的条目
            #   会被误判为同一条（仅影响光标位置，不影响数据正确性）。
            #   修复需引入唯一标记或改为"不排序 + 展示副本"的 refresh 契约。
            for row in range(self.list_widget.count()):
                item = self.memorial_list[row]
                if (item.get("name") == new_item.get("name")
                        and item.get("repeat_type") == new_item.get("repeat_type")
                        and item.get("day") == new_item.get("day")
                        and item.get("month") == new_item.get("month")
                        and item.get("type") == new_item.get("type")):
                    self.list_widget.setCurrentRow(row)
                    break

    def edit_item(self):
        row = self.list_widget.currentRow()
        if row < 0:
            msg_info(self, tr("msg.hint"), tr("memorial.manage.select_first"))
            return
        dlg = AddMemorialDialog(self)
        dlg.load_data(self.memorial_list[row])
        if dlg.exec():
            self.memorial_list[row] = dlg.get_data()
            self.refresh_list()

    def del_item(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            reply = QMessageBox.question(
                self, tr("memorial.manage.confirm_delete_title"),
                tr("memorial.confirm_delete"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                del self.memorial_list[row]
                self.refresh_list()

    def batch_enable_all(self):
        if not self.memorial_list:
            msg_info(self, tr("msg.hint"), tr("memorial.manage.empty"))
            return
        reply = QMessageBox.question(
            self, tr("msg.confirm"),
            tr("memorial.manage.confirm_enable_all"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            for item in self.memorial_list:
                item["enabled"] = True
            self.refresh_list()

    def batch_disable_all(self):
        if not self.memorial_list:
            msg_info(self, tr("msg.hint"), tr("memorial.manage.empty"))
            return
        reply = QMessageBox.question(
            self, tr("msg.confirm"),
            tr("memorial.manage.confirm_disable_all"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            for item in self.memorial_list:
                item["enabled"] = False
            self.refresh_list()

    def get_result(self):
        return self.memorial_list


# ===================== 纪念日提醒弹窗 =====================
class MemorialRemindDialog(RetranslatableDialog, QDialog):
    def __init__(self, memorial_list, theme, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("memorial.remind_title"))
        self.resize(300, 240)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet("""
        QDialog{background-color:#f7f3ed;border-radius:16px;}
        QLabel{font-size:13px;color:#333333;background:transparent;}
        QPushButton{
            min-width:86px;padding:7px 18px;
            background:#a7b8a1;color:#ffffff;border:none;
            border-radius:10px;font-size:12px;
        }
        QPushButton:hover{background:#8fa089;}
        QPushButton:pressed{background:#798b74;}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # 具名：retranslate_ui 需要 setText
        self.title_label = QLabel(tr("memorial.remind_heading"))
        self.title_label.setStyleSheet(
            "font-size:16px;font-weight:bold;color:#4A4A4A;")
        layout.addWidget(self.title_label)

        content_text = "\n".join(f"• {line}" for line in memorial_list)
        orange_color = theme.get("memorial_orange", "#D47026")
        content_label = QLabel(content_text)
        content_label.setStyleSheet(
            f"font-size:14px;color:{orange_color};background:transparent;")
        content_label.setWordWrap(True)
        layout.addWidget(content_label)
        layout.addStretch(1)

        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton(tr("memorial.remind_ok"))
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_ok)
        layout.addLayout(btn_layout)

        self.retranslate_ui()

    def retranslate_ui(self):
        """
        刷新全部静态文本。

        不重建命中列表——列表内容是调用方传入的数据而非静态文案，
        重建需要重跑 reminder_manager 的命中逻辑，超出对话框职责。
        """
        self.setWindowTitle(tr("memorial.remind_title"))
        self.title_label.setText(tr("memorial.remind_heading"))
        self.btn_ok.setText(tr("memorial.remind_ok"))