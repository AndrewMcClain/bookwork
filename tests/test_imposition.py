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
    build_cover_order,
    compute_bound_preview_views,
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


def test_compute_bound_preview_views_first_and_last_page_alone_when_even():
    # 8 pages (even): page 1 alone, spreads (2,3) (4,5) (6,7), page 8 alone.
    assert compute_bound_preview_views(8) == [(0,), (1, 2), (3, 4), (5, 6), (7,)]


def test_compute_bound_preview_views_no_dangling_single_when_odd():
    # 7 pages (odd): page 1 alone, then full spreads all the way through.
    assert compute_bound_preview_views(7) == [(0,), (1, 2), (3, 4), (5, 6)]


def test_compute_bound_preview_views_small_cases():
    assert compute_bound_preview_views(0) == []
    assert compute_bound_preview_views(1) == [(0,)]
    assert compute_bound_preview_views(2) == [(0,), (1,)]
    assert compute_bound_preview_views(3) == [(0,), (1, 2)]


def test_build_bound_preview_reconstructs_reading_order_as_spreads(make_pdf):
    path = make_pdf(num_pages=8)
    src = fitz.open(path)
    params = ImpositionParams(signature_size_pages=8, margin_pt=10, gutter_pt=10)
    imposed = impose(src, params)

    preview = build_bound_preview(imposed, src_page_count=8, params=params)

    # 5 views: [1], [2,3], [4,5], [6,7], [8] — matching how a reader would
    # actually flip through the book (single cover pages, spreads between).
    assert preview.page_count == 5

    assert "Page 1" in preview[0].get_text()
    assert preview[0].rect.width == params.sheet_width_pt / 2  # single-width

    assert "Page 2" in preview[1].get_text()
    assert "Page 3" in preview[1].get_text()
    assert preview[1].rect.width == params.sheet_width_pt  # double-width spread

    assert "Page 4" in preview[2].get_text()
    assert "Page 5" in preview[2].get_text()
    assert "Page 6" in preview[3].get_text()
    assert "Page 7" in preview[3].get_text()

    assert "Page 8" in preview[4].get_text()
    assert preview[4].rect.width == params.sheet_width_pt / 2  # single-width


def test_build_bound_preview_left_right_order_within_a_spread(make_pdf):
    # Within a spread, the lower page number must render on the left.
    path = make_pdf(num_pages=8)
    src = fitz.open(path)
    params = ImpositionParams(signature_size_pages=8, margin_pt=10, gutter_pt=0)
    imposed = impose(src, params)

    preview = build_bound_preview(imposed, src_page_count=8, params=params)

    spread = preview[1]  # pages 2 and 3
    rect2 = spread.search_for("Page 2")[0]
    rect3 = spread.search_for("Page 3")[0]
    assert rect2.x1 <= spread.rect.width / 2
    assert rect3.x0 >= spread.rect.width / 2


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


# --- Endpapers (blank leaves for gluing to a hardcover case) ---
#
# Hand-derived reference for page_count=8, signature_size_pages=8,
# leading_blanks=trailing_blanks=1: content_and_required_blanks = 1+8+1 = 10,
# rounds up to 2 signatures of 8 (16 slots total). Chunk 0 = [blank, p1..p6],
# chunk 1 = [p7, blank, <6 filler blanks>]. Applying the same saddle-stitch
# formula used elsewhere in this file to each chunk gives the physical order
# below (None = blank).


def test_compute_signature_order_with_endpapers():
    order = compute_signature_order(page_count=8, signature_size_pages=8, leading_blanks=1, trailing_blanks=1)
    assert order == [
        6, None, 0, 5, 4, 1, 2, 3,  # chunk 0: [blank,0,1,2,3,4,5,6]
        None, 7, None, None, None, None, None, None,  # chunk 1: [7,blank x7]
    ]


def test_bound_reading_order_with_endpapers_shifts_content_and_leaves_blanks():
    mapping = bound_reading_order(page_count=8, signature_size_pages=8, leading_blanks=1, trailing_blanks=1)
    assert len(mapping) == 16
    assert mapping[0] is None  # leading blank (glued to front case)
    # Content now starts at reading index 1 (page 1), not 0.
    assert mapping[1] == (1, "left")  # page 1
    assert mapping[2] == (2, "right")  # page 2
    assert mapping[8] == (4, "right")  # page 8
    # Trailing filler blanks.
    assert mapping[9:] == [None] * 7


def test_compute_bound_preview_views_with_endpapers_page_one_starts_a_spread():
    # 16 total slots (see above): front blank alone, then page 1 immediately
    # pairs with page 2 — no single-page view for page 1.
    views = compute_bound_preview_views(16)
    assert views[0] == (0,)
    assert views[1] == (1, 2)


def test_build_bound_preview_with_endpapers_end_to_end(make_pdf):
    path = make_pdf(num_pages=8)
    src = fitz.open(path)
    params = ImpositionParams(signature_size_pages=8, include_endpapers=True)
    imposed = impose(src, params)

    preview = build_bound_preview(imposed, src_page_count=8, params=params)

    assert preview.page_count == 9  # [blank],[1,2],[3,4],[5,6],[7,8],[blank,blank],[blank,blank],[blank,blank],[blank]

    # Front cover: blank, alone, single-width.
    assert preview[0].get_text().strip() == ""
    assert preview[0].rect.width == params.sheet_width_pt / 2

    # Page 1 is the LEFT half of the first real spread, not alone.
    spread = preview[1]
    assert "Page 1" in spread.get_text()
    assert "Page 2" in spread.get_text()
    rect1 = spread.search_for("Page 1")[0]
    assert rect1.x1 <= spread.rect.width / 2

    # Last real content page (8) is the left half of a spread, not alone —
    # it's followed by blank filler spreads.
    assert "Page 8" in preview[4].get_text()

    # Back cover: blank, alone, single-width — guaranteed by construction.
    assert preview[-1].get_text().strip() == ""
    assert preview[-1].rect.width == params.sheet_width_pt / 2


def test_compute_stats_accounts_for_endpapers():
    # 8 content pages, signature size 8: with no endpapers this divides
    # evenly (1 signature, no padding). With endpapers, 1+8+1=10 content
    # slots round up to a *second* full 8-page signature (16 slots), adding
    # 8 blanks total (2 endpapers + 6 filler).
    without_endpapers = compute_stats(page_count=8, params=ImpositionParams(signature_size_pages=8))
    assert without_endpapers.blank_pages_added == 0
    assert without_endpapers.signature_count == 1
    assert without_endpapers.sheet_side_count == 4

    with_endpapers = compute_stats(
        page_count=8, params=ImpositionParams(signature_size_pages=8, include_endpapers=True)
    )
    assert with_endpapers.blank_pages_added == 8
    assert with_endpapers.signature_count == 2
    assert with_endpapers.sheet_side_count == 8


# --- Separate wrap cover (first/last page as a single folio) ---
#
# Reference for page_count=10, signature_size_pages=8: interior is the 8
# middle pages (source indices 1..8). Hand-derived by combining
# build_cover_order(0, 9) with compute_signature_order(8, 8, leading_blanks=1,
# trailing_blanks=1) (already verified against real psbook elsewhere in this
# file) shifted by +1, and cross-checked against the function's own output
# during development.


def test_build_cover_order():
    assert build_cover_order(first_index=0, last_index=9) == [9, 0, None, None]


def test_imposition_params_rejects_separate_cover_with_endpapers():
    with pytest.raises(ValueError):
        ImpositionParams(separate_cover=True, include_endpapers=True)


def test_impose_separate_cover_sheet_count(make_pdf):
    path = make_pdf(num_pages=10)
    src = fitz.open(path)
    out = impose(src, ImpositionParams(signature_size_pages=8, separate_cover=True))
    # cover: 2 sheet sides. interior (8 pages + 2 inside-cover blanks = 10,
    # rounds up to 16): 8 sheet sides. Total 10.
    assert out.page_count == 10


def test_impose_separate_cover_outside_spread_layout(make_pdf):
    # Outside cover spread: back cover (page 10) on the left, front cover
    # (page 1) on the right.
    path = make_pdf(num_pages=10)
    src = fitz.open(path)
    params = ImpositionParams(signature_size_pages=8, separate_cover=True, margin_pt=10, gutter_pt=0)
    out = impose(src, params)

    cover_front_sheet = out[0]
    cell_boundary = params.sheet_width_pt / 2
    back_rect = cover_front_sheet.search_for("Page 10")[0]
    # "Page 1" is also a substring of "Page 10", so search_for returns both
    # hits; take the one actually in the right-hand cell.
    front_rect = next(r for r in cover_front_sheet.search_for("Page 1") if r.x0 >= cell_boundary)
    assert back_rect.x1 <= cell_boundary
    assert front_rect.x0 >= cell_boundary

    # Inside cover spread (sheet 1) is blank.
    assert out[1].get_text().strip() == ""


def test_bound_reading_order_separate_cover_matches_hand_derivation():
    mapping = bound_reading_order(10, 8, separate_cover=True)
    assert len(mapping) == 18
    assert mapping[0] == (0, "right")  # cover front (page 1)
    assert mapping[-1] == (0, "left")  # cover back (page 10)
    # Interior: reading slot for source page i (1..8) is i+1.
    assert mapping[2] == (3, "left")  # page 2 (source index 1)
    assert mapping[9] == (6, "right")  # page 9 (source index 8)
    assert mapping[1] is None  # inside-front-cover blank
    assert all(entry is None for entry in mapping[10:17])  # interior filler


def test_compute_bound_preview_views_separate_cover_both_ends_alone():
    views = compute_bound_preview_views(18)
    assert views[0] == (0,)
    assert views[-1] == (17,)
    assert views[1] == (1, 2)


def test_build_bound_preview_separate_cover_end_to_end(make_pdf):
    path = make_pdf(num_pages=10)
    src = fitz.open(path)
    params = ImpositionParams(signature_size_pages=8, separate_cover=True)
    imposed = impose(src, params)

    preview = build_bound_preview(imposed, src_page_count=10, params=params)

    # Front cover alone, single-width.
    assert "Page 1" in preview[0].get_text()
    assert preview[0].rect.width == params.sheet_width_pt / 2

    # Inside-front-cover blank pairs with page 2 (interior's own leading
    # blank) as the first real spread.
    assert preview[1].get_text().strip() == "Page 2"
    rect2 = preview[1].search_for("Page 2")[0]
    assert rect2.x0 >= preview[1].rect.width / 2  # page 2 on the right

    # Back cover alone at the very end, single-width.
    assert "Page 10" in preview[-1].get_text()
    assert preview[-1].rect.width == params.sheet_width_pt / 2


def test_impose_separate_cover_requires_at_least_two_pages(make_pdf):
    path = make_pdf(num_pages=1)
    src = fitz.open(path)
    with pytest.raises(ValueError):
        impose(src, ImpositionParams(separate_cover=True))


def test_compute_stats_separate_cover(make_pdf):
    stats = compute_stats(page_count=10, params=ImpositionParams(signature_size_pages=8, separate_cover=True))
    assert stats.has_separate_cover
    assert stats.cover_physical_sheet_count == 1
    assert stats.signature_count == 2
    assert stats.blank_pages_added == 8
    assert stats.sheet_side_count == 10
    assert stats.physical_sheet_count == 5
