# coding: utf-8
"""
向后兼容层。

原先 utils.py 承担了「农历转换 + 纪念日 + 平台初始化」三块职责，
现拆分为：
  - lunar.py    ：农历 / 节假日 / 公农历互转
  - memorial.py ：纪念日归一化、匹配、下次日期

本文件保留原 utils.py 的所有对外符号，其他模块的 `from utils import X`
和 `from utils import *` 都能继续工作，无需改动 import。
"""
import sys
import ctypes

from config import get_logger

logger=get_logger()

# ===================== 平台级副作用 =====================
# 放在这里而不是 lunar.py：utils 是本工程所有模块的公共入口，
# 能保证 DPI 感知 / AppUserModelID 在任何 Qt 窗口创建前执行一次。
if sys.platform == "win32":
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception as e:
        logger.warning(f"DPI感知设置失败: {e}")
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "desktop.lunar.calendar.v3"
        )
    except Exception as e:
        logger.warning(f"设置AppUserModelID失败: {e}")


# ===================== 配置初始化工具 =====================
def init_config_defaults(cfg):
    """
    Bug 13：原实现每个默认值都用 save=True 触发一次 save_debounced，
    首次启动时会连续调度 5 次定时器。这里统一 save=False，末尾 flush 一次。

    修复 6：显式校验 memorial_cfg 必须是 dict。
    """
    if not isinstance(cfg.get("memorial_cfg"), dict):
        cfg.set("memorial_cfg", {}, save=False)
    mem_defaults = {
        "enable_remind": True,
        "remind_start_hour": 8,
        "remind_end_hour": 22,
        "sound_enable": True,
        "last_remind_date": "",
    }
    for key, default_val in mem_defaults.items():
        if cfg.get_nested("memorial_cfg", key) is None:
            cfg.set_nested("memorial_cfg", key, default_val, save=False)
    cfg.save_debounced()


# ===================== 向后兼容导出 =====================
from lunar import *      # noqa: E402,F401,F403
from memorial import *   # noqa: E402,F401,F403