from bookwork.pdf_document import PdfDocument


def test_page_count(make_pdf):
    path = make_pdf(num_pages=5)
    with PdfDocument(path) as doc:
        assert doc.page_count == 5


def test_render_page_size_matches_dpi(make_pdf):
    # Letter size (612 x 792 pt) at 150 DPI -> 612/72*150 x 792/72*150
    path = make_pdf(num_pages=1, page_size=(612, 792))
    with PdfDocument(path) as doc:
        image = doc.render_page(0, dpi=150)
        assert image.width() == round(612 / 72 * 150)
        assert image.height() == round(792 / 72 * 150)


def test_render_thumbnail_is_smaller_than_full_page(make_pdf):
    path = make_pdf(num_pages=1)
    with PdfDocument(path) as doc:
        full = doc.render_page(0)
        thumb = doc.render_thumbnail(0)
        assert thumb.width() < full.width()
        assert thumb.height() < full.height()


def test_render_page_index_out_of_range_raises(make_pdf):
    path = make_pdf(num_pages=2)
    with PdfDocument(path) as doc:
        try:
            doc.render_page(5)
        except Exception:
            pass
        else:
            raise AssertionError("expected an exception for an out-of-range page index")


def _page_texts(doc: PdfDocument) -> list[str]:
    return [doc.fitz_document[i].get_text().strip() for i in range(doc.page_count)]


def test_insert_blank_page_shifts_later_pages(make_pdf):
    path = make_pdf(num_pages=3)  # "Page 1", "Page 2", "Page 3"
    with PdfDocument(path) as doc:
        doc.insert_blank_page(1)  # becomes the new page index 1
        assert doc.page_count == 4
        texts = _page_texts(doc)
        assert "Page 1" in texts[0]
        assert texts[1] == ""  # the new blank page
        assert "Page 2" in texts[2]
        assert "Page 3" in texts[3]


def test_insert_blank_page_matches_neighboring_page_size(make_pdf):
    path = make_pdf(num_pages=2, page_size=(500, 700))
    with PdfDocument(path) as doc:
        doc.insert_blank_page(1)
        rect = doc.fitz_document[1].rect
        assert (rect.width, rect.height) == (500, 700)


def test_delete_page_removes_correct_page(make_pdf):
    path = make_pdf(num_pages=3)
    with PdfDocument(path) as doc:
        doc.delete_page(1)  # remove "Page 2"
        assert doc.page_count == 2
        texts = _page_texts(doc)
        assert "Page 1" in texts[0]
        assert "Page 3" in texts[1]


def test_undo_reverts_insert_and_delete(make_pdf):
    path = make_pdf(num_pages=3)
    with PdfDocument(path) as doc:
        doc.insert_blank_page(1)
        assert doc.page_count == 4
        doc.undo()
        assert doc.page_count == 3
        assert [t for t in _page_texts(doc)] == ["Page 1", "Page 2", "Page 3"]

        doc.delete_page(0)
        assert doc.page_count == 2
        doc.undo()
        assert doc.page_count == 3
        assert _page_texts(doc) == ["Page 1", "Page 2", "Page 3"]


def test_redo_reapplies_undone_edit(make_pdf):
    path = make_pdf(num_pages=3)
    with PdfDocument(path) as doc:
        doc.delete_page(1)
        assert doc.page_count == 2
        doc.undo()
        assert doc.page_count == 3
        doc.redo()
        assert doc.page_count == 2
        assert _page_texts(doc) == ["Page 1", "Page 3"]


def test_new_edit_clears_redo_stack(make_pdf):
    path = make_pdf(num_pages=3)
    with PdfDocument(path) as doc:
        doc.delete_page(0)
        doc.undo()
        assert doc.can_redo()

        doc.delete_page(0)  # a fresh edit instead of redoing
        assert not doc.can_redo()


def test_can_undo_and_can_redo_reflect_stack_state(make_pdf):
    path = make_pdf(num_pages=2)
    with PdfDocument(path) as doc:
        assert not doc.can_undo()
        assert not doc.can_redo()

        doc.insert_blank_page(0)
        assert doc.can_undo()
        assert not doc.can_redo()

        doc.undo()
        assert not doc.can_undo()
        assert doc.can_redo()


def test_undo_with_empty_stack_is_a_no_op(make_pdf):
    path = make_pdf(num_pages=2)
    with PdfDocument(path) as doc:
        doc.undo()  # nothing to undo
        assert doc.page_count == 2


def test_editing_does_not_touch_the_file_on_disk(make_pdf):
    path = make_pdf(num_pages=3)
    with PdfDocument(path) as doc:
        doc.delete_page(0)
        doc.insert_blank_page(0)

    # Re-opening the same path fresh must be unaffected by the in-memory edits.
    with PdfDocument(path) as fresh:
        assert fresh.page_count == 3
        assert _page_texts(fresh) == ["Page 1", "Page 2", "Page 3"]
