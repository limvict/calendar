# coding: utf-8
"""
启动时依赖检查。

用 weakref + QTimer.singleShot 延迟弹窗，避免：
  - 在窗口首次显示之前弹窗造成视觉突兀；
  - 定时器闭包强引用住主窗口，导致其生命周期被延长。
"""
import weakref

from PyQt6.QtCore import QTimer

from dialogs import msg_warn
from i18n import tr


def check_dependencies(
    parent_widget,
    has_cnlunar: bool,
    has_chinese_cal: bool,
    delay_ms: int = 100,
) -> None:
    """无缺失时静默；有缺失时延迟弹窗。"""
    warn_msgs = []
    if not has_cnlunar:
        warn_msgs.append(tr("dep.missing_cnlunar"))
    if not has_chinese_cal:
        warn_msgs.append(tr("dep.missing_chinese_cal"))
    if not warn_msgs:
        return

    ref = weakref.ref(parent_widget)

    def _fire():
        w = ref()
        if w is not None:
            _show_warning(w, warn_msgs)

    QTimer.singleShot(delay_ms, _fire)


def _show_warning(parent_widget, warn_msgs) -> None:
    msg_warn(
        parent_widget, tr("dep.missing_title"),
        "\n".join(warn_msgs) + "\n" + tr("dep.install_hint"))