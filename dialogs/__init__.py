# coding: utf-8
"""
对话框集合的包入口。

按职责拆成多个子模块，本 __init__ 统一 re-export，保持
`from dialogs import Xxx` 的历史 import 路径不变。

模块结构：
  messages.py : 通用消息弹窗（msg_info / msg_warn / msg_error）
  base.py     : RetranslatableDialog + 按钮盒工具
  picker.py   : MonthYearPickerDialog
  memorial.py : AddMemorialDialog / MemorialDialog / MemorialRemindDialog
  settings.py : SettingDialog

依赖方向（单向，无环）：
  messages ← base ← memorial ← settings
                  ↖ picker
                  
“私有名仅为兼容旧调用点，不承诺长期存在”

"""
from .messages import msg_info, msg_warn, msg_error
from .base import (
    RetranslatableDialog,
    _make_button_box, make_button_box,
    _retranslate_button_box, retranslate_button_box,
)
from .picker import MonthYearPickerDialog
from .memorial import (
    AddMemorialDialog, MemorialDialog, MemorialRemindDialog,
)
from .settings import SettingDialog

__all__ = [
    # 通用消息弹窗
    "msg_info", "msg_warn", "msg_error",
    # 基础设施
    "RetranslatableDialog",
    "make_button_box", "retranslate_button_box",
    # 具体对话框
    "AddMemorialDialog", "MemorialDialog", "MemorialRemindDialog",
    "SettingDialog", "MonthYearPickerDialog",
]