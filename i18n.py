# coding: utf-8
"""
轻量级 i18n。不用 Qt Linguist（需要 .ts/.qm 工具链），
直接字典查表 + 格式化，便于随代码一起 review。

语言切换：默认"重启后生效"；需要热更新的组件可通过
on_language_changed() 注册回调，在 set_language 时同步收到通知。
UI 组件的自动挂载/卸载由 dialogs.RetranslatableDialog mixin 负责，
主窗口则显式在 __init__ / quit_app 处注册与注销。

线程模型：_current_lang / _listeners 预期仅在主线程读写。若从工作
线程调用 set_language，需调用方自行保证"当前无 UI 组件正在响应"
——Qt 控件只能在主线程被操作。
"""
from typing import Callable, List, Optional

from config import get_logger
from translations import LANGUAGES, ZH_CN

logger = get_logger()

_DEFAULT_LANG = "zh_CN"
_current_lang: str = _DEFAULT_LANG
_listeners: List[Callable[[str], None]] = []


def set_language(lang: Optional[str]) -> None:
    """
    设置当前语言。未知语言（含 None）回退到默认语言并记录 warning。

    语言真正变化时，依次调用已注册的监听者；单个监听者抛异常不影响
    其它监听者（与 event_bus 的隔离策略一致）。

    相同语言重复设置会短路返回，不触发监听者：避免"用户在设置里
    选了与当前相同的语言并点确定"时做无谓的 UI 刷新。
    """
    global _current_lang
    if lang in LANGUAGES:
        new_lang = lang
    else:
        logger.warning(f"未知语言 {lang!r}，回退到 {_DEFAULT_LANG}")
        new_lang = _DEFAULT_LANG

    if new_lang == _current_lang:
        return
    _current_lang = new_lang

    for cb in list(_listeners):
        try:
            cb(new_lang)
        except Exception:
            logger.exception(f"语言切换监听者 {cb!r} 抛异常，已隔离")


def get_language() -> str:
    return _current_lang


def on_language_changed(cb: Callable[[str], None]) -> None:
    """
    注册语言切换监听者。同一函数重复注册不会重复入列——保证
    "构造 → 挂载 → 语言切换 → 关闭 → 再构造"的循环里，监听表不会
    随构造次数增长。

    无弱引用：主窗口与对话框的生命周期由调用方显式管理
    （off_language_changed / RetranslatableDialog.done）。若将来
    引入超长生命周期的短命订阅者，应改用 weakref.WeakMethod。
    """
    if cb not in _listeners:
        _listeners.append(cb)


def off_language_changed(cb: Callable[[str], None]) -> None:
    """注销语言切换监听者；未注册时不报错（幂等）。"""
    try:
        _listeners.remove(cb)
    except ValueError:
        pass


def has_key(key: str, lang: Optional[str] = None) -> bool:
    """key 在指定语言（默认当前）或 zh_CN 中存在，即视为可翻译。"""
    target = lang if lang is not None else _current_lang
    if target in LANGUAGES and key in LANGUAGES[target]["table"]:
        return True
    return key in ZH_CN


def get_language_display_name(lang: Optional[str] = None) -> str:
    """返回语言的显示名；未知语言返回 code 本身。"""
    target = lang if lang is not None else _current_lang
    meta = LANGUAGES.get(target)
    return meta["name"] if meta else str(target)


def tr(key: str, **kwargs) -> str:
    """
    翻译。三级回退：当前语言 → zh_CN → key 本身。
    返回 key 本身是刻意的：漏翻时肉眼可见，而不是静默显示空白。
    """
    table = LANGUAGES.get(_current_lang, {}).get("table", {})
    text = table.get(key)
    if text is None:
        text = ZH_CN.get(key)
    if text is None:
        logger.debug(f"翻译缺失 key={key!r} lang={_current_lang!r}")
        return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            logger.warning(f"翻译格式化失败 key={key!r} kwargs={kwargs!r}")
            return text
    return text


def available_languages() -> list[tuple[str, str]]:
    """返回 [(code, 显示名), ...]，供下拉框使用。"""
    return [(code, meta["name"]) for code, meta in LANGUAGES.items()]


def validate_keys(*, strict: bool = False) -> dict:
    """
    检查各非默认语言相对 zh_CN 的 key 一致性。

    返回 {code: {"missing": [...], "extra": [...]}}：
      - missing：该语言缺失但 zh_CN 有的 key（tr 会回退到 zh_CN）
      - extra：该语言有但 zh_CN 没有的 key（永远用不到，多为拼写错误）

    strict=True 时，只要存在不一致就抛 KeyError；用于测试 / CI。
    """
    base_keys = set(ZH_CN)
    report: dict = {}
    for code, meta in LANGUAGES.items():
        if code == _DEFAULT_LANG:
            continue
        keys = set(meta.get("table") or {})
        missing = sorted(base_keys - keys)
        extra = sorted(keys - base_keys)
        if missing or extra:
            report[code] = {"missing": missing, "extra": extra}
            logger.warning(
                f"语言 {code!r} 与 zh_CN 的 key 不一致："
                f"missing={len(missing)} extra={len(extra)}")
    if strict and report:
        raise KeyError(f"语言 key 不一致：{report}")
    return report


if __name__ == "__main__":
    # python i18n.py 可做一次 key 一致性自检
    import json
    rep = validate_keys(strict=False)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if rep
          else "OK: 所有语言的 key 一致")