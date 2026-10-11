
---

# docs/API.md

```markdown
# API 参考

> 本文档按模块列出对外公共接口。带 `_` 前缀的成员为内部实现，不保证向后兼容。

- [config](#config)
- [constants](#constants)
- [calendar_widget](#calendar_widget)
- [lunar](#lunar)
- [memorial](#memorial)
- [event_bus](#event_bus)
- [holiday_manager](#holiday_manager)
- [network](#network)
- [reminder_manager](#reminder_manager)
- [dialogs](#dialogs)
- [memorial_data_manager](#memorial_data_manager)
- [tray_manager](#tray_manager)
- [style_manager](#style_manager)
- [window_state_manager](#window_state_manager)
- [sound_manager](#sound_manager)
- [utils](#utils)

---

## config

### 常量

| 名称 | 值 | 说明 |
| --- | --- | --- |
| `CONFIG_VERSION` | `2` | 当前配置版本 |
| `CONFIG_SAVE_DEBOUNCE_MS` | `500` | 防抖保存延迟 |
| `LOG_MAX_BYTES` | `5 MB` | 单个日志文件上限 |
| `LOG_BACKUP_COUNT` | `3` | 日志滚动份数 |
| `APP_LOGGER_NAME` | `"MyCalendarApp"` | 日志器名称 |

### 模块级函数

#### `get_logger() -> logging.Logger`

返回应用命名 logger（懒初始化、线程安全）。日志文件默认位于
`<数据目录>/calendar_log.txt`，超过 `LOG_MAX_BYTES` 自动滚动。

#### `log_exception(msg: str) -> None`

在异常上下文中打印 traceback，否则只打 `ERROR` 日志。
避免 `NoneType: None` 噪音。

#### `get_resource_path(relative_path: str) -> str`

获取资源文件绝对路径，兼容 PyInstaller 打包环境（`sys._MEIPASS`）。

```python
icon = get_resource_path("assets/app.ico")