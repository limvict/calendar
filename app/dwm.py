# coding: utf-8
"""
Windows DWM 修复：为无边框窗口消除黑边。

非 Windows 平台或调用失败时静默返回——DWM 修复是"锦上添花"，
失败不应影响窗口显示。
"""
import ctypes
import sys


def apply_dwm_fix(window) -> None:
    """对 Windows 窗口应用 DwmExtendFrameIntoClientArea(-1,-1,-1,-1)。

    失败静默：非 Windows 平台直接返回；Windows 上 API 调用异常
    也仅忽略，让窗口按默认样式显示。
    """
    if sys.platform != "win32":
        return
    try:
        dwmapi = ctypes.windll.dwmapi

        class MARGINS(ctypes.Structure):
            _fields_ = [
                ("cxLeftWidth", ctypes.c_int),
                ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int),
                ("cyBottomHeight", ctypes.c_int)]

        margins = MARGINS(-1, -1, -1, -1)
        hwnd = int(window.winId())
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
    except Exception:
        pass