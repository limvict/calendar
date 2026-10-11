# coding: utf-8
"""
设置对话框。

数据约定：self.cfg 是唯一可写数据源（构造时深拷贝一份）。对话框
只改 self.cfg，不触碰全局 config。用户点"确定"后由 main 侧调用
_apply_settings(dlg) 统一写回；点"取消"则丢弃副本。导入配置时
同样只覆盖 self.cfg 并刷新控件。

依赖方向：base / messages / memorial（打开子对话框）+ i18n / config。
"""
import copy
import json

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QCheckBox, QSpinBox, QPushButton, QSlider, QGroupBox,
    QFileDialog, QComboBox,
)

from i18n import tr, available_languages
from config import get_logger

from .messages import msg_info, msg_error
from .base import (
    RetranslatableDialog,
    make_button_box,
    retranslate_button_box,
)
from .memorial import MemorialDialog

logger = get_logger()

__all__ = ["SettingDialog"]


# ===================== 设置弹窗 =====================
class SettingDialog(RetranslatableDialog, QDialog):
    """
    设置对话框。

    数据约定：self.cfg 是唯一可写数据源（构造时深拷贝一份）。对话框
    只改 self.cfg，不触碰全局 config。用户点"确定"后由 main 侧调用
    _apply_settings(dlg) 统一写回；点"取消"则丢弃副本。导入配置时
    同样只覆盖 self.cfg 并刷新控件。
    """
    preview_opacity_changed = pyqtSignal(float)
    preview_topmost_changed = pyqtSignal(bool)

    def __init__(self, cfg, auto_start_state, topmost_state, opacity,
                 memorial_remind, memorial_sound, parent=None):
        super().__init__(parent)
        self.cfg = copy.deepcopy(cfg) if isinstance(cfg, dict) else {}
        self.cfg.setdefault("memorial_days", [])
        self.cfg.setdefault("memorial_cfg", {})

        self._auto_start_state = bool(auto_start_state)
        self._topmost_state = bool(topmost_state)
        self._opacity_val = float(opacity)
        self.memorial_remind = bool(memorial_remind)
        self.memorial_sound = bool(memorial_sound)
        self.parent_win = parent

        self.setWindowTitle(tr("setting.title"))
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

        self.group_general = QGroupBox(tr("setting.general"))
        lay_general = QGridLayout(self.group_general)
        lay_general.setSpacing(10)
        self.combo_lang = QComboBox()
        for code, name in available_languages():
            self.combo_lang.addItem(name, code)
        cur_lang = self.cfg.get("language", "zh_CN")
        idx = self.combo_lang.findData(cur_lang)
        if idx >= 0:
            self.combo_lang.setCurrentIndex(idx)

        self.lbl_lang = QLabel(tr("setting.language"))
        lay_general.addWidget(self.lbl_lang, 5, 0)
        lay_general.addWidget(self.combo_lang, 5, 1)

        self.chk_autostart = QCheckBox(tr("setting.autostart"))
        self.chk_autostart.setChecked(self._auto_start_state)

        self.chk_topmost = QCheckBox(tr("setting.topmost"))
        self.chk_topmost.setChecked(self._topmost_state)
        self.chk_topmost.toggled.connect(
            lambda v: self.preview_topmost_changed.emit(v))

        self.chk_mem_remind = QCheckBox(tr("setting.memorial_remind"))
        self.chk_mem_remind.setChecked(self.memorial_remind)

        self.chk_mem_sound = QCheckBox(tr("setting.memorial_sound"))
        self.chk_mem_sound.setChecked(self.memorial_sound)

        lay_general.addWidget(self.chk_autostart, 0, 0)
        lay_general.addWidget(self.chk_topmost, 1, 0)
        lay_general.addWidget(self.chk_mem_remind, 2, 0)
        lay_general.addWidget(self.chk_mem_sound, 3, 0)

        self.lbl_op = QLabel(tr("setting.opacity"))
        self.slider_op = QSlider(Qt.Orientation.Horizontal)
        self.slider_op.setRange(60, 100)
        self.slider_op.setValue(int(opacity * 100))
        self.lbl_op_val = QLabel(f"{int(opacity * 100)}%")
        self.slider_op.valueChanged.connect(self._on_slider_change)

        self.lay_op = QHBoxLayout()
        self.lay_op.addWidget(self.lbl_op)
        self.lay_op.addWidget(self.slider_op)
        self.lay_op.addWidget(self.lbl_op_val)
        lay_general.addLayout(self.lay_op, 4, 0)

        main_layout.addWidget(self.group_general)

        self.group_data = QGroupBox(tr("setting.data"))
        lay_data = QHBoxLayout(self.group_data)
        self.btn_export = QPushButton(tr("btn.export"))
        self.btn_import = QPushButton(tr("btn.import"))
        self.btn_export.clicked.connect(self._export_config)
        self.btn_import.clicked.connect(self._import_config)
        lay_data.addWidget(self.btn_export)
        lay_data.addWidget(self.btn_import)
        main_layout.addWidget(self.group_data)

        self.btn_mem = QPushButton(tr("btn.manage_memorial"))
        self.btn_mem.clicked.connect(self.open_mem_dialog)
        main_layout.addWidget(self.btn_mem)

        self._btn_box = make_button_box(self)
        main_layout.addWidget(self._btn_box)

        # 首次文本填充
        self.retranslate_ui()

    def _on_slider_change(self, v: int):
        self._opacity_val = v / 100
        self.lbl_op_val.setText(f"{v}%")
        self.preview_opacity_changed.emit(self._opacity_val)

    def _export_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("msg.export_title"),
            "calendar_config.json", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
            msg_info(self, tr("msg.success"), tr("msg.export_success"))
        except Exception as e:
            msg_error(self, tr("msg.error"),
                      tr("msg.export_failed").format(error=e))

    def _import_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("msg.import_title"), "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("root is not a dict")
        except Exception as e:
            msg_error(self, tr("msg.error"),
                      tr("msg.import_format_error").format(error=e))
            return
        # merge 而非整体替换：文件里出现的键覆盖 self.cfg，未出现的键
        # 保留用户在对话框里已做但尚未保存的改动（透明度、语言等）。
        for k, v in data.items():
            self.cfg[k] = v
        if not isinstance(self.cfg.get("memorial_days"), list):
            self.cfg["memorial_days"] = []
        if not isinstance(self.cfg.get("memorial_cfg"), dict):
            self.cfg["memorial_cfg"] = {}
        self._reload_from_cfg()
        msg_info(self, tr("msg.success"), tr("msg.import_success"))

    def _reload_from_cfg(self):
        """
        导入配置后刷新控件显示。

        期间 blockSignals，避免 setChecked/setValue 触发预览信号让主窗口
        在"用户点导入但随后取消"的流程里闪一下。
        """
        widgets = (
            self.chk_topmost, self.chk_mem_remind,
            self.chk_mem_sound, self.slider_op,
            self.combo_lang,
        )
        for w in widgets:
            w.blockSignals(True)
        try:
            self.chk_topmost.setChecked(bool(self.cfg.get("topmost", False)))

            mem_cfg = self.cfg.get("memorial_cfg") or {}
            self.chk_mem_remind.setChecked(
                bool(mem_cfg.get("enable_remind", True)))
            self.chk_mem_sound.setChecked(
                bool(mem_cfg.get("sound_enable", True)))

            # 自启状态来自注册表，不跟随导入文件
            self.chk_autostart.setChecked(self._auto_start_state)

            try:
                op = float(self.cfg.get("opacity", 0.92))
            except (TypeError, ValueError):
                op = 0.92
            op = max(0.6, min(1.0, op))
            self.slider_op.setValue(int(op * 100))

            # slider 被 block 后 _on_slider_change 未触发，手动同步派生状态
            self._opacity_val = op
            self.lbl_op_val.setText(f"{int(op * 100)}%")
            cur_lang = self.cfg.get("language", "zh_CN")
            idx = self.combo_lang.findData(cur_lang)
            if idx >= 0:
                self.combo_lang.setCurrentIndex(idx)
        finally:
            for w in widgets:
                w.blockSignals(False)

    def retranslate_ui(self):
        """
        刷新 SettingDialog 的全部静态文本。

        不触碰任何用户输入 / 控件值（滑块位置、复选框状态、
        combo_lang 当前项、self._opacity_val 等）。
        """
        self.setWindowTitle(tr("setting.title"))
        self.group_general.setTitle(tr("setting.general"))
        self.group_data.setTitle(tr("setting.data"))
        self.lbl_lang.setText(tr("setting.language"))
        self.chk_autostart.setText(tr("setting.autostart"))
        self.chk_topmost.setText(tr("setting.topmost"))
        self.chk_mem_remind.setText(tr("setting.memorial_remind"))
        self.chk_mem_sound.setText(tr("setting.memorial_sound"))
        self.lbl_op.setText(tr("setting.opacity"))
        self.btn_export.setText(tr("btn.export"))
        self.btn_import.setText(tr("btn.import"))
        self.btn_mem.setText(tr("btn.manage_memorial"))
        retranslate_button_box(self._btn_box)

    def open_mem_dialog(self):
        dlg = MemorialDialog(self.cfg.get("memorial_days", []), self)
        if dlg.exec():
            self.cfg["memorial_days"] = dlg.get_result()

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

    def get_language(self) -> str:
        return self.combo_lang.currentData() or "zh_CN"