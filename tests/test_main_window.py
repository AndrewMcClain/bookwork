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
    # Signature size defaults to 20 pages; a 4-page doc is padded up to a full
    # 20-page signature (like real psbook does) -> 10 sheet sides.
    assert window._imposed_pane.document.page_count == 10


def test_changing_imposition_params_regenerates_imposed_view(qtbot, make_pdf):
    path = make_pdf(num_pages=16)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))

    # 16 pages padded up to the default 20-page signature -> 10 sheet sides.
    assert window._imposed_pane.document.page_count == 10

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
    assert "3" in stats_text  # signatures (20 pages / 8-page signatures -> 3)
    assert "4" in stats_text  # blank pages added
