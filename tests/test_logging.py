# coding: utf-8
"""
日志级别契约测试。

锁定的约定（见项目 README / 日志矩阵）：

  ┌────────────────────────────────────────────────────────────┐
  │ debug     已知降级路径（缺依赖、库覆盖范围外、单点失败）      │
  │ warning   算法跑通但结果异常（参数错 / 数据缺 / 窗口落空）    │
  │ exception 真 bug（去重或不去重，取决于调用频率）              │
  └────────────────────────────────────────────────────────────┘

这些测试的目的不是验证业务逻辑（那属于 test_memorial.py），
而是防止后人「随手把手滑把 debug 改成 log_exception」导致日志刷屏。

注意：
  * 所有用例都 monkeypatch 掉真实库依赖，环境里装/不装 cnlunar 都能跑
  * Qt 相关的用例需要 PyQt6，未安装会自动 skip
  * 假设 config.logger 会向 root 传播日志（标准配置）
  * ensure_debug_logger / qapp 由 tests/conftest.py 提供
"""
import logging
from datetime import date

import pytest

import lunar
import memorial
from lunar import _get_lunar_cached, lunar_to_gregorian
from memorial import (
    get_next_memorial_date, REPEAT_MONTH, REPEAT_YEAR,
)
from _helpers import called_names


# ===================== 公共工具 =====================

def _levels_for(caplog, substring: str):
    """取出所有 message 里含 substring 的日志记录的 levelno 列表。"""
    return [
        r.levelno for r in caplog.records
        if substring in r.getMessage()
    ]


# ===================== lunar.py =====================

class TestLunarModuleLogging:
    """lunar._get_lunar_cached 的失败必须走 debug，不能是 exception。"""

    def test_get_lunar_cached_failure_logs_debug(self, monkeypatch, caplog):
        """
        cnlunar.Lunar 抛异常时：
          - 返回值 None
          - 日志级别 = DEBUG
          - 只打一条（lru_cache 不会重复进入函数体）
        """
        monkeypatch.setattr(lunar, "HAS_CHNCAL", True)

        class FakeCnlunar:
            @staticmethod
            def Lunar(*args, **kwargs):
                raise ValueError("模拟 cnlunar 内部错误")

        monkeypatch.setattr(lunar, "cnlunar", FakeCnlunar)
        _get_lunar_cached.cache_clear()

        with caplog.at_level(logging.DEBUG):
            result = _get_lunar_cached(2100, 6, 1)  # 冷门日期，避免污染其它测试

        assert result is None
        levels = _levels_for(caplog, "农历转换降级")
        assert levels == [logging.DEBUG], (
            f"期望恰好 1 条 DEBUG，实际 {levels}。"
            "若这里是 ERROR/WARNING，说明有人把降级改回了 log_exception，"
            "会在 lunar_to_gregorian 的循环里刷出几百条 traceback。"
        )

    def test_get_lunar_cached_second_call_hits_cache(self, monkeypatch, caplog):
        """lru_cache 命中时不重复进入函数体 → 不重复打日志。"""
        monkeypatch.setattr(lunar, "HAS_CHNCAL", True)

        class FakeCnlunar:
            @staticmethod
            def Lunar(*args, **kwargs):
                raise ValueError("模拟 cnlunar 内部错误")

        monkeypatch.setattr(lunar, "cnlunar", FakeCnlunar)
        _get_lunar_cached.cache_clear()

        with caplog.at_level(logging.DEBUG):
            _get_lunar_cached(2101, 7, 1)
            _get_lunar_cached(2101, 7, 1)  # 缓存命中
            _get_lunar_cached(2101, 7, 1)

        levels = _levels_for(caplog, "农历转换降级")
        assert levels == [logging.DEBUG], (
            "lru_cache 命中后不应重复进入函数体，也就不应重复打日志"
        )


# ===================== memorial.py =====================

class TestMemorialModuleLogging:
    """memorial.py 农历分支的 5 个出口，级别必须精确。"""

    # ---------- 每月 · 农历 ----------

    def test_monthly_lunar_no_cnlunar_logs_debug(self, monkeypatch, caplog):
        """缺 cnlunar → debug，不是 warning（启动时已经 warn 过一次）。"""
        monkeypatch.setattr(memorial, "HAS_CHNCAL", False)
        mem = {"type": "lunar", "repeat_type": REPEAT_MONTH, "day": 15}

        with caplog.at_level(logging.DEBUG):
            result = get_next_memorial_date(mem, date(2025, 6, 1))

        assert result is None
        levels = _levels_for(caplog, "cnlunar 未安装")
        assert levels == [logging.DEBUG], (
            f"期望 DEBUG，实际 {levels}。"
            "缺库是用户选择，不是异常；用 warning 会在每次刷新界面时刷屏。"
        )

    def test_monthly_lunar_unknown_base_logs_warning(self, monkeypatch, caplog):
        """基准日查不出农历 → warning（算法无法推进，需要人关注）。"""
        monkeypatch.setattr(memorial, "HAS_CHNCAL", True)
        monkeypatch.setattr(memorial, "get_lunar_by_datetime", lambda dt: None)
        mem = {"type": "lunar", "repeat_type": REPEAT_MONTH, "day": 15}

        with caplog.at_level(logging.DEBUG):
            result = get_next_memorial_date(mem, date(2025, 6, 1))

        assert result is None
        levels = _levels_for(caplog, "无农历信息")
        assert levels == [logging.WARNING], (
            f"期望 WARNING，实际 {levels}。"
            "静默返回 None 会被误认为「真的没有下一次」。"
        )

    def test_monthly_lunar_window_miss_logs_warning(self, monkeypatch, caplog):
        """6 个农历月窗口内未命中 → warning（day=30 遇上连续小月等）。"""
        monkeypatch.setattr(memorial, "HAS_CHNCAL", True)

        class FakeLunar:
            lunarYear = 2025
            lunarMonth = 1

        monkeypatch.setattr(
            memorial, "get_lunar_by_datetime", lambda dt: FakeLunar()
        )
        monkeypatch.setattr(
            memorial, "lunar_to_gregorian", lambda *a, **kw: None
        )
        mem = {"type": "lunar", "repeat_type": REPEAT_MONTH, "day": 30}

        with caplog.at_level(logging.DEBUG):
            result = get_next_memorial_date(mem, date(2025, 6, 1))

        assert result is None
        levels = _levels_for(caplog, "6 个农历月内未找到")
        assert levels == [logging.WARNING], (
            f"期望 WARNING，实际 {levels}"
        )

    # ---------- 每年 · 农历 ----------

    def test_yearly_lunar_no_cnlunar_logs_debug(self, monkeypatch, caplog):
        """缺 cnlunar → debug。"""
        monkeypatch.setattr(memorial, "HAS_CHNCAL", False)
        mem = {"type": "lunar", "repeat_type": REPEAT_YEAR, "month": 1, "day": 1}

        with caplog.at_level(logging.DEBUG):
            result = get_next_memorial_date(mem, date(2025, 6, 1))

        assert result is None
        levels = _levels_for(caplog, "cnlunar 未安装")
        assert levels == [logging.DEBUG], f"期望 DEBUG，实际 {levels}"

    def test_yearly_lunar_window_miss_logs_warning(self, monkeypatch, caplog):
        """3 年窗口全部落空 → warning（等价于该纪念日永远不再触发）。"""
        monkeypatch.setattr(memorial, "HAS_CHNCAL", True)
        monkeypatch.setattr(
            memorial, "lunar_to_gregorian", lambda *a, **kw: None
        )
        mem = {"type": "lunar", "repeat_type": REPEAT_YEAR,
               "month": 12, "day": 30}

        with caplog.at_level(logging.DEBUG):
            result = get_next_memorial_date(mem, date(2025, 1, 1))

        assert result is None
        levels = _levels_for(caplog, "三年内未找到")
        assert levels == [logging.WARNING], f"期望 WARNING，实际 {levels}"

    # ---------- 正常路径必须静默 ----------

    def test_successful_path_logs_nothing(self, monkeypatch, caplog):
        """命中成功时静默返回 date，不产生任何日志。"""
        monkeypatch.setattr(memorial, "HAS_CHNCAL", True)

        class FakeLunar:
            lunarYear = 2025
            lunarMonth = 1

        monkeypatch.setattr(
            memorial, "get_lunar_by_datetime", lambda dt: FakeLunar()
        )
        monkeypatch.setattr(
            memorial, "lunar_to_gregorian",
            lambda ly, lm, d, is_leap: date(2025, 6, 15),
        )
        mem = {"type": "lunar", "repeat_type": REPEAT_MONTH, "day": 15}

        with caplog.at_level(logging.DEBUG):
            result = get_next_memorial_date(mem, date(2025, 6, 1))

        assert result == date(2025, 6, 15)
        # 可能 normalize_memorial 会打 warning（若参数缺失），这里只检查
        # 与"农历"相关的日志不应出现
        lunar_logs = [
            r for r in caplog.records
            if "农历" in r.getMessage() and "未找到" in r.getMessage()
        ]
        assert lunar_logs == [], (
            f"成功路径不应打任何农历降级日志，实际："
            f"{[r.getMessage() for r in lunar_logs]}"
        )


# ===================== calendar_widget.py =====================

class TestCalendarWidgetDedupe:
    """_log_exception_once 按 key 去重，避免 42 个单元格刷屏。"""

    def test_same_key_reported_once(self, qapp, caplog):
        """
        同一 key：
          - 第一次调用 → 上报
          - 后续调用     → 静默
        """
        from calendar_widget import LunarCalendarWidget
        widget = LunarCalendarWidget(None, {}, [])

        with caplog.at_level(logging.DEBUG):
            widget._log_exception_once("k1", "第一次错误")
            widget._log_exception_once("k1", "第二次错误")  # 去重
            widget._log_exception_once("k1", "第三次错误")  # 去重

        msgs = [r.getMessage() for r in caplog.records]
        assert any("第一次错误" in m for m in msgs), "第一次必须上报"
        assert not any("第二次错误" in m for m in msgs), "第二次必须静默"
        assert not any("第三次错误" in m for m in msgs), "第三次必须静默"

    def test_different_keys_reported_separately(self, qapp, caplog):
        """不同 key 各自第一次都上报。"""
        from calendar_widget import LunarCalendarWidget
        widget = LunarCalendarWidget(None, {}, [])

        with caplog.at_level(logging.DEBUG):
            widget._log_exception_once("paintCell", "paint 失败")
            widget._log_exception_once("get_lunar_cell_text", "文本失败")
            widget._log_exception_once("paintCell", "paint 失败·再次")
            widget._log_exception_once("get_lunar_cell_text", "文本失败·再次")

        msgs = [r.getMessage() for r in caplog.records]
        assert any("paint 失败" in m and "再次" not in m for m in msgs)
        assert any("文本失败" in m and "再次" not in m for m in msgs)
        assert not any("再次" in m for m in msgs), (
            "第二次调用同一 key 必须静默"
        )

    def test_reported_errors_initialized_empty(self, qapp):
        """构造后 _reported_errors 必须存在且为空。"""
        from calendar_widget import LunarCalendarWidget
        widget = LunarCalendarWidget(None, {}, [])
        assert hasattr(widget, "_reported_errors")
        assert widget._reported_errors == set()

    def test_dedupe_is_per_widget_instance(self, qapp, caplog):
        """去重状态绑定在 widget 实例上，不同实例互不影响。"""
        from calendar_widget import LunarCalendarWidget
        w1 = LunarCalendarWidget(None, {}, [])
        w2 = LunarCalendarWidget(None, {}, [])

        with caplog.at_level(logging.DEBUG):
            w1._log_exception_once("k1", "来自 w1")
            w2._log_exception_once("k1", "来自 w2")  # 不同实例，应上报

        msgs = [r.getMessage() for r in caplog.records]
        assert any("来自 w1" in m for m in msgs)
        assert any("来自 w2" in m for m in msgs)


# ===================== 元测试：防止 log_exception 滥用 =====================

class TestLoggingContract:
    """
    把「哪些字符串不该出现在 log_exception 里」也做成断言。

    思路：这些函数的调用频率是逐单元格（一次重绘 42 次），一旦有人
    把它们改回 log_exception，日志会在真实环境里炸。这里通过 AST
    静态检查「是否真正调用了 log_exception」，属于保险丝。

    为什么不用 inspect.getsource + `in` 字符串匹配：
      * 注释里提到 log_exception（比如"若用 log_exception 会刷屏"）
        会被误判为违规 —— 我们用 AST 避免了这个问题。
    """

    def test_lunar_py_does_not_use_log_exception_in_hot_path(self):
        """
        lunar._get_lunar_cached 必须用 logger.debug，
        不能出现 log_exception（会被 lunar_to_gregorian 循环调用数百次）。
        """
        called = called_names(lunar._get_lunar_cached)
        assert "log_exception" not in called, (
            "_get_lunar_cached 里实际调用了 log_exception —— 它被 "
            "lunar_to_gregorian 在最多 ~420 天的循环里反复调用，"
            "必须用 logger.debug 降级。"
        )
        # 反向验证：debug 必须存在，否则说明降级日志被删了
        assert "debug" in called, (
            "_get_lunar_cached 应该调用 logger.debug 记录降级，"
            "现在连 debug 都没有了。"
        )

    def test_memorial_hot_paths_use_debug_not_exception(self):
        """
        memorial 农历分支的「缺 cnlunar」出口必须是 debug，
        不能是 log_exception / logger.warning。
        """
        called = called_names(get_next_memorial_date)
        assert "log_exception" not in called, (
            "get_next_memorial_date 中不应使用 log_exception —— "
            "它是查询路径，被 GUI 频繁调用，应使用 debug / warning。"
        )