# coding: utf-8
import dialogs as dialogs_mod
from dialogs import AddMemorialDialog
from memorial import REPEAT_WEEK, REPEAT_YEAR


def test_add_memorial_week_forces_solar(qapp):
    dlg = AddMemorialDialog()

    dlg.radio_lunar.setChecked(True)
    idx = dlg.combo_repeat.findData(REPEAT_WEEK)
    dlg.combo_repeat.setCurrentIndex(idx)
    dlg.spin_day.setValue(3)

    data = dlg.get_data()

    assert data["type"] == "solar"
    assert data["repeat_type"] == REPEAT_WEEK
    assert data["day"] == 3


def test_accept_rejects_invalid_solar_date(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(
        dialogs_mod,
        "msg_warn",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    dlg = AddMemorialDialog()
    dlg.edit_name.setText("测试")
    dlg.radio_solar.setChecked(True)

    idx = dlg.combo_repeat.findData(REPEAT_YEAR)
    dlg.combo_repeat.setCurrentIndex(idx)

    dlg.spin_month.setValue(2)
    dlg.spin_day.setValue(30)

    dlg._on_accept()

    assert calls
    assert dlg.result() == 0