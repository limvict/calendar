# coding: utf-8
"""
语言包。key 使用 "模块.用途" 命名，避免扁平化冲突。
缺失 key 的兜底逻辑见 i18n.tr：优先当前语言 → zh_CN → 返回 key。
"""

ZH_CN = {
    # ---- 通用 ----
    "app.title": "桌面农历日历",
    "btn.ok": "确定",
    "btn.cancel": "取消",
    "btn.today": "今天",
    "btn.add": "新增",
    "btn.edit": "编辑选中",
    "btn.delete": "删除选中",
    "btn.all_enable": "全部启用",
    "btn.all_disable": "全部禁用",
    "btn.export": "导出配置",
    "btn.import": "导入配置",
    "btn.manage_memorial": "纪念日管理",
    "btn.pick_month": "跳转到月份",

    # ---- 设置 ----
    "setting.title": "设置",
    "setting.general": "通用设置",
    "setting.autostart": "Windows开机自启",
    "setting.topmost": "窗口置顶",
    "setting.memorial_remind": "启用纪念日提醒",
    "setting.memorial_sound": "提醒时播放提示音",
    "setting.opacity": "窗口透明度：",
    "setting.data": "数据管理",
    "setting.export": "导出配置",
    "setting.import": "导入配置",
    "setting.memorial_mgr": "纪念日管理",
    "setting.language": "语言 / Language",
    "setting.year_label": "年：",
    "setting.month_label": "月：",

    # ---- 纪念日 ----
    "memorial.title_new": "新增/编辑纪念日",
    "memorial.title_manage": "纪念日管理",
    "memorial.name": "名称",
    "memorial.name_placeholder": "纪念日名称（如：生日）",
    "memorial.solar": "公历日期",
    "memorial.lunar": "农历日期",
    "memorial.leap": "闰月（仅农历生效）",
    "memorial.repeat": "重复周期",
    "memorial.repeat_year": "每年重复",
    "memorial.repeat_month": "每月重复",
    "memorial.repeat_week": "每周重复",
    "memorial.month": "月份",
    "memorial.day": "日期/星期",
    "memorial.advance": "提前几天提醒(0=当天提醒)",
    "memorial.enabled": "启用该纪念日提醒",
    "memorial.remind_title": "纪念日提醒",
    "memorial.remind_heading": "今日纪念日提醒",
    "memorial.remind_ok": "知道了",
    "memorial.confirm_delete": "确定删除这条纪念日？",
    "memorial.weekday_suffix": "  (1=周一, 7=周日)",
    "memorial.default_name": "未命名纪念日",

    # ---- 纪念日表单校验 ----
    "memorial.warn_solar_day": "{month}月没有{day}日，请输入 1~{max_day} 之间的日期",
    "memorial.warn_lunar_day_max": "农历日期最大为 30 日（农历每月最多 30 天）",
    "memorial.warn_lunar_day_max_short": "农历日期最大为 30 日",
    "memorial.warn_leap_rare": (
        "闰月纪念日仅在对应闰月出现的年份显示。\n"
        "若该闰月间隔超过 5 年，个别年份可能不提醒。\n"
        "是否继续？"
    ),
    "memorial.warn_day_overflow": (
        "每月 {day} 日在部分月份不存在，"
        "届时将自动按该月最后一天提醒。\n是否继续？"
    ),

    # ---- 纪念日管理 ----
    "memorial.manage.select_first": "请先选中一条纪念日",
    "memorial.manage.empty": "暂无纪念日",
    "memorial.manage.confirm_delete_title": "确认删除",
    "memorial.manage.confirm_enable_all": "确定将所有纪念日【启用提醒】？",
    "memorial.manage.confirm_disable_all": "确定将所有纪念日【禁用提醒】？",
    "memorial.manage.repeat_prefix_year": "每年",
    "memorial.manage.repeat_prefix_month": "每月",
    "memorial.manage.repeat_prefix_week": "每周",
    "memorial.manage.status_enabled": "✅启用",
    "memorial.manage.status_disabled": "❌禁用",
    "memorial.manage.type_solar": "公历",
    "memorial.manage.type_lunar": "农历",
    "memorial.manage.leap_prefix": "闰",
    "memorial.manage.advance_fmt": "提前{advance}天提醒",
    "memorial.manage.week_fmt": "周{week}",
    "memorial.manage.date_fmt": "{month}月{day}日",

    # ---- 星期短名（1=周一 ... 7=周日）----
    "weekday.short.1": "一",
    "weekday.short.2": "二",
    "weekday.short.3": "三",
    "weekday.short.4": "四",
    "weekday.short.5": "五",
    "weekday.short.6": "六",
    "weekday.short.7": "日",

    # ---- 提醒命中文本 ----
    "memorial.remind.hit_fmt": "{name}，还有{days}天",
    "memorial.remind.hit_fmt_one": "{name}，还有1天",  

    # ---- 提示 / 错误 ----
    "msg.hint": "提示",
    "msg.error": "错误",
    "msg.success": "成功",
    "msg.name_empty": "名称不能为空",
    "msg.confirm": "确认",

    # ---- 配置导入/导出 ----
    "msg.export_title": "导出配置",
    "msg.export_success": "配置已导出",
    "msg.export_failed": "导出失败\n{error}",
    "msg.import_title": "导入配置",
    "msg.import_success": '配置已载入，点"确定"后生效',
    "msg.import_format_error": "导入失败，文件格式错误\n{error}",
    "msg.save_failed": "保存失败\n{error}",

    # ---- 纪念日备份/恢复 ----
    "backup.dialog_title": "备份纪念日数据",
    "backup.dialog_restore_title": "恢复纪念日数据",
    "backup.success": "已备份 {count} 条纪念日",
    "backup.failed": "备份失败\n{error}",
    "backup.restore_success": "已恢复 {count} 条纪念日{tail}",
    "backup.restore_skipped": "（跳过 {count} 条无效数据）",
    "backup.read_failed": "读取备份文件失败\n{error}",
    "backup.format_error": "文件格式错误：未找到 memorial_days 字段",

    # ---- 依赖 ----
    "dep.missing_title": "依赖缺失",
    "dep.missing_cnlunar": "cnlunar未安装，农历、节气功能不可用",
    "dep.missing_chinese_cal": "chinese_calendar未安装，本地节假日判断不可用",
    "dep.install_hint": "pip install cnlunar chinese_calendar",

    # ---- 主窗口 ----
    "cal.title_format": "{year}年{month}月",
    "info.solar_term": "节气",
    "info.festival": "节日",
    "info.memorial": "纪念日",
    "info.no_cnlunar": "农历库未安装，详情不可用",
    "info.lunar_unavailable": "暂无农历详情",
    "info.no_events": "今日无节日 / 纪念日",

    # ---- 托盘 ----
    "tray.show": "恢复窗口",
    "tray.topmost": "窗口置顶",
    "tray.backup": "备份纪念日数据",
    "tray.restore": "恢复纪念日数据",
    "tray.settings": "设置",
    "tray.quit": "完全退出",

    # ---- 上下文菜单 ----
    "ctxmenu.minimize": "最小化到托盘",
    "ctxmenu.backup": "备份纪念日数据",
    "ctxmenu.restore": "恢复纪念日数据",
    "ctxmenu.settings": "设置",
    "ctxmenu.quit": "完全退出",

    # ---- 开机自启 ----
    "autostart.windows_only": "开机自启仅支持Windows",
    "autostart.enabled": "✅ 已开启开机自启",
    "autostart.disabled": "✅ 已关闭开机自启",
    "autostart.permission_error": "注册表权限不足，请尝试以管理员运行程序",
    "autostart.failed": "设置开机自启失败：{error}",
    "autostart.window_title_hint": "提示",
    "autostart.window_title_success": "成功",
    "autostart.window_title_error": "错误",
    "autostart.window_title_permission": "权限错误",
    
    #-----除夕/班-----
    "cell.new_year_eve": "除夕",
    "cell.leap_prefix": "闰",
    "cell.workday_tag": "班",
}

EN_US = {
    "app.title": "Desktop Lunar Calendar",
    "btn.ok": "OK",
    "btn.cancel": "Cancel",
    "btn.today": "Today",
    "btn.add": "Add",
    "btn.edit": "Edit",
    "btn.delete": "Delete",
    "btn.all_enable": "Enable all",
    "btn.all_disable": "Disable all",
    "btn.export": "Export config",
    "btn.import": "Import config",
    "btn.manage_memorial": "Manage memorials",
    "btn.pick_month": "Go to month",

    "setting.title": "Settings",
    "setting.general": "General",
    "setting.autostart": "Start with Windows",
    "setting.topmost": "Always on top",
    "setting.memorial_remind": "Enable memorial reminders",
    "setting.memorial_sound": "Play sound on reminder",
    "setting.opacity": "Opacity: ",
    "setting.data": "Data",
    "setting.export": "Export config",
    "setting.import": "Import config",
    "setting.memorial_mgr": "Manage memorials",
    "setting.language": "Language / 语言",
    "setting.year_label": "Year:",
    "setting.month_label": "Month:",

    "memorial.title_new": "New / Edit Memorial",
    "memorial.title_manage": "Memorial Manager",
    "memorial.name": "Name",
    "memorial.name_placeholder": "e.g. Birthday",
    "memorial.solar": "Solar",
    "memorial.lunar": "Lunar",
    "memorial.leap": "Leap month (lunar only)",
    "memorial.repeat": "Repeat",
    "memorial.repeat_year": "Yearly",
    "memorial.repeat_month": "Monthly",
    "memorial.repeat_week": "Weekly",
    "memorial.month": "Month",
    "memorial.day": "Day / Weekday",
    "memorial.advance": "Remind N days ahead (0 = same day)",
    "memorial.enabled": "Enabled",
    "memorial.remind_title": "Memorial Reminder",
    "memorial.remind_heading": "Today's Memorial Reminders",
    "memorial.remind_ok": "Got it",
    "memorial.confirm_delete": "Delete this memorial?",
    "memorial.weekday_suffix": "  (1=Mon, 7=Sun)",
    "memorial.default_name": "Untitled Memorial",

    "memorial.warn_solar_day": "{month} has no day {day}. Please enter 1~{max_day}.",
    "memorial.warn_lunar_day_max": "Max lunar day is 30.",
    "memorial.warn_lunar_day_max_short": "Max lunar day is 30.",
    "memorial.warn_leap_rare": (
        "A leap-month memorial only fires in years with the matching leap month.\n"
        "If the gap exceeds 5 years, some years may be skipped.\n"
        "Continue?"
    ),
    "memorial.warn_day_overflow": (
        "Day {day} does not exist in some months; it will fall back to the "
        "last day of the month.\nContinue?"
    ),

    "memorial.manage.select_first": "Please select a memorial first",
    "memorial.manage.empty": "No memorials",
    "memorial.manage.confirm_delete_title": "Confirm delete",
    "memorial.manage.confirm_enable_all": "Enable reminders for all memorials?",
    "memorial.manage.confirm_disable_all": "Disable reminders for all memorials?",
    "memorial.manage.repeat_prefix_year": "Yearly",
    "memorial.manage.repeat_prefix_month": "Monthly",
    "memorial.manage.repeat_prefix_week": "Weekly",
    "memorial.manage.status_enabled": "✅On",
    "memorial.manage.status_disabled": "❌Off",
    "memorial.manage.type_solar": "Solar",
    "memorial.manage.type_lunar": "Lunar",
    "memorial.manage.leap_prefix": "Leap ",
    "memorial.manage.advance_fmt": "{advance}d ahead",
    "memorial.manage.week_fmt": "Wk{week}",
    "memorial.manage.date_fmt": "{month}/{day}",

    "weekday.short.1": "Mon",
    "weekday.short.2": "Tue",
    "weekday.short.3": "Wed",
    "weekday.short.4": "Thu",
    "weekday.short.5": "Fri",
    "weekday.short.6": "Sat",
    "weekday.short.7": "Sun",

    "memorial.remind.hit_fmt": "{name}, {days} days away",
    "memorial.remind.hit_fmt_one": "{name}, 1 day away",

    "msg.hint": "Notice",
    "msg.error": "Error",
    "msg.success": "Success",
    "msg.name_empty": "Name cannot be empty",
    "msg.confirm": "Confirm",

    "msg.export_title": "Export config",
    "msg.export_success": "Config exported",
    "msg.export_failed": "Export failed\n{error}",
    "msg.import_title": "Import config",
    "msg.import_success": 'Config loaded. Click "OK" to apply.',
    "msg.import_format_error": "Import failed: bad file format\n{error}",
    "msg.save_failed": "Save failed\n{error}",

    "backup.dialog_title": "Backup memorials",
    "backup.dialog_restore_title": "Restore memorials",
    "backup.success": "Backed up {count} memorials",
    "backup.failed": "Backup failed\n{error}",
    "backup.restore_success": "Restored {count} memorials{tail}",
    "backup.restore_skipped": " (skipped {count} invalid)",
    "backup.read_failed": "Failed to read backup\n{error}",
    "backup.format_error": "Bad format: memorial_days field not found",

    "dep.missing_title": "Missing Dependencies",
    "dep.missing_cnlunar": "cnlunar not installed: lunar / solar terms unavailable",
    "dep.missing_chinese_cal": "chinese_calendar not installed: local holiday data unavailable",
    "dep.install_hint": "pip install cnlunar chinese_calendar",

    "cal.title_format": "{year}-{month}",
    "info.solar_term": "Term",
    "info.festival": "Festival",
    "info.memorial": "Memorial",
    "info.no_cnlunar": "Lunar library not installed, details unavailable",
    "info.lunar_unavailable": "No lunar details",
    "info.no_events": "No events today",

    "tray.show": "Show window",
    "tray.topmost": "Always on top",
    "tray.backup": "Backup memorials",
    "tray.restore": "Restore memorials",
    "tray.settings": "Settings",
    "tray.quit": "Quit",

    "ctxmenu.minimize": "Minimize to tray",
    "ctxmenu.backup": "Backup memorials",
    "ctxmenu.restore": "Restore memorials",
    "ctxmenu.settings": "Settings",
    "ctxmenu.quit": "Quit",

    "autostart.windows_only": "Auto-start is only supported on Windows",
    "autostart.enabled": "✅ Auto-start enabled",
    "autostart.disabled": "✅ Auto-start disabled",
    "autostart.permission_error": "Registry access denied. Try running as administrator.",
    "autostart.failed": "Failed to set auto-start: {error}",
    "autostart.window_title_hint": "Notice",
    "autostart.window_title_success": "Success",
    "autostart.window_title_error": "Error",
    "autostart.window_title_permission": "Permission Error",
    
    
    "cell.new_year_eve": "NYE",
    "cell.leap_prefix": "Leap ",
    "cell.workday_tag": "W",
}

LANGUAGES = {
    "zh_CN": {"name": "简体中文", "table": ZH_CN},
    "en_US": {"name": "English",  "table": EN_US},
}