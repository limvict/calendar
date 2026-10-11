# coding: utf-8
"""
应用层模块集合。

依赖方向（单向，无环）：
  dwm / auto_start / dependency_check / info_panel（叶子模块）
  event_wiring → event_bus
  settings_controller → dialogs / auto_start / event_bus / config
  main_window → 以上全部

main_window 是唯一持有 DragCalendarWidget 定义的模块，
main.py（项目根目录）只做入口装配。
"""