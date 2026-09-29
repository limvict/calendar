# coding: utf-8
import os
import json
from PyQt6.QtCore import QObject, QDate, QDateTime, Qt, QStandardPaths
from PyQt6.QtWidgets import QMessageBox, QFileDialog
from config import ConfigManager, get_logger
from utils import normalize_memorial, REPEAT_WEEK
from event_bus import event_bus, EventType

logger=get_logger()

class MemorialDataManager(QObject):
    """纪念日数据管理：备份、恢复、导入导出、去重合并"""

    def __init__(self, parent, config: ConfigManager):
        super().__init__(parent)
        self.parent = parent
        self.config = config

    def backup(self):
        """备份纪念日数据+配置到本地JSON文件"""
        doc_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        default_name = f"日历纪念日备份_{QDate.currentDate().toString('yyyyMMdd')}.json"
        file_path, _ = QFileDialog.getSaveFileName(
            self.parent, "备份纪念日数据",
            os.path.join(doc_dir, default_name),
            "JSON文件 (*.json)"
        )
        if not file_path:
            return False

        export_data = {
            "version": 2,
            "backup_time": QDateTime.currentDateTime().toString(Qt.DateFormat.ISODate),
            "memorial_days": self.config.get("memorial_days", []),
            "memorial_cfg": self.config.get("memorial_cfg", {})
        }

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self.parent, "备份成功", f"数据已保存到：\n{file_path}")
            return True
        except Exception as e:
            logger.error(f"备份失败: {e}")
            QMessageBox.critical(self.parent, "备份失败", f"写入文件出错：{str(e)}")
            return False

    def restore(self):
        """从JSON文件恢复纪念日数据，支持替换/合并两种模式"""
        file_path, _ = QFileDialog.getOpenFileName(
            self.parent, "恢复纪念日数据", "", "JSON文件 (*.json)"
        )
        if not file_path:
            return False

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 版本校验：上限 2，下限 1
            version = data.get("version", 1)
            if not isinstance(version, int) or version < 1:
                raise ValueError("备份文件版本无效")
            if version > 2:
                raise ValueError("备份文件版本过高，请升级程序后再尝试")

            raw_list = data.get("memorial_days", [])
            if not isinstance(raw_list, list):
                raise ValueError("文件格式无效：纪念日数据不是列表")

            # 数据标准化与校验
            valid_list = [
                normalize_memorial(m) for m in raw_list
                if isinstance(m, dict) and "name" in m
            ]
            if not valid_list:
                QMessageBox.warning(self.parent, "恢复失败", "文件中无有效纪念日数据")
                return False

            # 自定义按钮，避免Yes/No语义混淆
            msg_box = QMessageBox(self.parent)
            msg_box.setWindowTitle("选择恢复方式")
            msg_box.setText("请选择数据恢复方式：")
            btn_replace = msg_box.addButton("替换(清空现有)", QMessageBox.ButtonRole.ActionRole)
            btn_merge = msg_box.addButton("合并(保留现有)", QMessageBox.ButtonRole.ActionRole)
            btn_cancel = msg_box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(btn_merge)
            msg_box.exec()

            clicked = msg_box.clickedButton()
            if clicked == btn_cancel:
                return False

            # 恢复纪念日列表
            if clicked == btn_replace:
                self.config.set("memorial_days", valid_list)
                # 替换模式下同步恢复提醒配置
                if "memorial_cfg" in data and isinstance(data["memorial_cfg"], dict):
                    self.config.set("memorial_cfg", data["memorial_cfg"])
            else:
                self._merge_data(valid_list)

            self.config.save_debounced()
            event_bus.publish(EventType.MEMORIAL_CHANGED)

            # MEMORIAL_CHANGED 走的是 check_today=False 的静默重排；
            # 恢复数据是用户显式动作，这里单独触发一次当日检查
            try:
                self.parent.reminder_mgr.reschedule(force=True, check_today=True)
            except Exception as e:
                logger.warning(f"恢复后重排提醒失败: {e}")

            QMessageBox.information(
                self.parent, "恢复成功",
                f"已导入 {len(valid_list)} 条纪念日数据"
            )
            return True

        except json.JSONDecodeError:
            QMessageBox.critical(self.parent, "恢复失败", "文件不是有效的JSON格式")
        except ValueError as e:
            QMessageBox.critical(self.parent, "恢复失败", str(e))
        except Exception as e:
            logger.error(f"恢复失败: {e}")
            QMessageBox.critical(self.parent, "恢复失败", f"读取文件出错：{str(e)}")
        return False

    @staticmethod
    def _dedup_key(m: dict):
        """
        构造去重键。
        - REPEAT_WEEK：month 无意义，用 0 占位
        - 其他：包含 month/day/type/isleap
        """
        m = normalize_memorial(m)
        if m["repeat_type"] == REPEAT_WEEK:
            month = 0
        else:
            month = m.get("month", 0)
        return (
            m["name"],
            m["repeat_type"],
            m["type"],
            month,
            m["day"],
            bool(m.get("isleap", False)),
        )

    def _merge_data(self, valid_list: list):
        """合并数据：保留现有数据，追加新数据并自动去重"""
        # 创建副本，避免直接修改config中的引用对象
        existing = list(self.config.get("memorial_days", []))
        exist_keys = set()

        for m in existing:
            exist_keys.add(self._dedup_key(m))

        for m in valid_list:
            key = self._dedup_key(m)
            if key not in exist_keys:
                existing.append(m)
                exist_keys.add(key)

        self.config.set("memorial_days", existing)