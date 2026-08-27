# Bookwork — a PDF imposition tool for home book binding
# Copyright (C) 2026  Andrew McClain
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for bookwork.presets.

Always construct QSettings pointed at a temp ini file (never `default_
settings()`) so tests never read or write the real user's persistent
settings store.
"""

from __future__ import annotations

import dataclasses
import pathlib
import shutil

from PySide6.QtCore import QSettings

from bookwork.imposition import ImpositionParams
from bookwork.presets import _FIELDS, delete_preset, list_preset_names, load_preset, save_preset


def _settings(tmp_path) -> QSettings:
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


def _settings_read_fresh_from_disk(tmp_path) -> QSettings:
    """A QSettings that genuinely re-reads the ini from disk, the way a
    restarted app does.

    Constructing a second QSettings on the *same* path does not do this:
    QSettings keeps a per-path in-process cache and hands back the original
    typed values, which masks the fact that the ini stores everything as
    plain text. Copying to a path this process hasn't seen defeats that
    cache — without this, a preset that only loads correctly within the
    session that wrote it still passes.
    """
    source = tmp_path / "settings.ini"
    fresh = tmp_path / "settings_reread.ini"
    shutil.copyfile(source, fresh)
    return QSettings(str(fresh), QSettings.Format.IniFormat)


#: Every field set to something distinguishable from its default, so a field
#: that silently fails to round-trip can't pass by coincidentally matching
#: the value the dataclass would have defaulted to.
_NON_DEFAULT_PARAMS = ImpositionParams(
    signature_size_pages=8,
    sheet_width_pt=700.0,
    sheet_height_pt=500.0,
    margin_pt=12.5,
    gutter_pt=24.0,
    show_crop_marks=False,
    include_endpapers=True,
    separate_cover=False,
    pad_last_signature_to_full=True,
)


def test_list_preset_names_empty_initially(qtbot, tmp_path):
    assert list_preset_names(_settings(tmp_path)) == []


def test_persisted_fields_cover_every_imposition_param():
    """Guards the whole preset feature against a field being added to
    `ImpositionParams` but not persisted — which is exactly how
    `pad_last_signature_to_full` came to be silently dropped on load.
    """
    assert set(_FIELDS) == {field.name for field in dataclasses.fields(ImpositionParams)}


def test_non_default_params_really_differ_from_defaults():
    """Keeps the round-trip tests below honest: every field in
    `_NON_DEFAULT_PARAMS` must actually differ from the dataclass default,
    or a field that fails to persist would still compare equal."""
    defaults = ImpositionParams()
    differing = {
        field.name
        for field in dataclasses.fields(ImpositionParams)
        if getattr(_NON_DEFAULT_PARAMS, field.name) != getattr(defaults, field.name)
    }
    # separate_cover is mutually exclusive with include_endpapers, so it
    # cannot also be flipped here; it gets its own round-trip test below.
    assert differing == set(_FIELDS) - {"separate_cover"}


def test_save_and_load_preset_round_trips_all_fields(qtbot, tmp_path):
    save_preset(_settings(tmp_path), "My Preset", _NON_DEFAULT_PARAMS)

    loaded = load_preset(_settings(tmp_path), "My Preset")  # fresh instance, same file

    assert loaded == _NON_DEFAULT_PARAMS


def test_preset_round_trips_after_a_restart(qtbot, tmp_path):
    """The ini backend stores everything as text; only an in-process cache
    made values look correctly typed within the writing session. Without
    conversion on load, `ImpositionParams.__post_init__` gets `"8"` instead
    of `8` here and raises TypeError — i.e. saved presets were unusable
    after every app restart.
    """
    save_preset(_settings(tmp_path), "My Preset", _NON_DEFAULT_PARAMS)

    loaded = load_preset(_settings_read_fresh_from_disk(tmp_path), "My Preset")

    assert loaded == _NON_DEFAULT_PARAMS


def test_preset_round_trips_separate_cover_after_a_restart(qtbot, tmp_path):
    # Covers the one field _NON_DEFAULT_PARAMS can't flip (it's mutually
    # exclusive with include_endpapers).
    params = ImpositionParams(separate_cover=True)
    save_preset(_settings(tmp_path), "Wrap cover", params)

    assert load_preset(_settings_read_fresh_from_disk(tmp_path), "Wrap cover") == params


def test_false_booleans_survive_a_restart(qtbot, tmp_path):
    """Qt writes False as the literal string "false", and `bool("false")` is
    True — so a naive conversion turns every unchecked box back on."""
    params = ImpositionParams(show_crop_marks=False, include_endpapers=False)
    save_preset(_settings(tmp_path), "No marks", params)

    loaded = load_preset(_settings_read_fresh_from_disk(tmp_path), "No marks")

    assert loaded.show_crop_marks is False
    assert loaded.include_endpapers is False


def test_preset_saved_before_a_field_existed_still_loads(qtbot, tmp_path):
    """Upgrade path: a preset written by a version predating a field has no
    key for it, and QSettings returns None. That must fall back to the
    dataclass default rather than being passed through as None."""
    save_preset(_settings(tmp_path), "Old", ImpositionParams(signature_size_pages=8))

    fresh = _settings_read_fresh_from_disk(tmp_path)
    path = fresh.fileName()
    original = pathlib.Path(path).read_text().splitlines(keepends=True)
    kept = [line for line in original if "pad_last_signature_to_full" not in line]
    assert len(kept) < len(original)  # the key really was there to remove
    pathlib.Path(path).write_text("".join(kept))

    loaded = load_preset(QSettings(path, QSettings.Format.IniFormat), "Old")

    assert loaded.signature_size_pages == 8
    assert loaded.pad_last_signature_to_full is ImpositionParams().pad_last_signature_to_full


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
