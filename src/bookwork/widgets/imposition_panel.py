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

"""Form panel for imposition parameters (signature size, sheet size, margin,
gutter, crop marks), saved presets, plus a read-only summary of the
resulting layout (number of signatures, blanks added, sheet count, ...).
Emits the current settings as an `ImpositionParams` when the user clicks
Apply (or picks a preset) — deliberately not live-on-every-keystroke, so
typing a new value doesn't trigger a re-impose on every digit.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bookwork.imposition import ImpositionParams, ImpositionStats, describe_signature_sizes
from bookwork.presets import default_settings, delete_preset, list_preset_names, load_preset, save_preset

_PT_PER_INCH = 72.0

#: Sentinel item at the top of the preset dropdown — no preset selected.
_NO_PRESET = "(no preset)"

#: Shown in the paper-size dropdown when the sheet doesn't match a known size.
#: Selecting it deliberately changes nothing — it is a label for where you
#: already are, not a size to switch to.
_CUSTOM_PAPER = "(Custom)"

#: Sheet sizes offered in the dropdown, `name: (width_in, height_in)`.
#:
#: Wide edge first, i.e. fed landscape, because the sheet is folded across its
#: width to make the leaves — a "Letter" booklet is Letter turned sideways and
#: folded in half, not a Letter-shaped page. The names carry their dimensions
#: so the dropdown is unambiguous about which way round it means.
#:
#: ISO sizes are converted from their millimetre definitions rather than
#: rounded inch values, so A4 is 297x210mm exactly.
_MM_PER_INCH = 25.4
PAPER_SIZES: dict[str, tuple[float, float]] = {
    "Letter — 11 × 8.5 in": (11.0, 8.5),
    "Legal — 14 × 8.5 in": (14.0, 8.5),
    "Tabloid — 17 × 11 in": (17.0, 11.0),
    "A3 — 420 × 297 mm": (420 / _MM_PER_INCH, 297 / _MM_PER_INCH),
    "A4 — 297 × 210 mm": (297 / _MM_PER_INCH, 210 / _MM_PER_INCH),
    "A5 — 210 × 148 mm": (210 / _MM_PER_INCH, 148 / _MM_PER_INCH),
    "B5 — 250 × 176 mm": (250 / _MM_PER_INCH, 176 / _MM_PER_INCH),
}

#: The spinboxes show three decimals, so anything closer than this is the same
#: size as far as the user can see or enter.
_PAPER_MATCH_TOLERANCE_IN = 0.001


def paper_size_name(width_in: float, height_in: float) -> str:
    """The dropdown entry matching these dimensions, or `_CUSTOM_PAPER`."""
    for name, (width, height) in PAPER_SIZES.items():
        if (
            abs(width - width_in) <= _PAPER_MATCH_TOLERANCE_IN
            and abs(height - height_in) <= _PAPER_MATCH_TOLERANCE_IN
        ):
            return name
    return _CUSTOM_PAPER


class ImpositionPanel(QWidget):
    params_changed = Signal(ImpositionParams)

    def __init__(self, initial: ImpositionParams | None = None, settings: QSettings | None = None) -> None:
        super().__init__()
        initial = initial or ImpositionParams()
        self._settings = settings if settings is not None else default_settings()

        self._preset_combo = QComboBox()
        self._preset_combo.activated.connect(self._on_preset_selected)
        self._save_preset_button = QPushButton("Save As...")
        self._save_preset_button.setToolTip("Save the current settings below as a named preset.")
        self._save_preset_button.clicked.connect(self._save_current_as_preset)
        self._delete_preset_button = QPushButton("Delete")
        self._delete_preset_button.setToolTip("Delete the selected preset.")
        self._delete_preset_button.clicked.connect(self._delete_selected_preset)
        self._reload_preset_list()

        preset_row = QHBoxLayout()
        preset_row.addWidget(self._preset_combo, stretch=1)
        preset_row.addWidget(self._save_preset_button)
        preset_row.addWidget(self._delete_preset_button)

        self._signature_size = QSpinBox()
        self._signature_size.setRange(0, 9996)
        self._signature_size.setSingleStep(4)
        self._signature_size.setToolTip(
            "Pages per signature (must be 0 for a single signature covering\n"
            "the whole document, or a multiple of 4)."
        )

        self._sheet_width_in = self._make_inch_spinbox()
        self._sheet_height_in = self._make_inch_spinbox()

        self._paper_size = QComboBox()
        self._paper_size.addItems([*PAPER_SIZES, _CUSTOM_PAPER])
        self._paper_size.setToolTip(
            "Fills in the sheet size below. Sizes are listed wide edge first:\n"
            "the sheet is fed landscape and folded across its width, so a\n"
            "Letter booklet uses Letter turned sideways.\n\n"
            "Editing the width or height directly switches this to (Custom).\n"
            "Choosing (Custom) leaves the dimensions alone."
        )
        # `activated` fires only on a real user pick, so syncing the dropdown
        # back from the spinboxes below cannot loop.
        self._paper_size.activated.connect(self._on_paper_size_selected)
        for spinbox in (self._sheet_width_in, self._sheet_height_in):
            spinbox.valueChanged.connect(self._sync_paper_size)
        self._margin_in = self._make_inch_spinbox()
        self._gutter_in = self._make_inch_spinbox()

        self._show_crop_marks = QCheckBox("Show crop marks")
        self._show_crop_marks.setToolTip(
            "Draw a small L-shaped tick at each corner of the placed page,\n"
            "marking where to trim the sheet down to. Both arms point away\n"
            "from the page, so cutting along them leaves no ink behind on\n"
            "the finished page."
        )

        self._include_endpapers = QCheckBox("Add blank endpapers (case binding)")
        self._include_endpapers.setToolTip(
            "Add one real blank page at the very front and one at the very\n"
            "back, for gluing to a hardcover case. Not needed for a plain\n"
            "stapled/saddle-stitch booklet."
        )

        self._separate_cover = QCheckBox("Separate wrap cover (first/last page)")
        self._separate_cover.setToolTip(
            "Treat the first and last page as a single-folio cover, printed\n"
            "and folded on its own, wrapped around the interior signature(s)\n"
            "— e.g. for a saddle-stitch booklet with heavier cover stock."
        )

        self._pad_last_signature_to_full = QCheckBox("Pad last signature to full size")
        self._pad_last_signature_to_full.setToolTip(
            "By default, a leftover partial signature is padded only up to\n"
            "the next multiple of 4, to avoid wasting blank pages/sheets.\n"
            "Check this to force every signature — including the last — to\n"
            "the same full signature size instead."
        )

        # Mutually exclusive: ImpositionParams itself rejects both being set,
        # but resolving that in the UI directly is friendlier than a warning
        # dialog every time.
        self._include_endpapers.toggled.connect(
            lambda checked: self._separate_cover.setChecked(False) if checked else None
        )
        self._separate_cover.toggled.connect(
            lambda checked: self._include_endpapers.setChecked(False) if checked else None
        )

        self._apply_button = QPushButton("Apply")
        self._apply_button.clicked.connect(self.try_emit_params)

        self._set_fields(initial)

        form = QFormLayout()
        form.addRow("Preset", preset_row)
        form.addRow("Signature size (pages)", self._signature_size)
        form.addRow("Paper size", self._paper_size)
        form.addRow("Sheet width (in)", self._sheet_width_in)
        form.addRow("Sheet height (in)", self._sheet_height_in)
        form.addRow("Margin (in)", self._margin_in)
        form.addRow("Gutter (in)", self._gutter_in)
        form.addRow(self._show_crop_marks)
        form.addRow(self._include_endpapers)
        form.addRow(self._separate_cover)
        form.addRow(self._pad_last_signature_to_full)
        form.addRow(self._apply_button)

        self._stats_label = QLabel("Open a PDF to see layout stats.")
        self._stats_label.setWordWrap(True)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(divider)
        layout.addWidget(self._stats_label)
        layout.addStretch(1)

    def _on_paper_size_selected(self, _index: int) -> None:
        """Fill in the sheet size from the dropdown.

        `(Custom)` is a no-op by design: it describes a sheet size that isn't
        one of the presets, so there is nothing to switch *to*. Picking it
        should never disturb dimensions the user has already dialled in.
        """
        size = PAPER_SIZES.get(self._paper_size.currentText())
        if size is None:
            return
        width_in, height_in = size
        self._sheet_width_in.setValue(width_in)
        self._sheet_height_in.setValue(height_in)

    def _sync_paper_size(self) -> None:
        """Point the dropdown at whatever the spinboxes now say.

        Runs on every change to either dimension, including the ones
        `_on_paper_size_selected` just made — it resolves to the same entry in
        that case, so no guard flag is needed. Typing a size by hand therefore
        lands on `(Custom)` unless it happens to match a listed size exactly,
        in which case naming it is more useful than calling it custom.
        """
        name = paper_size_name(self._sheet_width_in.value(), self._sheet_height_in.value())
        self._paper_size.setCurrentIndex(self._paper_size.findText(name))

    @staticmethod
    def _make_inch_spinbox() -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(0.0, 100.0)
        box.setSingleStep(0.125)
        box.setDecimals(3)
        box.setSuffix(" in")
        return box

    def _set_fields(self, params: ImpositionParams) -> None:
        self._signature_size.setValue(params.signature_size_pages)
        self._sheet_width_in.setValue(params.sheet_width_pt / _PT_PER_INCH)
        self._sheet_height_in.setValue(params.sheet_height_pt / _PT_PER_INCH)
        self._margin_in.setValue(params.margin_pt / _PT_PER_INCH)
        self._gutter_in.setValue(params.gutter_pt / _PT_PER_INCH)
        self._show_crop_marks.setChecked(params.show_crop_marks)
        self._include_endpapers.setChecked(params.include_endpapers)
        self._separate_cover.setChecked(params.separate_cover)
        self._pad_last_signature_to_full.setChecked(params.pad_last_signature_to_full)
        self._sync_paper_size()

    def current_params(self) -> ImpositionParams:
        """Build an `ImpositionParams` from the current field values.

        Raises `ValueError` (from `ImpositionParams.__post_init__`) if the
        fields don't form a valid combination — e.g. a signature size that
        isn't 0 or a multiple of 4. Callers driving this from a button click
        should use `try_emit_params` instead, which surfaces that as a
        message box rather than an uncaught exception in a Qt slot.
        """
        return ImpositionParams(
            signature_size_pages=self._signature_size.value(),
            sheet_width_pt=self._sheet_width_in.value() * _PT_PER_INCH,
            sheet_height_pt=self._sheet_height_in.value() * _PT_PER_INCH,
            margin_pt=self._margin_in.value() * _PT_PER_INCH,
            gutter_pt=self._gutter_in.value() * _PT_PER_INCH,
            show_crop_marks=self._show_crop_marks.isChecked(),
            include_endpapers=self._include_endpapers.isChecked(),
            separate_cover=self._separate_cover.isChecked(),
            pad_last_signature_to_full=self._pad_last_signature_to_full.isChecked(),
        )

    def try_emit_params(self) -> None:
        try:
            params = self.current_params()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid imposition settings", str(exc))
            return
        self.params_changed.emit(params)

    # --- Presets ---

    def _reload_preset_list(self, *, select: str | None = None) -> None:
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        self._preset_combo.addItem(_NO_PRESET)
        self._preset_combo.addItems(list_preset_names(self._settings))
        if select is not None:
            index = self._preset_combo.findText(select)
            if index >= 0:
                self._preset_combo.setCurrentIndex(index)
        self._preset_combo.blockSignals(False)
        self._delete_preset_button.setEnabled(self._preset_combo.currentText() != _NO_PRESET)

    def _on_preset_selected(self, _index: int) -> None:
        name = self._preset_combo.currentText()
        self._delete_preset_button.setEnabled(name != _NO_PRESET)
        if name == _NO_PRESET:
            return
        try:
            params = load_preset(self._settings, name)
        except KeyError:
            self._reload_preset_list()
            return
        self._set_fields(params)
        self.try_emit_params()  # a preset pick is one deliberate action -> apply immediately

    def _save_current_as_preset(self) -> None:
        try:
            params = self.current_params()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid imposition settings", str(exc))
            return

        current = self._preset_combo.currentText()
        default_name = current if current != _NO_PRESET else ""
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:", text=default_name)
        if not ok or not name.strip():
            return
        name = name.strip()

        save_preset(self._settings, name, params)
        self._reload_preset_list(select=name)

    def _delete_selected_preset(self) -> None:
        name = self._preset_combo.currentText()
        if name == _NO_PRESET:
            return
        delete_preset(self._settings, name)
        self._reload_preset_list()

    # --- Stats ---

    def set_stats(self, stats: ImpositionStats | None) -> None:
        if stats is None or stats.source_page_count == 0:
            self._stats_label.setText("Open a PDF to see layout stats.")
            return

        lines = [f"<b>{stats.source_page_count}</b> source pages"]
        if stats.signature_size_pages == 0:
            lines.append("single signature (whole document)")
        else:
            breakdown = describe_signature_sizes(stats.signature_sizes)
            lines.append(f"<b>1</b> cover sheet + {breakdown}" if stats.has_separate_cover else breakdown)
        if stats.blank_pages_added:
            lines.append(f"<b>{stats.blank_pages_added}</b> blank page(s) added")
        lines.append(
            f"<b>{stats.sheet_side_count}</b> sheet sides "
            f"(<b>{stats.physical_sheet_count}</b> physical sheet(s) of paper, printed duplex)"
        )
        self._stats_label.setText("<br>".join(lines))
