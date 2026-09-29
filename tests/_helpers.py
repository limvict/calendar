# coding: utf-8
"""
测试辅助类与工具函数。

不依赖 pytest —— 可以像普通 Python 模块一样 import / 复用。
"""
import ast
import inspect
import textwrap
from datetime import date


class FakeLunar:
    """
    假的农历对象，只暴露业务代码用到的属性。

    业务代码访问的属性：
      * lunarYear / lunarMonth / lunarDay
      * isLunarLeapMonth
    """

    def __init__(self, lunar_year: int, lunar_month: int, lunar_day: int,
                 is_leap: bool = False):
        self.lunarYear = lunar_year
        self.lunarMonth = lunar_month
        self.lunarDay = lunar_day
        self.isLunarLeapMonth = is_leap


class FakeLunarEnv:
    """
    假的农历环境：把指定公历日期和 FakeLunar 对象绑定。

    同时维护正向（公历→农历）和反向（农历→公历）两张表，
    使 get_lunar_by_datetime 和 lunar_to_gregorian 都能被完整 mock。
    """

    def __init__(self):
        self._forward: dict = {}   # (y, m, d) -> FakeLunar
        self._reverse: dict = {}   # (ly, lm, ld, is_leap) -> date

    def add(self, gregorian: date, lunar: FakeLunar) -> None:
        """
        注册一条映射。

        :param gregorian: 公历日期
        :param lunar:     FakeLunar 实例
        """
        self._forward[(gregorian.year, gregorian.month, gregorian.day)] = lunar
        self._reverse[
            (lunar.lunarYear, lunar.lunarMonth,
             lunar.lunarDay, bool(lunar.isLunarLeapMonth))
        ] = gregorian

    def get(self, key):
        """正向查询：(y, m, d) → FakeLunar 或 None。"""
        return self._forward.get(tuple(int(x) for x in key))

    def get_gregorian(self, ly, lm, ld, is_leap=False):
        """反向查询：(农历年, 月, 日, 是否闰月) → date 或 None。"""
        return self._reverse.get((int(ly), int(lm), int(ld), bool(is_leap)))


def called_names(func) -> set:
    """
    返回函数体内实际被调用的函数名集合（不含注释、不含字符串）。

    用 AST 而不是字符串匹配，原因：
      * 注释里提到 log_exception 不应误报
      * 字符串字面量里提到 log_exception 不应误报
      * 只有真正被调用（ast.Call）才算

    收集两类：
      * 裸调用  foo(...)      → "foo"
      * 属性调用 obj.bar(...) → "bar"（只记 attr）
    """
    src = textwrap.dedent(inspect.getsource(func))
    tree = ast.parse(src)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                names.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                names.add(fn.attr)
    return names