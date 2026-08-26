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

from PySide6.QtCore import QSettings

from bookwork.imposition import ImpositionParams

_ORGANIZATION = "Bookwork"
_APPLICATION = "Bookwork"
_GROUP = "presets"

_FIELDS = (
    "signature_size_pages",
    "sheet_width_pt",
    "sheet_height_pt",
    "margin_pt",
    "gutter_pt",
    "show_crop_marks",
    "include_endpapers",
    "separate_cover",
)


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
            kwargs = {field: settings.value(field) for field in _FIELDS}
        finally:
            settings.endGroup()
    finally:
        settings.endGroup()
    return ImpositionParams(**kwargs)


def delete_preset(settings: QSettings, name: str) -> None:
    settings.beginGroup(_GROUP)
    try:
        settings.remove(name)
    finally:
        settings.endGroup()
    settings.sync()
