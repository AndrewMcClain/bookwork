"""Tests for bookwork.imposition.

The signature-order expectations below (M=8 and M=20 cases) were captured by
actually running `psbook` (psutils 3.3.14) on generated test PDFs and reading
its output page order — see the design-doc update in the session this was
written. `None` stands in for a blank padding page.
"""

import pymupdf as fitz
import pytest

from bookwork.imposition import (
    ImpositionParams,
    bound_reading_order,
    build_bound_preview,
    compute_signature_order,
    compute_stats,
    impose,
)


def test_signature_order_matches_psbook_s8_two_full_signatures():
    # 16 pages, signature size 8 (2 sheets/signature, 2 signatures, no padding).
    order = compute_signature_order(page_count=16, signature_size_pages=8)
    expected = [
        7, 0, 1, 6, 5, 2, 3, 4,  # pages 8,1,2,7,6,3,4,5 (0-indexed)
        15, 8, 9, 14, 13, 10, 11, 12,  # pages 16,9,10,15,14,11,12,13
    ]
    assert order == expected


def test_signature_order_matches_psbook_s8_with_padding():
    # 20 pages, signature size 8: 2 full signatures + 1 padded (4 real + 4 blank).
    order = compute_signature_order(page_count=20, signature_size_pages=8)
    assert len(order) == 24
    last_signature = order[16:]
    assert last_signature == [None, 16, 17, None, None, 18, 19, None]


def test_signature_order_matches_psbook_s20_single_signature():
    # 20 pages, signature size 20 (1 signature of 5 sheets, no padding needed).
    order = compute_signature_order(page_count=20, signature_size_pages=20)
    expected = [
        19, 0, 1, 18,
        17, 2, 3, 16,
        15, 4, 5, 14,
        13, 6, 7, 12,
        11, 8, 9, 10,
    ]
    assert order == expected


def test_signature_order_matches_psbook_s20_padding_to_full_signature():
    # 25 pages, signature size 20: signature 2 is padded up to a full 20 pages
    # (15 blanks), not just to a multiple of 4.
    order = compute_signature_order(page_count=25, signature_size_pages=20)
    assert len(order) == 40
    second_signature = order[20:]
    assert second_signature.count(None) == 15
    assert [x for x in second_signature if x is not None] == [20, 21, 22, 23, 24]


def test_signature_order_default_signature_size_zero_pads_to_multiple_of_four():
    order = compute_signature_order(page_count=6, signature_size_pages=0)
    assert len(order) == 8
    assert order.count(None) == 2


def test_signature_order_invalid_size_raises():
    with pytest.raises(ValueError):
        compute_signature_order(page_count=10, signature_size_pages=3)


def test_signature_order_empty_document():
    assert compute_signature_order(page_count=0, signature_size_pages=8) == []


def test_imposition_params_rejects_invalid_signature_size():
    with pytest.raises(ValueError):
        ImpositionParams(signature_size_pages=5)


def test_impose_sheet_count(make_pdf):
    path = make_pdf(num_pages=8)
    src = fitz.open(path)
    out = impose(src, ImpositionParams(signature_size_pages=8))
    # 8 pages -> 8 positions -> 4 sheet sides.
    assert out.page_count == 4


def test_impose_pads_partial_signature_with_visible_blanks(make_pdf):
    path = make_pdf(num_pages=6)
    src = fitz.open(path)
    out = impose(src, ImpositionParams(signature_size_pages=8))
    # 6 pages padded to 8 -> order is [blank,1,2,blank,6,3,4,5] -> 4 sheet
    # sides; the first sheet side has a blank left cell and page 1 on the
    # right, and no sheet side ever contains a page number > 6.
    assert out.page_count == 4
    first_side_text = out[0].get_text()
    assert "Page 1" in first_side_text
    assert "Page 2" not in first_side_text  # page 2 is on the next sheet side

    all_text = "".join(p.get_text() for p in out)
    assert "Page 6" in all_text
    for n in range(7, 9):
        assert f"Page {n}" not in all_text


def test_impose_places_pages_in_correct_left_right_cell(make_pdf):
    # Signature of 4 pages: order is 4,1,2,3 -> sheet0 front=(4,1), back=(2,3).
    path = make_pdf(num_pages=4)
    src = fitz.open(path)
    params = ImpositionParams(signature_size_pages=4, margin_pt=10, gutter_pt=0)
    out = impose(src, params)
    assert out.page_count == 2

    cell_boundary = params.sheet_width_pt / 2

    front = out[0]
    rect4 = front.search_for("Page 4")[0]
    rect1 = front.search_for("Page 1")[0]
    assert rect4.x1 <= cell_boundary  # page 4 in the left cell
    assert rect1.x0 >= cell_boundary  # page 1 in the right cell

    back = out[1]
    rect2 = back.search_for("Page 2")[0]
    rect3 = back.search_for("Page 3")[0]
    assert rect2.x1 <= cell_boundary  # page 2 in the left cell
    assert rect3.x0 >= cell_boundary  # page 3 in the right cell


def test_gutter_pushes_content_away_from_spine(make_pdf):
    path = make_pdf(num_pages=4)
    src = fitz.open(path)
    cell_boundary = ImpositionParams().sheet_width_pt / 2

    no_gutter = impose(src, ImpositionParams(signature_size_pages=4, margin_pt=10, gutter_pt=0))
    with_gutter = impose(src, ImpositionParams(signature_size_pages=4, margin_pt=10, gutter_pt=30))

    # Page 4 sits in the left cell, whose spine edge is on the right (at
    # cell_boundary). More gutter should push its content further left,
    # increasing the gap between it and the spine.
    rect_no_gutter = no_gutter[0].search_for("Page 4")[0]
    rect_with_gutter = with_gutter[0].search_for("Page 4")[0]
    assert (cell_boundary - rect_with_gutter.x1) > (cell_boundary - rect_no_gutter.x1)

    # Page 1 sits in the right cell, whose spine edge is on the left (at
    # cell_boundary). More gutter should push its content further right.
    rect1_no_gutter = no_gutter[0].search_for("Page 1")[0]
    rect1_with_gutter = with_gutter[0].search_for("Page 1")[0]
    assert (rect1_with_gutter.x0 - cell_boundary) > (rect1_no_gutter.x0 - cell_boundary)


def test_crop_marks_drawn_by_default(make_pdf):
    path = make_pdf(num_pages=4)
    src = fitz.open(path)
    out = impose(src, ImpositionParams(signature_size_pages=4))
    drawings = out[0].get_drawings()
    assert len(drawings) > 0


def test_crop_marks_stay_within_the_sheet(make_pdf):
    # Marks at the sheet's own outer corners must not extend past the page
    # boundary (there's no bleed area out there to draw into, so anything
    # past the edge would simply be invisible).
    path = make_pdf(num_pages=4)
    src = fitz.open(path)
    out = impose(src, ImpositionParams(signature_size_pages=4))
    page = out[0]
    sheet = page.rect
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            for point in item[1:]:
                if hasattr(point, "x"):
                    assert sheet.x0 <= point.x <= sheet.x1
                    assert sheet.y0 <= point.y <= sheet.y1


def test_crop_marks_can_be_disabled(make_pdf):
    path = make_pdf(num_pages=4)
    src = fitz.open(path)
    out = impose(src, ImpositionParams(signature_size_pages=4, show_crop_marks=False))
    drawings = out[0].get_drawings()
    assert len(drawings) == 0


def test_bound_reading_order_matches_psbook_s8_reference():
    # Verified against real psbook -s8 output for 8 pages: physical order
    # (0-indexed) is [7,0,1,6,5,2,3,4] -> sheets [0,0,1,1,2,2,3,3], cells
    # alternating left,right.
    mapping = bound_reading_order(page_count=8, signature_size_pages=8)
    expected = [
        (0, "right"),  # page 1 (source index 0)
        (1, "left"),  # page 2
        (2, "right"),  # page 3
        (3, "left"),  # page 4
        (3, "right"),  # page 5
        (2, "left"),  # page 6
        (1, "right"),  # page 7
        (0, "left"),  # page 8
    ]
    assert mapping == expected


def test_build_bound_preview_reconstructs_reading_order(make_pdf):
    path = make_pdf(num_pages=8)
    src = fitz.open(path)
    params = ImpositionParams(signature_size_pages=8, margin_pt=10, gutter_pt=10)
    imposed = impose(src, params)

    preview = build_bound_preview(imposed, src_page_count=8, params=params)

    assert preview.page_count == 8
    for i in range(8):
        assert f"Page {i + 1}" in preview[i].get_text()


def test_compute_stats_reports_signatures_and_padding():
    stats = compute_stats(page_count=20, params=ImpositionParams(signature_size_pages=8))
    assert stats.source_page_count == 20
    assert stats.signature_size_pages == 8
    assert stats.signature_count == 3
    assert stats.blank_pages_added == 4
    assert stats.sheet_side_count == 12
    assert stats.physical_sheet_count == 6


def test_compute_stats_no_padding_needed():
    stats = compute_stats(page_count=16, params=ImpositionParams(signature_size_pages=8))
    assert stats.signature_count == 2
    assert stats.blank_pages_added == 0
    assert stats.sheet_side_count == 8
    assert stats.physical_sheet_count == 4


def test_compute_stats_empty_document():
    stats = compute_stats(page_count=0, params=ImpositionParams())
    assert stats.source_page_count == 0
    assert stats.signature_count == 0
    assert stats.sheet_side_count == 0
