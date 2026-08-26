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
