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
