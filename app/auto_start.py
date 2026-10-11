# coding: utf-8
"""
Windows 开机自启（注册表 Run 键）。

非 Windows 平台 or winreg 不可用时：
  - check_auto_start() 恒返回 False；
  - apply_auto_start() 弹"仅支持 Windows"提示。
"""
import os
import sys

from PyQt6.QtWidgets import QMessageBox

from config import get_logger
from i18n import tr

# Windows 注册表（开机自启）；非 Windows 平台降级
try:
    import winreg
    HAS_WINREG = True
except ImportError:
    winreg = None
    HAS_WINREG = False

logger = get_logger()

_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_REG_KEY = "DesktopLunarCalendarV3"


def check_auto_start() -> bool:
    if sys.platform != "win32" or not HAS_WINREG:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as key:
            val, _ = winreg.QueryValueEx(key, _REG_KEY)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.warning(f"读取开机自启状态失败: {e}", exc_info=True)
        return False


def _build_cmd() -> str:
    """打包环境直接用 exe；源码环境显式拼接 python + script。"""
    if getattr(sys, "_MEIPASS", None):
        return f'"{sys.executable}"'
    script = os.path.abspath(sys.argv[0])
    if script.endswith(".py"):
        return f'"{sys.executable}" "{script}"'
    # python -m 或其它方式：退化为只记录 python，
    # 至少不会写成无效路径；用户可手动编辑注册表补全。
    return f'"{sys.executable}"'


def apply_auto_start(parent_widget, enable: bool) -> None:
    """写 / 删注册表 Run 键并弹提示。"""
    if sys.platform != "win32" or not HAS_WINREG:
        QMessageBox.information(
            parent_widget, tr("autostart.window_title_hint"),
            tr("autostart.windows_only"))
        return

    cmd = _build_cmd()
    try:
        # 必须带 KEY_SET_VALUE：后面要 SetValueEx / DeleteValue。
        # 只读权限（默认）会在第一次写入时抛 PermissionError。
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _REG_PATH, 0,
                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            if enable:
                winreg.SetValueEx(key, _REG_KEY, 0, winreg.REG_SZ, cmd)
                QMessageBox.information(
                    parent_widget, tr("autostart.window_title_success"),
                    tr("autostart.enabled"))
            else:
                try:
                    winreg.DeleteValue(key, _REG_KEY)
                except FileNotFoundError:
                    # 值本就不存在，视为"已关闭"，不报错
                    pass
                QMessageBox.information(
                    parent_widget, tr("autostart.window_title_success"),
                    tr("autostart.disabled"))
    except PermissionError:
        QMessageBox.critical(
            parent_widget, tr("autostart.window_title_permission"),
            tr("autostart.permission_error"))
    except FileNotFoundError:
        # Run 键整体不存在：极罕见（企业策略 / 精简系统裁剪过）。
        # 单独分支给出可定位的提示，而不是落进下面的"未知错误"。
        QMessageBox.critical(
            parent_widget, tr("autostart.window_title_error"),
            tr("autostart.failed").format(
                error=f"注册表路径不存在: HKCU\\{_REG_PATH}"))
    except Exception as e:
        QMessageBox.critical(
            parent_widget, tr("autostart.window_title_error"),
            tr("autostart.failed").format(error=e))