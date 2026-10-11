# coding: utf-8
"""
设置对话框的打开与应用。

拆出 main.py 中 open_settings_dialog / _apply_settings 的完整流程。
所有对主窗口状态的操作都通过传入的 window 访问，本模块不直接
持有全局管理器引用，方便测试时替换 window 的 stub。

【顺序约束】apply_settings 里 config 落盘 → window_state 生效 →
事件广播 → 语言切换 → 自启处理的顺序是有意为之，不要"整理"。
"""
from PyQt6.QtWidgets import QDialog

from config import config, get_logger
from i18n import set_language
from dialogs import SettingDialog
from event_bus import event_bus, EventType

from .auto_start import check_auto_start, apply_auto_start

logger = get_logger()


def open_settings_dialog(window) -> None:
    # 进入对话框前取快照：既用于初始化控件，也用于"取消"时还原
    snapshot = config.snapshot()
    orig_opacity = float(snapshot.get("opacity", 0.92))
    orig_topmost = bool(snapshot.get("topmost", False))

    mem_cfg = snapshot.get("memorial_cfg") or {}
    mem_remind = bool(mem_cfg.get("enable_remind", True))
    mem_sound = bool(mem_cfg.get("sound_enable", True))

    auto_start = check_auto_start()
    dlg = SettingDialog(
        snapshot, auto_start,
        orig_topmost, orig_opacity,
        mem_remind, mem_sound, window)
    dlg.preview_opacity_changed.connect(window.window_state.set_opacity)
    dlg.preview_topmost_changed.connect(window.window_state.set_topmost)

    if dlg.exec() == QDialog.DialogCode.Accepted:
        apply_settings(window, dlg)
    else:
        # 取消：还原预览效果。全局 config 从未被对话框改动，无需回滚
        window.window_state.set_opacity(orig_opacity)
        window.window_state.set_topmost(orig_topmost)
        window.tray_mgr.update_topmost_check(orig_topmost)


def apply_settings(window, dlg: SettingDialog) -> None:
    new_cfg = dlg.cfg
    new_lang = dlg.get_language()
    lang_changed = new_lang != config.get("language", "zh_CN")
    new_cfg["language"] = new_lang

    new_cfg["topmost"] = bool(dlg.get_topmost_status())
    new_cfg["opacity"] = float(dlg.get_opacity())
    new_cfg["memorial_days"] = dlg.get_memorial_list()

    mem_cfg = dict(new_cfg.get("memorial_cfg") or {})
    mem_cfg["enable_remind"] = bool(dlg.get_mem_remind())
    mem_cfg["sound_enable"] = bool(dlg.get_mem_sound())
    new_cfg["memorial_cfg"] = mem_cfg

    config.replace_all(new_cfg, save=False)
    config.flush()

    final_opacity = dlg.get_opacity()
    final_topmost = dlg.get_topmost_status()
    window.window_state.set_opacity(final_opacity)
    window.window_state.set_topmost(final_topmost)

    event_bus.publish(EventType.MEMORIAL_CHANGED, check_today=True)
    event_bus.publish(EventType.SETTINGS_CHANGED)
    window.tray_mgr.update_topmost_check(final_topmost)
    if lang_changed:
        set_language(new_lang)

    want_auto = dlg.get_auto_start_status()
    if want_auto != check_auto_start():
        apply_auto_start(window, want_auto)