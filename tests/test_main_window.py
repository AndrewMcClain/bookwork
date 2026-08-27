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

import pytest
from PySide6.QtWidgets import QDialog

from bookwork.main_window import MainWindow


def test_open_pdf_loads_pages_and_shows_first_page(qtbot, make_pdf):
    path = make_pdf(num_pages=4)
    window = MainWindow()
    qtbot.addWidget(window)

    window.open_pdf(str(path))

    assert window._source_pane.document is not None
    assert window._source_pane.document.page_count == 4
    assert window._source_pane.current_page == 0
    assert window._source_pane.thumbnail_list.count() == 4


def test_next_and_previous_navigate_pages(qtbot, make_pdf):
    path = make_pdf(num_pages=3)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))

    window._go_next()
    assert window._source_pane.current_page == 1

    window._go_next()
    assert window._source_pane.current_page == 2

    # Already on the last page: should clamp, not error or wrap.
    window._go_next()
    assert window._source_pane.current_page == 2

    window._go_previous()
    assert window._source_pane.current_page == 1


def test_thumbnail_click_navigates_to_page(qtbot, make_pdf):
    path = make_pdf(num_pages=3)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))

    window._source_pane.thumbnail_list.page_selected.emit(2)
    assert window._source_pane.current_page == 2


def test_opening_pdf_also_populates_imposed_tab(qtbot, make_pdf):
    path = make_pdf(num_pages=4)
    window = MainWindow()
    qtbot.addWidget(window)

    window.open_pdf(str(path))

    assert window._imposed_pane.document is not None
    # Signature size defaults to 20 pages, but the last (only) signature is
    # minimized by default -> a 4-page doc pads only to 4, not a full 20
    # -> 2 sheet sides.
    assert window._imposed_pane.document.page_count == 2


def test_changing_imposition_params_regenerates_imposed_view(qtbot, make_pdf):
    path = make_pdf(num_pages=16)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))

    # 16 pages, default 20-page signature, minimized -> pads only to 16 -> 8 sheet sides.
    assert window._imposed_pane.document.page_count == 8

    window._imposition_panel._signature_size.setValue(8)
    window._imposition_panel.try_emit_params()

    # 16 pages / 8-page signatures divides evenly, no padding -> 8 sheet sides.
    assert window._imposed_pane.document.page_count == 8


def test_invalid_imposition_params_shows_warning_and_keeps_prior_view(qtbot, make_pdf, monkeypatch):
    path = make_pdf(num_pages=8)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))
    prior_document = window._imposed_pane.document

    warnings = []
    monkeypatch.setattr(
        "bookwork.widgets.imposition_panel.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append(args),
    )

    # 3 is neither 0 nor a multiple of 4: current_params() would raise, but
    # try_emit_params (what the Apply button calls) must catch that itself.
    window._imposition_panel._signature_size.setValue(3)
    window._imposition_panel.try_emit_params()

    assert len(warnings) == 1
    assert window._imposed_pane.document is prior_document  # unchanged


def test_editing_pages_with_invalid_unapplied_params_warns_instead_of_going_stale(
    qtbot, make_pdf, monkeypatch
):
    """Editing a page re-imposes using the panel's *current* fields, which
    may hold a value the widgets accept but ImpositionParams rejects (the
    spinbox allows 6; only multiples of 4 are valid). That must surface as a
    warning, not escape the Qt slot — which used to abort the callback after
    the page edit had already landed, leaving Imposed/Bound Preview silently
    showing the pre-edit layout with nothing reported to the user.
    """
    path = make_pdf(num_pages=9)
    window = MainWindow()
    qtbot.addWidget(window)
    window._imposition_panel._signature_size.setValue(4)
    window.open_pdf(str(path))
    assert window._imposed_pane.document.page_count == 6  # 9 pages -> [4,4,4] -> 6 sheet sides

    warnings = []
    monkeypatch.setattr(
        "bookwork.main_window.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append(args),
    )

    window._imposition_panel._signature_size.setValue(6)  # invalid, never applied
    window._source_pane.thumbnail_list.delete_requested.emit(0)

    assert window._source_pane.document.page_count == 8  # the edit itself still happened
    assert len(warnings) == 1  # ...and the user was told why the view didn't update


def test_every_page_edit_path_routes_through_the_guarded_reimpose(qtbot, make_pdf, monkeypatch):
    """The guard only helps if every edit path uses it. Each of these
    mutates the source and must re-impose through `_reimpose_from_panel`
    rather than calling `current_params()` unguarded itself.
    """
    path = make_pdf(num_pages=4)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))

    calls = []
    monkeypatch.setattr(window, "_reimpose_from_panel", lambda: calls.append(True))

    window._source_pane.thumbnail_list.insert_before_requested.emit(0)
    window._source_pane.thumbnail_list.insert_after_requested.emit(0)
    window._source_pane.thumbnail_list.delete_requested.emit(0)
    window._undo()
    window._redo()

    assert len(calls) == 5


def test_active_tab_determines_navigation_target(qtbot, make_pdf):
    path = make_pdf(num_pages=16)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))

    window._tabs.setCurrentIndex(1)  # Imposed tab
    window._go_next()
    assert window._imposed_pane.current_page == 1
    assert window._source_pane.current_page == 0


def test_opening_pdf_also_populates_bound_preview_tab_in_reading_order(qtbot, make_pdf):
    path = make_pdf(num_pages=8)
    window = MainWindow()
    qtbot.addWidget(window)
    window._imposition_panel._signature_size.setValue(8)

    window.open_pdf(str(path))

    assert window._bound_preview_pane.document is not None
    # 8 pages -> views [1],[2,3],[4,5],[6,7],[8]: 5 views (single cover pages,
    # spreads in between), matching how a reader flips through the book.
    doc = window._bound_preview_pane.document.fitz_document
    assert doc.page_count == 5
    assert "Page 1" in doc[0].get_text()
    assert "Page 2" in doc[1].get_text() and "Page 3" in doc[1].get_text()
    assert "Page 8" in doc[4].get_text()


def test_bound_preview_tab_is_third_tab_and_navigable(qtbot, make_pdf):
    path = make_pdf(num_pages=8)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))

    assert window._tabs.tabText(2) == "Bound Preview"
    window._tabs.setCurrentIndex(2)
    window._go_next()
    assert window._bound_preview_pane.current_page == 1


def test_imposition_panel_stats_reflect_opened_document(qtbot, make_pdf):
    path = make_pdf(num_pages=20)
    window = MainWindow()
    qtbot.addWidget(window)
    window._imposition_panel._signature_size.setValue(8)

    window.open_pdf(str(path))

    stats_text = window._imposition_panel._stats_label.text()
    assert "20" in stats_text  # source pages
    assert "2 full signatures" in stats_text  # 20 pages / 8-page signatures -> 2 full + 1 partial
    assert "1 signature of 4 pages" in stats_text  # minimized by default, not padded to a full 8
    assert "10" in stats_text  # sheet sides (no wasted padding)


def _source_page_texts(window: MainWindow) -> list[str]:
    doc = window._source_pane.document.fitz_document
    return [doc[i].get_text().strip() for i in range(doc.page_count)]


def test_insert_blank_page_before_updates_source_and_regenerates_imposed(qtbot, make_pdf):
    path = make_pdf(num_pages=3)
    window = MainWindow()
    qtbot.addWidget(window)
    window._imposition_panel._signature_size.setValue(4)
    window.open_pdf(str(path))
    imposed_before = window._imposed_pane.document

    window._insert_blank_page(1)  # before page 2

    assert window._source_pane.document.page_count == 4
    texts = _source_page_texts(window)
    assert "Page 1" in texts[0]
    assert texts[1] == ""
    assert "Page 2" in texts[2]
    assert "Page 3" in texts[3]
    # Regenerated, not the same object as before the edit.
    assert window._imposed_pane.document is not imposed_before
    assert window._undo_action.isEnabled()


def test_insert_blank_page_after(qtbot, make_pdf):
    path = make_pdf(num_pages=3)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))

    window._source_pane.thumbnail_list.insert_after_requested.emit(0)  # after page 1

    texts = _source_page_texts(window)
    assert "Page 1" in texts[0]
    assert texts[1] == ""
    assert "Page 2" in texts[2]


def test_delete_page_removes_it_and_regenerates_imposed(qtbot, make_pdf):
    path = make_pdf(num_pages=3)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))
    imposed_before = window._imposed_pane.document

    window._delete_page(1)  # remove "Page 2"

    assert window._source_pane.document.page_count == 2
    texts = _source_page_texts(window)
    assert "Page 1" in texts[0]
    assert "Page 3" in texts[1]
    assert window._imposed_pane.document is not imposed_before


def test_delete_page_refuses_to_empty_the_document(qtbot, make_pdf, monkeypatch):
    path = make_pdf(num_pages=1)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))

    warnings = []
    monkeypatch.setattr(
        "bookwork.main_window.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append(args),
    )

    window._delete_page(0)

    assert len(warnings) == 1
    assert window._source_pane.document.page_count == 1  # unchanged


def test_undo_redo_round_trip_through_main_window(qtbot, make_pdf):
    path = make_pdf(num_pages=3)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))

    assert not window._undo_action.isEnabled()
    assert not window._redo_action.isEnabled()

    window._delete_page(1)
    assert window._source_pane.document.page_count == 2
    assert window._undo_action.isEnabled()

    window._undo()
    assert window._source_pane.document.page_count == 3
    assert _source_page_texts(window) == ["Page 1", "Page 2", "Page 3"]
    assert window._redo_action.isEnabled()

    window._redo()
    assert window._source_pane.document.page_count == 2
    assert _source_page_texts(window) == ["Page 1", "Page 3"]


def test_thumbnail_context_menu_signals_wire_to_main_window_handlers(qtbot, make_pdf):
    # The Source tab's thumbnail list must be editable; Imposed/Bound Preview
    # must not be (they're regenerated output, not user-editable).
    path = make_pdf(num_pages=3)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))

    assert window._source_pane.thumbnail_list._editable
    assert not window._imposed_pane.thumbnail_list._editable
    assert not window._bound_preview_pane.thumbnail_list._editable


def test_separate_cover_checkbox_regenerates_with_cover(qtbot, make_pdf):
    path = make_pdf(num_pages=10)
    window = MainWindow()
    qtbot.addWidget(window)
    window._imposition_panel._signature_size.setValue(8)
    window.open_pdf(str(path))

    window._imposition_panel._separate_cover.setChecked(True)
    window._imposition_panel.try_emit_params()

    # 2 cover sheet sides + interior (8 pages -> content 10, minimized to
    # chunks [8,4]=12 -> 6 sheet sides) = 8.
    assert window._imposed_pane.document.page_count == 8
    stats_text = window._imposition_panel._stats_label.text()
    assert "cover sheet" in stats_text


def test_separate_cover_and_endpapers_checkboxes_are_mutually_exclusive(qtbot):
    from bookwork.widgets.imposition_panel import ImpositionPanel

    panel = ImpositionPanel()
    qtbot.addWidget(panel)

    panel._include_endpapers.setChecked(True)
    assert panel._include_endpapers.isChecked()

    panel._separate_cover.setChecked(True)
    assert panel._separate_cover.isChecked()
    assert not panel._include_endpapers.isChecked()  # turned off automatically

    panel._include_endpapers.setChecked(True)
    assert panel._include_endpapers.isChecked()
    assert not panel._separate_cover.isChecked()  # turned off automatically


def test_print_action_disabled_without_a_document(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    assert not window._print_action.isEnabled()


def test_print_action_enabled_after_opening_a_pdf(qtbot, make_pdf):
    path = make_pdf(num_pages=4)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))
    assert window._print_action.isEnabled()


def test_print_imposed_does_nothing_without_a_document(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)

    informed = []
    monkeypatch.setattr(
        "bookwork.main_window.QMessageBox.information",
        lambda *args, **kwargs: informed.append(args),
    )

    window._print_imposed()

    assert len(informed) == 1


def test_print_imposed_does_not_print_when_dialog_is_cancelled(qtbot, make_pdf, monkeypatch):
    # Never actually pop a real print dialog or send a job to a real
    # printer in a test -- simulate the user clicking Cancel.
    path = make_pdf(num_pages=4)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))

    printed = []
    monkeypatch.setattr("bookwork.main_window.print_document", lambda *args, **kwargs: printed.append(args))
    monkeypatch.setattr(
        "bookwork.main_window.QPrintDialog.exec",
        lambda self: QDialog.DialogCode.Rejected,
    )

    window._print_imposed()

    assert printed == []


def test_print_imposed_calls_print_document_when_dialog_is_accepted(qtbot, make_pdf, monkeypatch):
    path = make_pdf(num_pages=4)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))

    printed = []
    monkeypatch.setattr(
        "bookwork.main_window.print_document", lambda doc, printer, **kwargs: printed.append(doc)
    )
    monkeypatch.setattr(
        "bookwork.main_window.QPrintDialog.exec",
        lambda self: QDialog.DialogCode.Accepted,
    )

    window._print_imposed()

    assert printed == [window._imposed_pane.document]


def test_saving_and_selecting_a_preset_applies_it(qtbot, make_pdf, monkeypatch):
    path = make_pdf(num_pages=8)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))
    panel = window._imposition_panel

    panel._signature_size.setValue(4)
    monkeypatch.setattr(
        "bookwork.widgets.imposition_panel.QInputDialog.getText",
        lambda *args, **kwargs: ("My Preset", True),
    )
    panel._save_current_as_preset()
    assert panel._preset_combo.currentText() == "My Preset"

    # Change the field away from the saved value, then re-select the preset.
    panel._signature_size.setValue(20)
    index = panel._preset_combo.findText("My Preset")
    panel._preset_combo.setCurrentIndex(index)
    panel._on_preset_selected(index)

    assert panel._signature_size.value() == 4
    # Selecting a preset applies it immediately (not gated behind Apply).
    assert window._imposed_pane.document.page_count == 4  # 8 pages / 4-page signatures -> 4 sheet sides


def test_deleting_a_preset_removes_it_from_the_combo(qtbot, monkeypatch):
    from bookwork.widgets.imposition_panel import ImpositionPanel

    panel = ImpositionPanel()
    qtbot.addWidget(panel)

    monkeypatch.setattr(
        "bookwork.widgets.imposition_panel.QInputDialog.getText",
        lambda *args, **kwargs: ("Temp", True),
    )
    panel._save_current_as_preset()
    assert panel._preset_combo.findText("Temp") >= 0

    panel._delete_selected_preset()

    assert panel._preset_combo.findText("Temp") == -1


def test_pad_last_signature_to_full_checkbox_toggles_padding_behavior(qtbot, make_pdf):
    path = make_pdf(num_pages=20)
    window = MainWindow()
    qtbot.addWidget(window)
    window._imposition_panel._signature_size.setValue(8)
    window.open_pdf(str(path))

    # Off by default: last signature minimized -> chunks [8,8,4] -> 10 sheets.
    assert not window._imposition_panel._pad_last_signature_to_full.isChecked()
    assert window._imposed_pane.document.page_count == 10

    window._imposition_panel._pad_last_signature_to_full.setChecked(True)
    window._imposition_panel.try_emit_params()

    # On: every signature forced to the full 8 pages -> chunks [8,8,8] -> 12 sheets.
    assert window._imposed_pane.document.page_count == 12
    stats_text = window._imposition_panel._stats_label.text()
    assert "8 pages/signature, 3 signatures" in stats_text


def test_bound_preview_pages_by_click_and_arrow_keys(qtbot, make_pdf):
    """Click a page to turn it, or use the arrow keys — both drive the same
    navigation the menu and thumbnails do, so the status bar and thumbnail
    selection stay in step."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    path = make_pdf(num_pages=12)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))
    window._tabs.setCurrentIndex(2)  # Bound Preview

    pane = window._bound_preview_pane
    view = pane.page_view
    assert pane.current_page == 0

    def click(fraction):
        QTest.mouseClick(
            view, Qt.MouseButton.LeftButton, pos=QPoint(int(view.width() * fraction), view.height() // 2)
        )

    click(0.75)
    assert pane.current_page == 1
    click(0.25)
    assert pane.current_page == 0

    QTest.keyClick(view, Qt.Key.Key_Right)
    assert pane.current_page == 1
    QTest.keyClick(view, Qt.Key.Key_Left)
    assert pane.current_page == 0

    assert pane.thumbnail_list.currentRow() == 0
    assert "Page 1 of" in window.statusBar().currentMessage()


def test_bound_preview_navigation_stops_at_both_ends(qtbot, make_pdf):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    path = make_pdf(num_pages=12)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))
    window._tabs.setCurrentIndex(2)
    pane = window._bound_preview_pane
    last = pane.document.page_count - 1

    for _ in range(last + 5):
        QTest.keyClick(pane.page_view, Qt.Key.Key_Right)
    assert pane.current_page == last

    for _ in range(last + 5):
        QTest.keyClick(pane.page_view, Qt.Key.Key_Left)
    assert pane.current_page == 0


def test_arrow_keys_still_reach_the_imposition_panel_fields(qtbot, make_pdf):
    """The page view claims Left/Right, so it must do so as a focused widget
    rather than as an application shortcut — otherwise it would steal the
    arrow keys from every text cursor and spinbox in the settings panel."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    path = make_pdf(num_pages=8)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))
    window._tabs.setCurrentIndex(1)  # Imposed

    spin = window._imposition_panel._signature_size
    spin.setFocus()
    before = spin.value()
    QTest.keyClick(spin, Qt.Key.Key_Left)

    assert spin.value() == before


def test_only_the_bound_preview_animates_turns(qtbot, make_pdf):
    """Source and Imposed show flat sheets; a turn animation there would
    imply a physical structure that isn't in the output."""
    from bookwork.widgets.page_turn_view import PageTurnView

    window = MainWindow()
    qtbot.addWidget(window)

    assert isinstance(window._bound_preview_pane.page_view, PageTurnView)
    assert not isinstance(window._source_pane.page_view, PageTurnView)
    assert not isinstance(window._imposed_pane.page_view, PageTurnView)


# --- Paper size dropdown ---


def _panel(qtbot):
    from bookwork.widgets.imposition_panel import ImpositionPanel

    panel = ImpositionPanel()
    qtbot.addWidget(panel)
    return panel


def _pick_paper(panel, name):
    """Select by name the way a user does — `activated` only fires for real
    interaction, so setCurrentIndex alone would not trigger anything."""
    index = panel._paper_size.findText(name)
    assert index >= 0, f"{name!r} not in the dropdown"
    panel._paper_size.setCurrentIndex(index)
    panel._paper_size.activated.emit(index)


def test_paper_size_defaults_to_the_matching_name(qtbot):
    """The shipped default is Letter landscape, so the dropdown should say so
    rather than calling the out-of-box configuration custom."""
    panel = _panel(qtbot)
    assert panel._paper_size.currentText().startswith("Letter")


def test_choosing_a_paper_size_fills_in_the_dimensions(qtbot):
    from bookwork.widgets.imposition_panel import PAPER_SIZES

    panel = _panel(qtbot)
    name = next(n for n in PAPER_SIZES if n.startswith("A4"))
    width_in, height_in = PAPER_SIZES[name]

    _pick_paper(panel, name)

    assert panel._sheet_width_in.value() == pytest.approx(width_in, abs=0.001)
    assert panel._sheet_height_in.value() == pytest.approx(height_in, abs=0.001)


def test_paper_sizes_are_landscape(qtbot):
    """The sheet is folded across its width, so every listed size is wider
    than it is tall — a Letter booklet is Letter turned sideways."""
    from bookwork.widgets.imposition_panel import PAPER_SIZES

    for name, (width_in, height_in) in PAPER_SIZES.items():
        assert width_in > height_in, f"{name} is not landscape"


@pytest.mark.parametrize("field", ["_sheet_width_in", "_sheet_height_in"])
def test_editing_a_dimension_switches_to_custom(qtbot, field):
    panel = _panel(qtbot)
    assert not panel._paper_size.currentText().startswith("(Custom")

    getattr(panel, field).setValue(9.25)

    assert panel._paper_size.currentText() == "(Custom)"


def test_choosing_custom_leaves_the_dimensions_alone(qtbot):
    """(Custom) describes where you already are; there is nothing to switch
    to, so picking it must not disturb a size already dialled in."""
    panel = _panel(qtbot)
    panel._sheet_width_in.setValue(9.25)
    panel._sheet_height_in.setValue(6.5)

    _pick_paper(panel, "(Custom)")

    assert panel._sheet_width_in.value() == pytest.approx(9.25)
    assert panel._sheet_height_in.value() == pytest.approx(6.5)


def test_choosing_custom_after_a_preset_keeps_that_presets_dimensions(qtbot):
    from bookwork.widgets.imposition_panel import PAPER_SIZES

    panel = _panel(qtbot)
    name = next(n for n in PAPER_SIZES if n.startswith("Legal"))
    _pick_paper(panel, name)
    width, height = panel._sheet_width_in.value(), panel._sheet_height_in.value()

    _pick_paper(panel, "(Custom)")

    assert panel._sheet_width_in.value() == pytest.approx(width)
    assert panel._sheet_height_in.value() == pytest.approx(height)


def test_the_chosen_paper_size_reaches_the_emitted_params(qtbot):
    from bookwork.widgets.imposition_panel import PAPER_SIZES

    panel = _panel(qtbot)
    name = next(n for n in PAPER_SIZES if n.startswith("A4"))
    _pick_paper(panel, name)

    params = panel.current_params()

    width_in, height_in = PAPER_SIZES[name]
    assert params.sheet_width_pt == pytest.approx(width_in * 72.0, abs=0.1)
    assert params.sheet_height_pt == pytest.approx(height_in * 72.0, abs=0.1)


def test_loading_a_preset_names_its_paper_size(qtbot):
    """A saved imposition preset stores dimensions, not a paper name, so the
    dropdown has to work the name back out."""
    from bookwork.imposition import ImpositionParams
    from bookwork.widgets.imposition_panel import PAPER_SIZES

    panel = _panel(qtbot)
    name = next(n for n in PAPER_SIZES if n.startswith("A3"))
    width_in, height_in = PAPER_SIZES[name]

    panel._set_fields(ImpositionParams(sheet_width_pt=width_in * 72.0, sheet_height_pt=height_in * 72.0))

    assert panel._paper_size.currentText() == name


def test_loading_an_unusual_size_says_custom(qtbot):
    from bookwork.imposition import ImpositionParams

    panel = _panel(qtbot)

    panel._set_fields(ImpositionParams(sheet_width_pt=700.0, sheet_height_pt=500.0))

    assert panel._paper_size.currentText() == "(Custom)"
