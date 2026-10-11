# 桌面农历日历（Desktop Lunar Calendar）

一个基于 **PyQt6** 的 Windows 桌面农历日历小工具。支持农历/节气/节日展示、
节假日调休标注、纪念日提醒、网络节假日自动同步、系统托盘、开机自启、
主题自定义与配置导入导出。

---

## 目录

- [功能特性](#功能特性)
- [运行环境](#运行环境)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [架构设计](#架构设计)
- [配置说明](#配置说明)
- [主题自定义](#主题自定义)
- [依赖降级策略](#依赖降级策略)
- [打包发布](#打包发布)
- [常见问题](#常见问题)
- [API 参考](#api-参考)

---

## 功能特性

| 功能 | 说明 |
| --- | --- |
| 📅 农历日历 | 农历日期、节气、传统节日、公历节日 |
| 🎉 节假日调休 | 网络数据优先，`chinese_calendar` 兜底，周末降级 |
| 🎂 纪念日 | 公历/农历、每年/每月/每周重复、提前 N 天提醒 |
| 🔔 提醒弹窗 | 支持自定义提醒时段（默认 8:00–22:00）与提示音 |
| 🌐 网络同步 | 多 CDN 降级拉取节假日数据，本地缓存 7 天 |
| 📌 系统托盘 | 最小化到托盘、双击恢复、置顶切换 |
| 🎨 主题 | `theme.json` 覆盖默认主题，热更新无需重启 |
| 💾 配置管理 | 原子落盘、防抖保存、导入/导出 JSON |
| 🚀 开机自启 | Windows 注册表 `Run` 键 |
| 📦 数据备份 | 纪念日独立备份/恢复（JSON） |
| 🖼️ 无边框窗口 | 可拖拽、透明度可调、位置记忆 |

---

## 运行环境

- **Python**：3.8+
- **操作系统**：Windows / macOS / Linux（托盘、音效、开机自启在 Windows 上功能完整）
- **必需依赖**：
  - `PyQt6 >= 6.4`

- **可选依赖**（缺失时自动降级）：
  - `cnlunar` — 农历 / 节气转换（缺失则日历只显示公历）
  - `chinese_calendar` — 本地节假日判断（缺失则只按周末判断）

---

## 快速开始

```bash
# 1. 安装依赖
pip install PyQt6 cnlunar chinese_calendar

# 2. 运行
python main.py


项目结构
.
├── main.py                    # 主入口：主窗口 + 跨模块调度
├── calendar_widget.py         # 自定义日历控件（农历/节日/纪念日渲染）
├── config.py                  # ConfigManager 单例 + 日志系统
├── constants.py               # 默认主题、节日表、布尔归一化
├── dialogs.py                 # 全部对话框
├── event_bus.py               # 发布-订阅事件总线
├── holiday_manager.py         # 节假日缓存 / 网络 / 刷新
├── lunar.py                   # 农历 / 节假日 / 公农历互转（含降级）
├── memorial.py                # 纪念日归一化 / 匹配 / 下次日期计算
├── memorial_data_manager.py   # 纪念日备份 / 恢复
├── network.py                 # 网络节假日拉取（多 CDN）
├── reminder_manager.py        # 纪念日提醒调度
├── sound_manager.py           # Windows 音效播放
├── style_manager.py           # UI 样式统一刷新
├── tray_manager.py            # 系统托盘
├── utils.py                   # 启动期配置默认值初始化
├── window_state_manager.py    # 拖拽 / 置顶 / 透明度 / 位置记忆
├── assets/                    # 图标、音效
└── theme.json                 # 可选自定义主题