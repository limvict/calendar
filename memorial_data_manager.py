# coding: utf-8
"""
纪念日数据备份 / 恢复管理。

职责：
- 把 config 中的 memorial_days 导出为 JSON 文件（backup）
- 从 JSON 文件导入 memorial_days 覆盖当前配置（restore）
- 恢复后广播 MEMORIAL_CHANGED，并显式触发一次"当日检查"

边界：
- 不负责提醒调度逻辑本身（归 ReminderManager）；
- 不负责配置文件读写（落盘走 ConfigManager）；
- 与 event_bus 解耦：只 publish，不 subscribe。
"""
import json
from datetime import datetime

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QFileDialog

from i18n import tr
from config import ConfigManager, get_logger
from dialogs import msg_info, msg_error
from event_bus import event_bus, EventType
from memorial import normalize_memorial

logger = get_logger()

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
        raw = self.config.get("memorial_days", []) or []
        if not isinstance(raw, list):
            logger.warning(
                f"memorial_days 类型异常（{type(raw).__name__}），按空列表导出")
            raw = []

        default_name = (
            f"memorial_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        path, _ = QFileDialog.getSaveFileName(
            self.parent, tr("backup.dialog_title"), default_name,
            "JSON (*.json)")
        if not path:
            return

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
            msg_error(self.parent, tr("msg.error"),
                      tr("backup.failed").format(error=e))
            return

        logger.info(f"纪念日已备份到 {path}，共 {len(raw)} 条")
        msg_info(self.parent, tr("msg.success"),
                 tr("backup.success").format(count=len(raw)))

    # ------------------------------------------------------------------ #
    # 恢复
    # ------------------------------------------------------------------ #
    def restore(self):
        path, _ = QFileDialog.getOpenFileName(
            self.parent, tr("backup.dialog_restore_title"), "",
            "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"读取备份文件失败: {e}")
            msg_error(self.parent, tr("msg.error"),
                      tr("backup.read_failed").format(error=e))
            return

        # 兼容两种格式：
        #   {"version":1, "memorial_days":[...]}   ← 本模块导出的格式
        #   [...]                                  ← 用户手动导出的裸 list
        if isinstance(data, list):
            mem_list = data
        elif (isinstance(data, dict)
              and isinstance(data.get("memorial_days"), list)):
            mem_list = data["memorial_days"]
        else:
            msg_error(self.parent, tr("msg.error"),
                      tr("backup.format_error"))
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

        self.config.set("memorial_days", normalized, save=False)
        self.config.flush()

        # 用 payload 显式携带 check_today，让 main 侧订阅者统一决定
        # "是否立刻做当日提醒检查"；不再同时 publish + 直调 reminder_mgr，
        # 避免同一动作触发两次 reschedule 互相覆盖。
        event_bus.publish(EventType.MEMORIAL_CHANGED, check_today=True)

        tail = (tr("backup.restore_skipped").format(count=skipped)
                if skipped else "")
        logger.info(f"纪念日已从 {path} 恢复，共 {len(normalized)} 条{tail}")
        msg_info(self.parent, tr("msg.success"),
                 tr("backup.restore_success").format(
                     count=len(normalized), tail=tail))
