# 桌面农历日历

基于 **PyQt6** 的 Windows 桌面农历日历，支持公历 / 农历、二十四节气、法定节假日、周末调休（班）、纪念日提醒、主题配色、系统托盘等功能。

---

## 功能

- 📅 农历 + 公历双历显示，节气、传统节日、公历节日标注
- 🎉 法定节假日 / 调休「班」标记，优先使用网络数据，失败时回退本地库
- 🎂 纪念日提醒：支持公历 / 农历、每年 / 每月 / 每周重复、闰月、提前 N 天提醒
- 🎨 莫兰迪主题，圆角无边框窗口，透明度 / 置顶可调
- 🖥️ 系统托盘常驻，双击恢复窗口
- ⚙️ 设置持久化，支持配置导入 / 导出
- 🔔 提醒音效（Windows 原生 `winsound`）

---

## 环境要求

- **Python** ≥ 3.9
- **操作系统**：Windows 10/11（其它平台部分功能降级，如音效、开机自启）

---

## 安装

```bash
git clone https://github.com/limvict/calendar.git
cd calendar

# 建议使用虚拟环境
python -m venv .venv
.venv\Scripts\activate       # Windows PowerShell

pip install -r requirements.txt
```

---

## 运行

```bash
python main.py
```

首次启动会自动在 `%APPDATA%\MyCalendarApp\` 下生成日志与配置。

---

## 配置说明

用户配置保存在：

```
%APPDATA%\MyCalendarApp\config.json
```

> ⚠️ `config.json` 含个人纪念日、窗口位置等信息，**不纳入版本控制**（已在 `.gitignore` 中排除）。

如果需要参考配置结构，见仓库中的 `config.example.json`（如有）。

---

## 开发与测试

安装测试依赖：

```bash
pip install -r requirements-dev.txt
```

运行测试：

```bash
pytest
```

---

## 依赖

| 包 | 用途 |
|---|---|
| `PyQt6` | GUI 框架 |
| `cnlunar` | 农历 / 节气计算 |
| `chinesecalendar` | 法定节假日 / 调休判断（本地回退） |

---

## 目录结构

```
calendar/
├── main.py                    # 程序入口，主窗口
├── calendar_widget.py         # 自定义日历控件
├── config.py                  # 配置管理器单例
├── constants.py               # 常量与默认主题
├── dialogs.py                 # 各类弹窗
├── event_bus.py               # 全局事件总线
├── holiday_manager.py         # 节假日数据管理
├── lunar.py                   # 农历 / 节假日互转
├── memorial.py                # 纪念日归一化与匹配
├── memorial_data_manager.py   # 纪念日备份 / 恢复
├── network.py                 # 网络节假日拉取
├── reminder_manager.py        # 提醒调度
├── sound_manager.py           # 音效播放
├── style_manager.py           # 主题样式
├── tray_manager.py            # 系统托盘
├── utils.py                   # 向后兼容层
├── window_state_manager.py    # 窗口状态（拖拽 / 置顶 / 透明度）
├── assets/                    # 图标与音效
└── tests/                     # 单元测试
```

---

## 许可证

本项目仅供个人使用与学习交流。