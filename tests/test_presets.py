"""Tests for bookwork.presets.

Always construct QSettings pointed at a temp ini file (never `default_
settings()`) so tests never read or write the real user's persistent
settings store.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

from bookwork.imposition import ImpositionParams
from bookwork.presets import delete_preset, list_preset_names, load_preset, save_preset


def _settings(tmp_path) -> QSettings:
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


def test_list_preset_names_empty_initially(qtbot, tmp_path):
    assert list_preset_names(_settings(tmp_path)) == []


def test_save_and_load_preset_round_trips_all_fields(qtbot, tmp_path):
    settings = _settings(tmp_path)
    params = ImpositionParams(
        signature_size_pages=8,
        sheet_width_pt=700.0,
        sheet_height_pt=500.0,
        margin_pt=12.5,
        gutter_pt=24.0,
        show_crop_marks=False,
        include_endpapers=True,
        separate_cover=False,
    )

    save_preset(settings, "My Preset", params)
    loaded = load_preset(_settings(tmp_path), "My Preset")  # fresh instance, same file

    assert loaded == params


def test_save_preset_appears_in_list_preset_names(qtbot, tmp_path):
    settings = _settings(tmp_path)
    save_preset(settings, "Zebra", ImpositionParams())
    save_preset(settings, "Alpha", ImpositionParams())

    assert list_preset_names(settings) == ["Alpha", "Zebra"]  # sorted


def test_save_preset_rejects_empty_name(qtbot, tmp_path):
    settings = _settings(tmp_path)
    try:
        save_preset(settings, "   ", ImpositionParams())
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an empty preset name")


def test_load_missing_preset_raises_key_error(qtbot, tmp_path):
    settings = _settings(tmp_path)
    try:
        load_preset(settings, "Does Not Exist")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for a missing preset")


def test_delete_preset_removes_it(qtbot, tmp_path):
    settings = _settings(tmp_path)
    save_preset(settings, "Temp", ImpositionParams())
    assert "Temp" in list_preset_names(settings)

    delete_preset(settings, "Temp")

    assert "Temp" not in list_preset_names(settings)


def test_save_preset_overwrites_existing_name(qtbot, tmp_path):
    settings = _settings(tmp_path)
    save_preset(settings, "Preset", ImpositionParams(signature_size_pages=4))
    save_preset(settings, "Preset", ImpositionParams(signature_size_pages=20))

    loaded = load_preset(settings, "Preset")
    assert loaded.signature_size_pages == 20
    assert list_preset_names(settings) == ["Preset"]  # not duplicated
