# coding: utf-8
"""
纪念日数据备份 / 恢复管理。

职责：
- 把 config 中的 memorial_days 导出为 JSON 文件（backup）
- 从 JSON 文件导入 memorial_days 覆盖当前配置（restore）
- 恢复后广播 MEMORIAL_CHANGED，并由本模块显式触发一次"当日检查"

与其他模块的边界：
- 不负责提醒调度逻辑本身；调度归 ReminderManager。
- 不负责配置文件读写；落盘走 ConfigManager。
- 与 event_bus 的解耦方式：只 publish，不 subscribe。
"""
import json
import os
from datetime import datetime

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QFileDialog

from config import ConfigManager, get_logger
from dialogs import msg_info, msg_error
from event_bus import event_bus, EventType
from memorial import normalize_memorial

logger = get_logger()

# 备份文件格式版本，便于未来迁移
BACKUP_FORMAT_VERSION = 1


class MemorialDataManager(QObject):
    """纪念日数据的备份与恢复。"""

    def __init__(self, parent_widget, config: ConfigManager):
        super().__init__(parent_widget)
        self.parent = parent_widget
        self.config = config

    # ------------------------------------------------------------------ #
    # 备份
    # ------------------------------------------------------------------ #
    def backup(self):
        """把当前 memorial_days 导出为 JSON 文件。"""
        raw = self.config.get("memorial_days", []) or []
        if not isinstance(raw, list):
            logger.warning(
                f"memorial_days 类型异常（{type(raw).__name__}），按空列表导出"
            )
            raw = []

        default_name = (
            f"memorial_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        path, _ = QFileDialog.getSaveFileName(
            self.parent, "备份纪念日数据", default_name, "JSON文件 (*.json)"
        )
        if not path:
            return  # 用户取消

        payload = {
            "version": BACKUP_FORMAT_VERSION,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "memorial_days": raw,
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"备份纪念日失败: {e}")
            msg_error(self.parent, "失败", f"备份失败\n{e}")
            return

        logger.info(f"纪念日已备份到 {path}，共 {len(raw)} 条")
        msg_info(self.parent, "成功", f"已备份 {len(raw)} 条纪念日")

    # ------------------------------------------------------------------ #
    # 恢复
    # ------------------------------------------------------------------ #
    def restore(self):
        """从 JSON 文件导入 memorial_days，覆盖当前配置。"""
        path, _ = QFileDialog.getOpenFileName(
            self.parent, "恢复纪念日数据", "", "JSON文件 (*.json)"
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"读取备份文件失败: {e}")
            msg_error(self.parent, "失败", f"读取备份文件失败\n{e}")
            return

        # 兼容两种格式：
        #   {"version":1, "memorial_days":[...]}   ← 本模块导出的格式
        #   [...]                                  ← 用户手动导出的裸 list
        if isinstance(data, list):
            mem_list = data
        elif isinstance(data, dict) and isinstance(data.get("memorial_days"), list):
            mem_list = data["memorial_days"]
        else:
            msg_error(self.parent, "失败", "文件格式错误：未找到 memorial_days 字段")
            return

        # 逐条归一化：坏数据跳过而不是整体失败
        normalized = []
        skipped = 0
        for i, item in enumerate(mem_list):
            if not isinstance(item, dict):
                logger.warning(f"跳过第 {i} 条（非 dict）：{item!r}")
                skipped += 1
                continue
            try:
                normalized.append(normalize_memorial(item))
            except Exception as e:
                logger.warning(f"第 {i} 条纪念日归一化失败，已跳过: {e}")
                skipped += 1

        # 覆盖式写回。save=False + flush 保证在此刻同步落盘，
        # 避免防抖定时器未触发就退出导致数据丢失。
        self.config.set("memorial_days", normalized, save=False)
        self.config.flush()

        # 广播：main 侧订阅者会刷新日历 + 静默重排提醒（check_today=False）
        event_bus.publish(EventType.MEMORIAL_CHANGED)

        # 显式动作 → 需要立即检查今日命中（见 main._on_memorial_changed 注释）
        self._trigger_today_check()

        tail = f"（跳过 {skipped} 条无效数据）" if skipped else ""
        logger.info(f"纪念日已从 {path} 恢复，共 {len(normalized)} 条{tail}")
        msg_info(self.parent, "成功", f"已恢复 {len(normalized)} 条纪念日{tail}")

    # ------------------------------------------------------------------ #
    # 内部：触发一次"当日检查"
    # ------------------------------------------------------------------ #
    def _trigger_today_check(self):
        """
        让 ReminderManager 立即执行 check_memorial(force=True, check_today=True)。

        背景：MEMORIAL_CHANGED 的订阅者（main._on_memorial_changed）走的是
        "静默重排"（check_today=False），不弹当日提醒。用户从文件恢复数据
        属于显式动作，理应立刻看到今日命中结果 —— 这里补上那一次显式调用。

        用 getattr 而非直接引用 self.parent.reminder_mgr，避免子组件
        对主窗口属性的强耦合（测试/单测时可注入）。
        """
        mgr = getattr(self.parent, "reminder_mgr", None)
        if mgr is None:
            logger.debug("reminder_mgr 尚未初始化，跳过当日检查")
            return
        try:
            mgr.reschedule(force=True, check_today=True)
        except Exception as e:
            logger.warning(f"恢复后触发当日检查失败: {e}")