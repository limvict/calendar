# coding: utf-8
import json
import os


def test_config_crud_and_deepcopy(isolated_config):
    mod, cm = isolated_config

    cm.set("a", 1, save=False)
    cm.set_nested("memorial_cfg", "enable_remind", False, save=False)
    cm.update_nested("memorial_cfg", sound_enable=False, save=False)

    snap = cm.snapshot()
    snap["memorial_cfg"]["enable_remind"] = True

    assert cm.get("a") == 1
    assert cm.get_nested("memorial_cfg", "enable_remind") is False
    assert cm.get_nested("memorial_cfg", "sound_enable") is False


def test_flush_writes_json_atomically(isolated_config):
    mod, cm = isolated_config

    cm.set("x", 1, save=False)
    cm.flush()

    path = mod.get_config_path()
    assert os.path.exists(path)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["x"] == 1
    assert data["config_version"] == mod.CONFIG_VERSION



def test_migrate_fixes_bad_types(isolated_config):
    mod, cm = isolated_config

    cm.replace_all(
        {
            "memorial_days": None,
            "memorial_cfg": None,
        },
        save=False,
    )

    assert isinstance(cm.get("memorial_days"), list)
    assert isinstance(cm.get("memorial_cfg"), dict)
    assert cm.get("memorial_cfg")["enable_remind"] is True
    

def test_init_config_defaults_tolerates_plain_object():
    """
    【P2-4】传入无 _migrate / save_debounced 的对象时不应抛异常。
    """
    import utils as utils_mod

    class Bare:
        pass

    utils_mod.init_config_defaults(Bare())   # 不抛即通过
    utils_mod.init_config_defaults(None)     # None 也不抛
    
    
    
def test_init_config_defaults_delegates_to_migrate(isolated_config):
    """
    【P2-4】init_config_defaults 应委托 _migrate，
    不再自己维护一份默认值表；两者补齐的字段必须一致。
    """
    import utils as utils_mod

    mod, cm = isolated_config

    # 绕过 replace_all（它会自动跑 _migrate），直接造"迁移前"状态
    cm._cfg = {"memorial_cfg": {}}
    utils_mod.init_config_defaults(cm)

    # _migrate 补齐的所有字段都应存在
    assert cm.get("memorial_days") == []
    assert cm.get("topmost") is False
    assert cm.get("opacity") == 0.92
    assert cm.get("theme") is None
    assert cm.get("config_version") == mod.CONFIG_VERSION
    assert cm.get("memorial_cfg")["enable_remind"] is True
    assert cm.get("memorial_cfg")["remind_start_hour"] == 8
    assert cm.get("memorial_cfg")["remind_end_hour"] == 22
    assert cm.get("memorial_cfg")["sound_enable"] is True
    assert cm.get("memorial_cfg")["last_remind_date"] == ""

