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