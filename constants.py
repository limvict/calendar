# coding: utf-8
# 主题配置 - 莫兰迪柔和配色
import copy
import json
import os
from config import get_resource_path,get_logger
logger = get_logger()

# 你的默认主题常量
DEFAULT_THEME = {
    "window_width": 440,
    "window_height": 480,
    "font_family": "微软雅黑,SimHei,sans-serif",
    "font_size": 13,
    "week_header_font_size": 12,
    "bg_main": "#F7F3ED",
    "border_color": "#D8D2C5",
    "clock_text_color": "#4A4A4A",
    "date_text_color": "#5A5A5A",
    "lunar_clock_color": "#777777",
    "corner_radius": 20,
    "shadow_size": 0,
    "shadow_color": "#00000040",
    "calendar_header_bg": "#A7B8A1",
    "calendar_header_text": "#000000",
    "weekend_header_red": "#C96068",
    "select_bg": "#B8AAA0",
    "select_text_color": "#ffffff",
    "today_bg": "#7C947E",
    "today_text_color": "#ffffff",
    "festival_red": "#C96068",
    "workday_orange": "#D47026",
    "memorial_orange": "#D47026",
    "normal_cell_bg": "#F9F6F1",
    "normal_num_color": "#555555",
    "normal_lunar_color": "#808080",

    # ===== 【Item 2】相邻月单元格 =====
    "adjacent_cell_bg": "#E9E6E1",
    "adjacent_text_color": "#BBBBBB",

    # ===== 【Item 2】单元格尺寸 =====
    # 注意：不与上面的 window 圆角 "corner_radius" 冲突
    "cell_corner_radius": 8,
    "dot_size": 6,
    "tag_size": 14,
    "tag_bg": "#222222",
    "tag_text_color": "#FFFFFF",
}


def load_theme(theme_path: str = None) -> dict:
    """
    加载主题配置：优先读取外部文件，加载失败则返回默认主题。
    """
    # 【P2-3】deepcopy 替代浅拷贝：当前扁平字典无所谓，
    # 但未来若引入嵌套主题（如 {"colors": {...}}），浅拷贝会埋坑。
    theme = copy.deepcopy(DEFAULT_THEME)

    if theme_path is None:
        try:
            theme_path = get_resource_path("theme.json")
        except Exception as e:
            logger.warning(f"获取默认主题路径失败，使用默认主题：{e}")
            return theme
    if not theme_path or not os.path.exists(theme_path):
        logger.warning(f"主题文件 {theme_path!r} 不存在，使用默认主题")
        return theme
    try:
        with open(theme_path, "r", encoding="utf-8") as f:
            custom_theme = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"主题文件读取或解析失败，使用默认主题：{e}")
        return theme
    except Exception as e:
        logger.warning(f"加载主题文件时发生未知错误，使用默认主题：{e}")
        return theme
    if not isinstance(custom_theme, dict):
        logger.warning(
            f"主题文件内容不是 JSON 对象（实际为 {type(custom_theme).__name__}），"
            f"使用默认主题"
        )
        return theme
    unknown_keys = set(custom_theme) - set(DEFAULT_THEME)
    if unknown_keys:
        logger.warning(
            f"主题文件中存在未知配置项，已忽略：{', '.join(sorted(unknown_keys))}"
        )
    for key, value in custom_theme.items():
        if key not in DEFAULT_THEME:
            continue
        if value is None:
            logger.warning(f"主题配置项 {key!r} 为 None，已保留默认值")
            continue
        theme[key] = value
    return theme

# 农历传统节日（月,日）-> 名称，只对这些文字标红
LUNAR_FESTIVALS = {
    (1, 1): "春节", (1, 15): "元宵节", (2, 2): "龙抬头",
    (5, 5): "端午节", (7, 7): "七夕节", (7, 15): "中元节",
    (8, 15): "中秋节", (9, 9): "重阳节", (12, 8): "腊八节",
    (12, 23): "北方小年", (12, 24): "南方小年",
}

# 公历节日（正常灰色显示）
SOLAR_FESTIVALS = {
    (1, 1): "元旦", (3, 8): "妇女节", (3, 12): "植树节",
    (4, 1): "愚人节", (5, 1): "劳动节", (5, 4): "青年节",
    (6, 1): "儿童节", (7, 1): "建党节", (8, 1): "建军节",
    (9, 10): "教师节", (10, 1): "国庆节",
    (12, 24): "平安夜", (12, 25): "圣诞节",
}

# 节日名称归一化映射
FESTIVAL_NAME_MAP = {
    "元旦节": "元旦",
    "国际劳动节": "劳动节",
    "春节": "春节",
    "清明节": "清明节",
    "端午节": "端午节",
    "中秋节": "中秋节",
    "国庆节": "国庆节",
}

# 二十四节气
SOLAR_TERMS = [
    "小寒", "大寒", "立春", "雨水", "惊蛰", "春分",
    "清明", "谷雨", "立夏", "小满", "芒种", "夏至",
    "小暑", "大暑", "立秋", "处暑", "白露", "秋分",
    "寒露", "霜降", "立冬", "小雪", "大雪", "冬至",
]

# ===== 【修复 2】法定节日里需要标红的名称 =====
# 原实现 RED_TEXT_SET 只来自 LUNAR_FESTIVALS.values()，
# 导致「清明节」（不在农历传统节日表里）被当成灰色。
# 这里把全部法定节日名归一化后统一加入红字集合。
LEGAL_HOLIDAY_RED = {
    "元旦", "春节", "清明节", "劳动节",
    "端午节", "中秋节", "国庆节",
}

# 标红的节日集合（农历传统节日 ∪ 法定节日）
RED_TEXT_SET = set(LUNAR_FESTIVALS.values()) | LEGAL_HOLIDAY_RED

# 农历月份中文
MONTH_CN = ["", "正月", "二月", "三月", "四月", "五月", "六月",
            "七月", "八月", "九月", "十月", "冬月", "腊月"]

# 农历日期中文映射
NUM_CN_MAP = {
    "1": "初一", "2": "初二", "3": "初三", "4": "初四", "5": "初五",
    "6": "初六", "7": "初七", "8": "初八", "9": "初九", "10": "初十",
    "11": "十一", "12": "十二", "13": "十三", "14": "十四", "15": "十五",
    "16": "十六", "17": "十七", "18": "十八", "19": "十九", "20": "二十",
    "21": "廿一", "22": "廿二", "23": "廿三", "24": "廿四", "25": "廿五",
    "26": "廿六", "27": "廿七", "28": "廿八", "29": "廿九", "30": "三十",
}

# 预告提前天数
UPCOMING_REMIND_DAYS = 7