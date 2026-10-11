# utils.py
REPEAT_YEAR = "year"
REPEAT_WEEK = "week"


def init_config_defaults(cfg):
    """
    确保配置补齐默认字段并触发一次防抖落盘。

    默认值语义唯一由 ConfigManager._migrate 定义；本函数只负责
    "委托 _migrate + 触发落盘"。

    线程安全：_migrate 内部持 self._lock，本函数不重复加锁。
    落盘用 save_debounced 而非 flush —— 启动阶段不应同步阻塞在
    磁盘 IO 上；退出路径由 quit_app 的 config.flush() 兜底。首次
    启动时配置文件尚不存在，需要这里把默认值写出去。

    get_logger 采用函数内延迟导入：本函数调用频率极低（启动一次），
    延迟导入可避免"import utils 即触发 ConfigManager 单例构造"，也
    杜绝将来 config ↔ utils 反向依赖时的循环导入。
    """
    if cfg is None:
        return

    from config import get_logger
    log = get_logger()

    # 鸭子类型：容忍测试里的 FakeCfg / mock 没有 _migrate；
    # 真实路径上若缺 _migrate，打 warning 避免静默不补默认值。
    migrate = getattr(cfg, "_migrate", None)
    if callable(migrate):
        migrate()
    else:
        log.warning(
            "init_config_defaults: cfg %r 缺少 _migrate，默认值未补齐",
            type(cfg).__name__)

    # 测试 mock 通常没有 save_debounced，属预期场景，仅 debug。
    save_debounced = getattr(cfg, "save_debounced", None)
    if callable(save_debounced):
        save_debounced()
    else:
        log.debug(
            "init_config_defaults: cfg %r 无 save_debounced，跳过首次落盘",
            type(cfg).__name__)