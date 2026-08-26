"""Named, persisted `ImpositionParams` presets, stored via `QSettings`.

Uses the platform's native settings store (Windows registry / macOS plist /
Linux ini under `~/.config`) rather than a bespoke file format — no extra
dependency, no custom file-location logic, and it's the standard place a
user would expect a desktop app's settings to live on each OS.

Every function takes an explicit `QSettings` instance rather than looking one
up internally, so tests can point at an isolated temp file instead of ever
touching the real, persistent user settings store — see `default_settings`
vs. `tests/test_presets.py`.
"""

from __future__ import annotations

import dataclasses
import typing

from PySide6.QtCore import QSettings

from bookwork.imposition import ImpositionParams

_ORGANIZATION = "Bookwork"
_APPLICATION = "Bookwork"
_GROUP = "presets"

#: Every `ImpositionParams` field, derived from the dataclass rather than
#: listed by hand. A hand-maintained list silently drops any field added
#: later — which is exactly what happened to `pad_last_signature_to_full`:
#: presets saved with it on came back with it off, quietly changing the
#: imposition (and sheet count) the user thought they'd saved. Deriving it
#: means a new field is persisted automatically.
#:
#: Note this makes the settings schema follow the dataclass: *renaming* a
#: field orphans whatever previously-saved presets stored under the old key
#: (`load_preset` then falls back to that field's default), and removing one
#: leaves a harmless unread key behind.
_FIELDS = tuple(field.name for field in dataclasses.fields(ImpositionParams))

#: Declared type of each field, used to convert values back on load — see
#: `_coerce`. Resolved via `get_type_hints` rather than read off
#: `dataclasses.fields(...).type`, which is the *string* `"int"` etc. under
#: `from __future__ import annotations`.
_FIELD_TYPES = typing.get_type_hints(ImpositionParams)


def _coerce(raw: object, field_type: type) -> object:
    """Convert one raw `QSettings` value back to `field_type`.

    Necessary because the ini backend — which is what `QSettings` uses
    natively on Linux, and what the tests use on every platform — stores
    values as plain text and hands them back as `str` on a genuinely fresh
    read. Within the session that wrote them an in-process `QSettings` cache
    returns the original typed values, so skipping this conversion appears
    to work right up until the app is restarted, at which point
    `ImpositionParams.__post_init__` gets `"8"` instead of `8`.

    `bool` needs an explicit string comparison rather than `bool(raw)`: Qt
    writes False as the literal `"false"`, and `bool("false")` is True.
    """
    if field_type is bool:
        return raw if isinstance(raw, bool) else str(raw).strip().lower() in {"true", "1"}
    return field_type(raw)


def default_settings() -> QSettings:
    """The app's real, persistent settings store (organization/application
    name select the OS-appropriate location — see `QSettings` docs)."""
    return QSettings(_ORGANIZATION, _APPLICATION)


def list_preset_names(settings: QSettings) -> list[str]:
    settings.beginGroup(_GROUP)
    try:
        return sorted(settings.childGroups())
    finally:
        settings.endGroup()


def save_preset(settings: QSettings, name: str, params: ImpositionParams) -> None:
    if not name.strip():
        raise ValueError("Preset name must not be empty")
    settings.beginGroup(_GROUP)
    try:
        settings.beginGroup(name)
        try:
            for field in _FIELDS:
                settings.setValue(field, getattr(params, field))
        finally:
            settings.endGroup()
    finally:
        settings.endGroup()
    settings.sync()


def load_preset(settings: QSettings, name: str) -> ImpositionParams:
    settings.beginGroup(_GROUP)
    try:
        if name not in settings.childGroups():
            raise KeyError(f"No preset named {name!r}")
        settings.beginGroup(name)
        try:
            raw_values = {field: settings.value(field) for field in _FIELDS}
        finally:
            settings.endGroup()
    finally:
        settings.endGroup()

    # A preset saved by an older version has no key for a field added since,
    # and QSettings returns None for those. Drop them so the dataclass
    # default applies, rather than passing None into ImpositionParams.
    return ImpositionParams(
        **{
            field: _coerce(raw, _FIELD_TYPES[field])
            for field, raw in raw_values.items()
            if raw is not None
        }
    )


def delete_preset(settings: QSettings, name: str) -> None:
    settings.beginGroup(_GROUP)
    try:
        settings.remove(name)
    finally:
        settings.endGroup()
    settings.sync()
