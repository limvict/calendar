# coding: utf-8
import copy
import json
import calendar
from PyQt6.QtCore import Qt, pyqtSignal, QDate
from PyQt6.QtWidgets import (
    QMessageBox, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QCheckBox, QSpinBox, QDialogButtonBox,
    QListWidget, QListWidgetItem, QPushButton, QSlider, QGroupBox,
    QFileDialog, QComboBox, QRadioButton, QButtonGroup,
)
from utils import (
    REPEAT_YEAR, REPEAT_MONTH, REPEAT_WEEK,
    normalize_memorial, get_next_memorial_date,
)

# ===================== 纪念日列表排序常量 =====================
# 无法计算下次发生日期的纪念日排到最后。
# 取值需远大于任何真实"距今天数"，避免与正常条目冲突。
_NO_NEXT_DATE_RANK = 10 ** 6

# ===================== 基础消息弹窗基类 =====================
class _BaseMsgBox(QMessageBox):
    """消息弹窗基类：复用样式，仅按钮颜色区分"""
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

# ===================== 纪念日新增/编辑弹窗 =====================
class AddMemorialDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新增/编辑纪念日")
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
        self.edit_name.setPlaceholderText("纪念日名称（如：生日）")

        self.radio_solar = QRadioButton("公历日期")
        self.radio_lunar = QRadioButton("农历日期")
        self.radio_solar.setChecked(True)
        self._type_group = QButtonGroup(self)
        self._type_group.addButton(self.radio_solar)
        self._type_group.addButton(self.radio_lunar)

        self.chk_leap = QCheckBox("闰月（仅农历生效）")
        self.chk_leap.setEnabled(False)

        self.radio_solar.toggled.connect(self._on_type_changed)
        self.radio_lunar.toggled.connect(self._on_type_changed)

        # 重复周期
        self.combo_repeat = QComboBox()
        self.combo_repeat.addItem("每年重复", REPEAT_YEAR)
        self.combo_repeat.addItem("每月重复", REPEAT_MONTH)
        self.combo_repeat.addItem("每周重复", REPEAT_WEEK)
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

        self.chk_enabled = QCheckBox("启用该纪念日提醒")
        self.chk_enabled.setChecked(True)

        layout.addWidget(QLabel("名称"))
        layout.addWidget(self.edit_name)
        layout.addWidget(self.radio_solar)
        layout.addWidget(self.radio_lunar)
        layout.addWidget(self.chk_leap)
        layout.addWidget(QLabel("重复周期"))
        layout.addWidget(self.combo_repeat)
        layout.addWidget(QLabel("月份"))
        layout.addWidget(self.spin_month)
        layout.addWidget(QLabel("日期/星期"))
        layout.addWidget(self.spin_day)
        layout.addWidget(QLabel("提前几天提醒(0=当天提醒)"))
        layout.addWidget(self.spin_advance)
        layout.addWidget(self.chk_enabled)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _on_type_changed(self):
        """公历/农历切换：更新闰月可用性和日期范围"""
        is_solar = self.radio_solar.isChecked()
        self.chk_leap.setEnabled(not is_solar)
        if is_solar:
            self.chk_leap.setChecked(False)
        self._update_day_range()

    def _update_day_range(self):
        """根据重复类型更新日期输入范围"""
        repeat_type = self.combo_repeat.currentData()
        if repeat_type == REPEAT_WEEK:
            self.spin_day.setRange(1, 7)
            self.spin_day.setSuffix("  (1=周一, 7=周日)")
            self.spin_month.setEnabled(False)
            # 【#19】每周重复是纯公历概念，强制公历并禁用农历选项。
            # 阻断 toggled 信号，避免 setChecked 触发 _on_type_changed
            # 再次进入 _update_day_range 造成递归驱动。
            self.radio_solar.blockSignals(True)
            self.radio_lunar.blockSignals(True)
            self.radio_solar.setChecked(True)
            self.radio_solar.blockSignals(False)
            self.radio_lunar.blockSignals(False)
            self.radio_lunar.setEnabled(False)
            self.chk_leap.setEnabled(False)
            self.chk_leap.setChecked(False)
        else:
            self.spin_day.setRange(1, 31)
            self.spin_day.setSuffix("")
            self.spin_month.setEnabled(repeat_type == REPEAT_YEAR)
            self.radio_lunar.setEnabled(True)
            self.chk_leap.setEnabled(not self.radio_solar.isChecked())

    def _on_accept(self):
        if not self.edit_name.text().strip():
            msg_warn(self, "提示", "名称不能为空")
            return

        repeat_type = self.combo_repeat.currentData()
        is_solar = self.radio_solar.isChecked()

        # 【P2 修复】按"周期 × 公历/农历"补齐四类组合的校验，
        # 原实现只覆盖了"公历 + 每年"，其它三种能被写入非法值：
        #   - 农历 + 每年/每月：日 > 30 会被 normalize_memorial 静默 clamp 到 30
        #   - 公历 + 每月：日 > 28 会在 2 月按月末收敛（设计如此，不阻断）
        if repeat_type == REPEAT_YEAR:
            month = self.spin_month.value()
            day = self.spin_day.value()
            if is_solar:
                if not QDate.isValid(2024, month, day):
                    _, last_day = calendar.monthrange(2024, month)
                    msg_warn(
                        self, "提示",
                        f"{month}月没有{day}日，请输入 1~{last_day} 之间的日期"
                    )
                    return
            else:
                # 农历：日上限 30（农历月份最多 30 天）。
                # 精确校验"该农历月是否存在该日"需要构建农历索引，
                # 对 UI 层太重；只做范围校验，运行期由 normalize_memorial
                # 的 clamp + get_next_memorial_date 的降级路径兜底。
                if day > 30:
                    msg_warn(
                        self, "提示",
                        "农历日期最大为 30 日（农历每月最多 30 天）"
                    )
                    return

        elif repeat_type == REPEAT_MONTH:
            day = self.spin_day.value()
            if is_solar:
                # 公历每月：29/30/31 日在某些月份不存在，会按月末收敛。
                # 这是设计行为（与 memorial.py 一致），只做非阻断提示。
                if day > 28:
                    reply = QMessageBox.question(
                        self, "提示",
                        f"每月 {day} 日在部分月份不存在，"
                        f"届时将自动按该月最后一天提醒。\n是否继续？",
                        QMessageBox.StandardButton.Yes
                        | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes,
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        return
            else:
                if day > 30:
                    msg_warn(self, "提示", "农历日期最大为 30 日")
                    return
        # REPEAT_WEEK：spin_day 已被 _update_day_range 限制在 1~7，无需校验

        self.accept()

    def load_data(self, data: dict):
        self.edit_name.setText(data.get("name", ""))
        typ = data.get("type", "solar")
        if typ == "solar":
            self.radio_solar.setChecked(True)
        else:
            self.radio_lunar.setChecked(True)
        self.chk_leap.setChecked(data.get("isleap", False))
        repeat = data.get("repeat_type", REPEAT_YEAR)
        idx = self.combo_repeat.findData(repeat)
        if idx >= 0:
            self.combo_repeat.setCurrentIndex(idx)
        self.spin_month.setValue(data.get("month", 1))
        self.spin_day.setValue(data.get("day", 1))
        self.spin_advance.setValue(data.get("advance_days", 3))
        self.chk_enabled.setChecked(data.get("enabled", True))
        # 载入后刷新一次控件可用性，保证“周重复 -> 禁农历”一致
        self._update_day_range()

    def get_data(self) -> dict:
        typ = "solar" if self.radio_solar.isChecked() else "lunar"
        repeat_type = self.combo_repeat.currentData()
        # 每周重复强制公历，避免保存出非法组合
        if repeat_type == REPEAT_WEEK:
            typ = "solar"
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
class MemorialDialog(QDialog):
    def __init__(self, memorial_list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("纪念日管理")
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
        self.btn_add = QPushButton("新增")
        self.btn_edit = QPushButton("编辑选中")
        self.btn_del = QPushButton("删除选中")
        self.btn_all_enable = QPushButton("全部启用")
        self.btn_all_disable = QPushButton("全部禁用")
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_edit)
        btn_layout.addWidget(self.btn_del)
        btn_layout.addWidget(self.btn_all_enable)
        btn_layout.addWidget(self.btn_all_disable)
        layout.addLayout(btn_layout)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(btn_box)

        self.btn_add.clicked.connect(self.add_item)
        self.btn_edit.clicked.connect(self.edit_item)
        self.btn_del.clicked.connect(self.del_item)
        self.btn_all_enable.clicked.connect(self.batch_enable_all)
        self.btn_all_disable.clicked.connect(self.batch_disable_all)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)

    def _sort_by_date(self):
        """
        排序规则（三级）：
          1. 启用项排在禁用项之前
          2. 同类中按"距下次发生日天数"升序
          3. 无法计算下次日期的排到最后

        单条数据异常不应中断整体排序，故在 key 函数内 try/except。
        """
        from datetime import date
        today = date.today()

        def _sort_key(item: dict):
            # 启用优先：0 在前，1 沉底
            disabled_rank = 0 if item.get("enabled", True) else 1

            try:
                target = get_next_memorial_date(item, today, include_base=True)
            except Exception:
                target = None

            if target is None:
                return (disabled_rank, _NO_NEXT_DATE_RANK)

            return (disabled_rank, (target - today).days)

        self.memorial_list.sort(key=_sort_key)

    def refresh_list(self):
        self.list_widget.clear()
        self.memorial_list = [
            normalize_memorial(m) for m in self.memorial_list]
        self._sort_by_date()

        repeat_name_map = {
            REPEAT_YEAR: "每年", REPEAT_MONTH: "每月", REPEAT_WEEK: "每周"}
        week_cn = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "日"}

        for item in self.memorial_list:
            tname = "公历" if item["type"] == "solar" else "农历"
            leap = "闰" if item.get("isleap", False) else ""
            advance = item.get("advance_days", 0)
            enabled = item.get("enabled", True)
            repeat = repeat_name_map.get(
                item.get("repeat_type", REPEAT_YEAR), "每年")
            status_text = "✅启用" if enabled else "❌禁用"

            if item.get("repeat_type") == REPEAT_WEEK:
                date_text = f"周{week_cn.get(item['day'], item['day'])}"
            else:
                date_text = f"{item['month']}月{item['day']}日"

            text = (
                f"{status_text} | {item['name']} | {repeat} | "
                f"{tname}{leap}{date_text} | 提前{advance}天提醒"
            )
            QListWidgetItem(text, self.list_widget)

    def add_item(self):
        dlg = AddMemorialDialog()
        if dlg.exec():
            new_item = dlg.get_data()
            self.memorial_list.append(new_item)
            self.refresh_list()
            # 排序后新条目位置不定，需按字段反查行号。
            # 注意：若存在同名字段的老条目，命中第一条，这是可接受的
            # UI 行为；如需精确定位，应让 normalize_memorial 打 _normalized
            # 标记并改用身份比较（改动面较大，暂不引入）。
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
            msg_info(self, "提示", "请先选中一条纪念日")
            return
        dlg = AddMemorialDialog()
        dlg.load_data(self.memorial_list[row])
        if dlg.exec():
            self.memorial_list[row] = dlg.get_data()
            self.refresh_list()

    def del_item(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            reply = QMessageBox.question(
                self, "确认删除", "确定删除这条纪念日？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                del self.memorial_list[row]
                self.refresh_list()

    def batch_enable_all(self):
        if not self.memorial_list:
            msg_info(self, "提示", "暂无纪念日")
            return
        reply = QMessageBox.question(
            self, "确认", "确定将所有纪念日【启用提醒】？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            for item in self.memorial_list:
                item["enabled"] = True
            self.refresh_list()

    def batch_disable_all(self):
        if not self.memorial_list:
            msg_info(self, "提示", "暂无纪念日")
            return
        reply = QMessageBox.question(
            self, "确认", "确定将所有纪念日【禁用提醒】？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            for item in self.memorial_list:
                item["enabled"] = False
            self.refresh_list()

    def get_result(self):
        return self.memorial_list

# ===================== 设置弹窗 =====================
class SettingDialog(QDialog):
    """
    设置对话框。

    设计约定：
    - self.cfg 是唯一可写数据源（构造时深拷贝一份）。
      对话框只改 self.cfg，不触碰全局 config。
    - 用户点“确定”后由 main 侧调用 _apply_settings(dlg) 统一写回；
      点“取消”则丢弃 self.cfg，全局配置不受影响。
    - 导入配置时只覆盖 self.cfg 并刷新控件，同样不直接改全局 config。
    """
    preview_opacity_changed = pyqtSignal(float)
    preview_topmost_changed = pyqtSignal(bool)

    def __init__(self, cfg, auto_start_state, topmost_state, opacity,
                 memorial_remind, memorial_sound, parent=None):
        super().__init__(parent)
        # 深拷贝以防调用方传入内部引用；后续所有改动都落在这个副本上。
        self.cfg = copy.deepcopy(cfg) if isinstance(cfg, dict) else {}
        self.cfg.setdefault("memorial_days", [])
        self.cfg.setdefault("memorial_cfg", {})

        self._auto_start_state = bool(auto_start_state)
        self._topmost_state = bool(topmost_state)
        self._opacity_val = float(opacity)
        self.memorial_remind = bool(memorial_remind)
        self.memorial_sound = bool(memorial_sound)
        self.parent_win = parent

        self.setWindowTitle("设置")
        self.resize(440, 460)
        self.setStyleSheet("""
        QDialog{background-color:#f7f3ed;border-radius:16px;}
        QLabel{font-size:13px;color:#333333;background:transparent;}
        QCheckBox{font-size:13px;color:#333;padding:4px;}
        QSpinBox{border:1px solid #d8d2c5;border-radius:6px;background:#fff;font-size:13px;}
        QGroupBox{font-size:13px;border:1px solid #d8d2c5;border-radius:8px;margin-top:8px;}
        QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top left;margin-left:10px;padding:0 4px;}
        QSlider::handle{background:#a7b8a1;border-radius:8px;width:16px;height:16px;}
        QSlider::groove:horizontal{height:6px;background:#ddd;border-radius:3px;}
        QPushButton{
            min-width:86px;padding:7px 14px;
            background:#a7b8a1;color:white;border:none;border-radius:10px;font-size:12px;
        }
        QPushButton:hover{background:#8fa089;}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(12)

        # ---------- 通用设置 ----------
        group_general = QGroupBox("通用设置")
        lay_general = QGridLayout(group_general)
        lay_general.setSpacing(10)

        self.chk_autostart = QCheckBox("Windows开机自启")
        self.chk_autostart.setChecked(self._auto_start_state)

        self.chk_topmost = QCheckBox("窗口置顶")
        self.chk_topmost.setChecked(self._topmost_state)
        self.chk_topmost.toggled.connect(
            lambda v: self.preview_topmost_changed.emit(v))

        self.chk_mem_remind = QCheckBox("启用纪念日提醒")
        self.chk_mem_remind.setChecked(self.memorial_remind)

        self.chk_mem_sound = QCheckBox("提醒时播放提示音")
        self.chk_mem_sound.setChecked(self.memorial_sound)

        lay_general.addWidget(self.chk_autostart, 0, 0)
        lay_general.addWidget(self.chk_topmost, 1, 0)
        lay_general.addWidget(self.chk_mem_remind, 2, 0)
        lay_general.addWidget(self.chk_mem_sound, 3, 0)

        lbl_op = QLabel("窗口透明度：")
        self.slider_op = QSlider(Qt.Orientation.Horizontal)
        self.slider_op.setRange(60, 100)
        self.slider_op.setValue(int(opacity * 100))
        self.lbl_op_val = QLabel(f"{int(opacity * 100)}%")
        self.slider_op.valueChanged.connect(self._on_slider_change)

        self.lay_op = QHBoxLayout()
        self.lay_op.addWidget(lbl_op)
        self.lay_op.addWidget(self.slider_op)
        self.lay_op.addWidget(self.lbl_op_val)
        lay_general.addLayout(self.lay_op, 4, 0)

        main_layout.addWidget(group_general)

        # ---------- 数据管理 ----------
        group_data = QGroupBox("数据管理")
        lay_data = QHBoxLayout(group_data)
        self.btn_export = QPushButton("导出配置")
        self.btn_import = QPushButton("导入配置")
        self.btn_export.clicked.connect(self._export_config)
        self.btn_import.clicked.connect(self._import_config)
        lay_data.addWidget(self.btn_export)
        lay_data.addWidget(self.btn_import)
        main_layout.addWidget(group_data)

        self.btn_mem = QPushButton("纪念日管理")
        self.btn_mem.clicked.connect(self.open_mem_dialog)
        main_layout.addWidget(self.btn_mem)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        main_layout.addWidget(btn_box)

    # ---------- 透明度滑块 ----------
    def _on_slider_change(self, v: int):
        self._opacity_val = v / 100
        self.lbl_op_val.setText(f"{v}%")
        self.preview_opacity_changed.emit(self._opacity_val)

    # ---------- 导出：导出对话框当前快照（含未提交修改） ----------
    def _export_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出配置", "calendar_config.json", "JSON文件 (*.json)")
        if not path:
            return
        try:
            # 导出当前快照，用户所见即所得；
            # 不依赖全局 config，避免“导出的是旧值”。
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
            msg_info(self, "成功", "配置已导出")
        except Exception as e:
            msg_error(self, "失败", f"导出失败\n{e}")

    # ---------- 导入：只改对话框快照，不碰全局 config ----------
    def _import_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入配置", "", "JSON文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("根节点不是 dict")
        except Exception as e:
            msg_error(self, "失败", f"导入失败，文件格式错误\n{e}")
            return

        self.cfg = data
        self.cfg.setdefault("memorial_days", [])
        self.cfg.setdefault("memorial_cfg", {})
        self._reload_from_cfg()
        msg_info(self, "成功", "配置已载入，点“确定”后生效")

    def _reload_from_cfg(self):
        """
        导入配置后刷新各控件显示。
        注意：setChecked / setValue 会触发 toggled / valueChanged，
        进而 emit 预览信号——这是预期行为（让用户先看到效果）。
        """
        self.chk_topmost.setChecked(bool(self.cfg.get("topmost", False)))

        mem_cfg = self.cfg.get("memorial_cfg") or {}
        self.chk_mem_remind.setChecked(bool(mem_cfg.get("enable_remind", True)))
        self.chk_mem_sound.setChecked(bool(mem_cfg.get("sound_enable", True)))

        # 自启状态来自注册表，不跟随导入文件
        self.chk_autostart.setChecked(self._auto_start_state)

        try:
            op = float(self.cfg.get("opacity", 0.92))
        except (TypeError, ValueError):
            op = 0.92
        op = max(0.6, min(1.0, op))
        self.slider_op.setValue(int(op * 100))

    # ---------- 纪念日管理：直接读写 self.cfg ----------
    def open_mem_dialog(self):
        dlg = MemorialDialog(self.cfg.get("memorial_days", []), self)
        if dlg.exec():
            self.cfg["memorial_days"] = dlg.get_result()

    # ---------- 结果读取（供 main 侧 _apply_settings 使用） ----------
    def get_auto_start_status(self) -> bool:
        return self.chk_autostart.isChecked()

    def get_topmost_status(self) -> bool:
        return self.chk_topmost.isChecked()

    def get_opacity(self) -> float:
        return self._opacity_val

    def get_memorial_list(self):
        return self.cfg.get("memorial_days", [])

    def get_mem_remind(self) -> bool:
        return self.chk_mem_remind.isChecked()

    def get_mem_sound(self) -> bool:
        return self.chk_mem_sound.isChecked()
    
# ===================== 纪念日提醒弹窗 =====================
class MemorialRemindDialog(QDialog):
    def __init__(self, memorial_list, theme, parent=None):
        super().__init__(parent)
        self.setWindowTitle("纪念日提醒")
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

        title_label = QLabel("今日纪念日提醒")
        title_label.setStyleSheet(
            "font-size:16px;font-weight:bold;color:#4A4A4A;"
        )
        layout.addWidget(title_label)

        content_text = "\n".join(f"• {line}" for line in memorial_list)
        orange_color = theme.get("memorial_orange", "#D47026")
        content_label = QLabel(content_text)
        content_label.setStyleSheet(
            f"font-size:14px;color:{orange_color};background:transparent;"
        )
        content_label.setWordWrap(True)
        layout.addWidget(content_label)
        layout.addStretch(1)

        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("知道了")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)