from bookwork.main_window import MainWindow


def test_open_pdf_loads_pages_and_shows_first_page(qtbot, make_pdf):
    path = make_pdf(num_pages=4)
    window = MainWindow()
    qtbot.addWidget(window)

    window.open_pdf(str(path))

    assert window._document is not None
    assert window._document.page_count == 4
    assert window._current_page == 0
    assert window._thumbnail_list.count() == 4


def test_next_and_previous_navigate_pages(qtbot, make_pdf):
    path = make_pdf(num_pages=3)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))

    window._go_next()
    assert window._current_page == 1

    window._go_next()
    assert window._current_page == 2

    # Already on the last page: should clamp, not error or wrap.
    window._go_next()
    assert window._current_page == 2

    window._go_previous()
    assert window._current_page == 1


def test_thumbnail_click_navigates_to_page(qtbot, make_pdf):
    path = make_pdf(num_pages=3)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_pdf(str(path))

    window._thumbnail_list.page_selected.emit(2)
    assert window._current_page == 2
