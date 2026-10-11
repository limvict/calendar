# coding: utf-8
"""
对话框公共基础设施。

- RetranslatableDialog：i18n 语言切换 mixin，自动挂载 / 卸载监听。
- _make_button_box / _retranslate_button_box：QDialogButtonBox 的
  创建与重翻译工具。

依赖方向：本模块只依赖 PyQt6 + i18n + config，不依赖任何具体
对话框。这样 memorial / settings / picker 等子模块才能安全 import
本模块而不引入循环依赖。
"""
from typing import Callable, Optional

from PyQt6.QtWidgets import QDialog, QDialogButtonBox

from config import get_logger
from i18n import tr, on_language_changed, off_language_changed

logger = get_logger()

__all__ = [
    "RetranslatableDialog",
    "_make_button_box",
    "_retranslate_button_box",
    # 公开别名（新代码推荐使用；旧私有名保留以兼容既有调用点）
    "make_button_box",
    "retranslate_button_box",
]


# ===================== 按钮盒工具 =====================
def _make_button_box(
    dialog: QDialog, on_accept: Optional[Callable[[], None]] = None
) -> QDialogButtonBox:
    """创建带确定/取消的 QDialogButtonBox。

    统一处理三件事，避免每个对话框各写一遍时漏掉：
      - 中文化按钮文字；
      - accepted 连到 on_accept（默认 dialog.accept）；
      - rejected 连到 dialog.reject。

    调用方负责把返回值 addWidget 到自己的布局。
    """
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok
        | QDialogButtonBox.StandardButton.Cancel)
    box.button(QDialogButtonBox.StandardButton.Ok).setText(tr("btn.ok"))
    box.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("btn.cancel"))
    box.accepted.connect(on_accept if on_accept is not None else dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


def _retranslate_button_box(box: Optional[QDialogButtonBox]) -> None:
    """刷新 QDialogButtonBox 标准按钮的文本。

    允许 box 为 None：某些调用点在控件创建失败 / 提前 return 时可能
    拿到 None，这里静默返回比抛 AttributeError 更稳。
    """
    if box is None:
        return
    ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
    if ok_btn is not None:
        ok_btn.setText(tr("btn.ok"))
    cancel_btn = box.button(QDialogButtonBox.StandardButton.Cancel)
    if cancel_btn is not None:
        cancel_btn.setText(tr("btn.cancel"))


# 公开别名：后续从 _legacy 拆出去的对话框（memorial / settings / picker）
# 请直接使用公开名，逐步淘汰带下划线的旧名。
make_button_box = _make_button_box
retranslate_button_box = _retranslate_button_box


# ===================== 语言联动 Mixin =====================
class RetranslatableDialog:
    """
    让对话框自动跟随 i18n 语言切换的 mixin。

    ---- 子类契约 ----
    1. 继承顺序：``class Foo(RetranslatableDialog, QDialog)``。
       本 mixin 必须放在 QObject 派生类**之前**；否则 MRO 走不到本
       mixin 的 ``__init__``，监听不会被挂载。

    2. 构造末尾**显式**调用一次 ``self.retranslate_ui()``：
       本 mixin 在 ``__init__`` 里挂载监听，但不会主动触发首次填充
       （挂载时子类控件尚未创建）。首屏文案由子类自己负责。

    3. 实现 ``retranslate_ui()``：刷新所有依赖 ``tr()`` 的静态文本。
       **不得**修改任何用户输入状态（勾选、数值、选中项）。

    ---- 生命周期 ----
    - 挂载：``__init__`` 时把 ``self.retranslate_ui`` 注册到 i18n 监听。
    - 卸载：``done()`` 被重写为"先卸载再 super"；同时连接
      ``QObject.destroyed`` 做兜底（覆盖 ``deleteLater`` 等不经过
      ``done`` 的销毁路径）。两者都调用幂等的
      ``_detach_language_listener``，重复调用安全。
    """

    # 类级默认值，仅为可读性；实例化后立即被 __init__ 覆盖。
    _retranslate_cb: Optional[Callable[[str], None]] = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cb = self.retranslate_ui
        self._retranslate_cb = cb
        on_language_changed(cb)
        try:
            self.destroyed.connect(self._detach_language_listener)
        except Exception:
            # 理论上 QObject 一定有 destroyed；防御性 try 避免因信号连接
            # 失败导致对话框整体构造失败。此时监听仍已挂载，done() 会
            # 在正常关闭路径兜底卸载。
            logger.exception("连接 destroyed 信号失败，仅依赖 done() 卸载")

    def _detach_language_listener(self, _obj=None):
        """注销语言监听。幂等：重复调用 / 已销毁时是 no-op。"""
        cb = getattr(self, "_retranslate_cb", None)
        if cb is None:
            return
        off_language_changed(cb)
        self._retranslate_cb = None

    def done(self, r):
        # exec() 正常结束的必经之路（accept / reject / close 都走这里）
        self._detach_language_listener()
        super().done(r)

    def retranslate_ui(self):
        """子类必须实现。默认实现显式抛错，避免漏实现被静默吞掉。"""
        raise NotImplementedError(
            f"{type(self).__name__} 必须实现 retranslate_ui()")