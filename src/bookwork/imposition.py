"""Signature-order and 2-up imposition, reimplemented natively against PDFs.

This replaces the manual `psbook | psnup` shell pipeline (see DESIGN.md §2, §8)
with plain, testable Python. The signature/booklet reordering algorithm below
was verified against real `psbook` (psutils 3.3.14) output byte-for-byte,
including how it pads a trailing partial signature with blank sides — see
`tests/test_imposition.py`.

Terminology (see DESIGN.md §2.3):
- A "signature" is a group of consecutive pages, printed together and folded
  as one unit. `psbook`'s `-s`/`--signature` option — and this module's
  `signature_size_pages` — count PAGES per signature, not sheets (each sheet
  holds 4 pages: 2 per side). This must be `0` (all pages in one signature)
  or a multiple of 4.
- A "sheet side" holds 2 logical pages side by side (2-up).
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf as fitz

#: 11in x 8.5in, i.e. US Letter fed landscape and split into two 5.5in x 8.5in
#: halves side by side — matches the manual process's target layout.
DEFAULT_SHEET_WIDTH_PT = 792.0
DEFAULT_SHEET_HEIGHT_PT = 612.0

#: Quarter inch.
DEFAULT_MARGIN_PT = 18.0

#: Quarter inch of *additional* inset on the spine-adjacent edge of each cell,
#: on top of the base margin — leaves room for binding.
DEFAULT_GUTTER_PT = 18.0

#: Crop marks: a small "+" drawn at each corner of each cell, marking where
#: that cell's trim boundary (and, for the two inner corners, the fold line)
#: falls. Length of each arm of the cross, and line width/color.
#: Chosen to still read clearly once the page view scales a whole landscape
#: sheet down to fit a normal window (there's no zoom control yet).
CROP_MARK_LENGTH_PT = 10.0
CROP_MARK_WIDTH_PT = 0.75
CROP_MARK_COLOR = (0.3, 0.3, 0.3)


@dataclass(frozen=True)
class ImpositionParams:
    """User-configurable parameters for imposing a document.

    All distances are in PDF points (1/72 inch).
    """

    signature_size_pages: int = 20
    sheet_width_pt: float = DEFAULT_SHEET_WIDTH_PT
    sheet_height_pt: float = DEFAULT_SHEET_HEIGHT_PT
    margin_pt: float = DEFAULT_MARGIN_PT
    gutter_pt: float = DEFAULT_GUTTER_PT
    show_crop_marks: bool = True
    #: Add one real blank page at the very front and one at the very back,
    #: for gluing to a hardcover case (endpapers/pastedowns). Off by default
    #: since it's specific to case binding — the saddle-stitch booklet this
    #: project started from doesn't need it. See `compute_signature_order`'s
    #: `leading_blanks`/`trailing_blanks`.
    include_endpapers: bool = False
    #: Treat the first and last source pages as a separate wrap cover: a
    #: single folio (one folded sheet, printed and often stocked separately
    #: from the interior) whose outside spread shows the back cover on the
    #: left and front cover on the right, with a blank inside spread — and
    #: whose interior is everything else, imposed into its own signature(s)
    #: as usual. Off by default; mutually exclusive with `include_endpapers`
    #: (a case binding's cover *is* the case — it doesn't have its own wrap
    #: folio in this sense). See `build_cover_order`.
    separate_cover: bool = False

    def __post_init__(self) -> None:
        if self.signature_size_pages < 0:
            raise ValueError("signature_size_pages must be >= 0")
        if self.signature_size_pages != 0 and self.signature_size_pages % 4 != 0:
            raise ValueError(
                "signature_size_pages must be 0 (single signature covering the "
                "whole document) or a multiple of 4, matching psbook's own rule"
            )
        if self.sheet_width_pt <= 0 or self.sheet_height_pt <= 0:
            raise ValueError("sheet_width_pt and sheet_height_pt must be > 0")
        if self.margin_pt < 0 or self.gutter_pt < 0:
            raise ValueError("margin_pt and gutter_pt must be >= 0")
        if self.separate_cover and self.include_endpapers:
            raise ValueError(
                "separate_cover and include_endpapers are mutually exclusive "
                "(a case binding's cover doesn't also get a wrap folio)"
            )


def compute_signature_order(
    page_count: int,
    signature_size_pages: int = 0,
    *,
    leading_blanks: int = 0,
    trailing_blanks: int = 0,
) -> list[int | None]:
    """Return output positions -> source page index (0-based), or `None` for a
    blank (padding, or an explicit leading/trailing blank), in
    signature/booklet reading order.

    This mirrors `psbook`'s behavior: pages are split into consecutive chunks
    of `signature_size_pages` (or one chunk covering everything, if 0), each
    chunk padded with blanks up to a full signature length, and each chunk
    reordered with the standard saddle-stitch formula so that printing the
    result 2-up, duplex, and folding once per signature yields correct reading
    order.

    `leading_blanks`/`trailing_blanks` insert that many guaranteed blank
    pages before/after the real content (e.g. `1`/`1` for hardcover endpapers
    — see `ImpositionParams.include_endpapers`) before the usual padding (to
    a full signature length) is added at the tail.
    """
    if signature_size_pages < 0:
        raise ValueError("signature_size_pages must be >= 0")
    if signature_size_pages != 0 and signature_size_pages % 4 != 0:
        raise ValueError("signature_size_pages must be 0 or a multiple of 4")
    if leading_blanks < 0 or trailing_blanks < 0:
        raise ValueError("leading_blanks and trailing_blanks must be >= 0")

    content_and_required_blanks = leading_blanks + max(page_count, 0) + trailing_blanks
    if content_and_required_blanks <= 0:
        return []

    size = signature_size_pages or _round_up_to_multiple(content_and_required_blanks, 4)
    padded_total = _round_up_to_multiple(content_and_required_blanks, size)

    pages: list[int | None] = [None] * leading_blanks
    pages.extend(range(page_count))
    pages.extend([None] * trailing_blanks)
    pages.extend([None] * (padded_total - content_and_required_blanks))

    order: list[int | None] = []
    for start in range(0, padded_total, size):
        order.extend(_signature_block_order(pages[start : start + size]))
    return order


def _round_up_to_multiple(n: int, m: int) -> int:
    return ((n + m - 1) // m) * m


def _signature_block_order(block: list[int | None]) -> list[int | None]:
    """Apply the standard saddle-stitch formula to one signature's pages.

    For a signature of M pages (M a multiple of 4), sheet k (0-based) holds,
    front then back: (M-2k, 1+2k) and (2+2k, M-1-2k) in 1-indexed page
    numbers. Verified against real `psbook` output for M=8 and M=20,
    including padding.
    """
    m = len(block)
    result: list[int | None] = []
    for k in range(m // 4):
        result.append(block[m - 2 * k - 1])
        result.append(block[2 * k])
        result.append(block[2 * k + 1])
        result.append(block[m - 2 * k - 2])
    return result


def build_cover_order(first_index: int, last_index: int) -> list[int | None]:
    """Physical order for a single-folio wrap cover: one sheet, folded once.

    A fixed application of the same saddle-stitch formula used elsewhere in
    this module to the 4-page block `[first, blank, blank, last]`: outside
    spread is (back cover, front cover) = (`last_index`, `first_index`) —
    back on the left, front on the right, matching how a printed cover sheet
    is normally laid out — and the inside spread is blank.
    """
    return [last_index, first_index, None, None]


def _separate_cover_order(page_count: int, signature_size_pages: int) -> list[int | None]:
    """Physical order for the whole document in `separate_cover` mode: a
    fixed 4-slot cover folio (see `build_cover_order`), followed by the
    interior (everything but the first/last page) imposed into its own
    signature(s), with the interior itself getting a leading/trailing blank
    (the inside-cover blanks — reusing the exact mechanism `include_endpapers`
    uses for hardcover endpapers, since the shape is identical).
    """
    if page_count < 2:
        raise ValueError("separate_cover requires at least 2 pages (front and back cover content)")

    first_index, last_index = 0, page_count - 1
    cover_order = build_cover_order(first_index, last_index)

    interior_count = page_count - 2
    interior_relative_order = compute_signature_order(
        interior_count, signature_size_pages, leading_blanks=1, trailing_blanks=1
    )
    # interior_relative_order indexes into the interior alone (0-based from
    # the second source page); shift back to real source indices.
    interior_order: list[int | None] = [
        (index + 1 if index is not None else None) for index in interior_relative_order
    ]
    return cover_order + interior_order


def impose(src: fitz.Document, params: ImpositionParams | None = None) -> fitz.Document:
    """Build a new document: `src`'s pages reordered into signatures and
    placed 2-up per sheet side, with margin and gutter applied.

    Blank positions (padding pages from `compute_signature_order`) are left
    as blank sheet-side halves — visibly blank in the output, not silently
    dropped, so pagination problems are visible (see DESIGN.md §3.2, §4.1).
    """
    params = params or ImpositionParams()
    if params.separate_cover:
        order = _separate_cover_order(src.page_count, params.signature_size_pages)
    else:
        endpaper_count = 1 if params.include_endpapers else 0
        order = compute_signature_order(
            src.page_count,
            params.signature_size_pages,
            leading_blanks=endpaper_count,
            trailing_blanks=endpaper_count,
        )
    return _build_sheets(src, order, params)


def _build_sheets(src: fitz.Document, order: list[int | None], params: ImpositionParams) -> fitz.Document:
    """Place `order` (physical position -> source page index or blank) onto
    2-up sheet sides, margin/gutter/crop-marks applied — the shared final
    step for both the normal and `separate_cover` imposition paths."""
    out = fitz.open()
    cell_width = params.sheet_width_pt / 2

    for i in range(0, len(order), 2):
        left_index = order[i]
        right_index = order[i + 1]
        page = out.new_page(width=params.sheet_width_pt, height=params.sheet_height_pt)
        left_cell = fitz.Rect(0, 0, cell_width, params.sheet_height_pt)
        right_cell = fitz.Rect(cell_width, 0, params.sheet_width_pt, params.sheet_height_pt)
        _place_in_cell(page, src, left_index, left_cell, params, spine_on_right=True)
        _place_in_cell(page, src, right_index, right_cell, params, spine_on_right=False)

        if params.show_crop_marks:
            _draw_crop_marks(page, left_cell)
            _draw_crop_marks(page, right_cell)

    return out


def _place_in_cell(
    page: fitz.Page,
    src: fitz.Document,
    source_page_index: int | None,
    cell: fitz.Rect,
    params: ImpositionParams,
    *,
    spine_on_right: bool,
) -> None:
    """Place one source page (or leave blank) into one half of a sheet.

    The spine runs down the sheet's vertical centerline. `spine_on_right`
    says which edge of `cell` is adjacent to it, so the extra gutter inset
    goes on the correct side — content in the left cell is pushed left (away
    from the spine on its right); content in the right cell is pushed right
    (away from the spine on its left). `Page.show_pdf_page`'s own
    proportional-fit-and-center then handles scale-down and centering within
    whatever rect results, so no separate scale parameter is needed.
    """
    if source_page_index is None:
        return

    x0 = cell.x0 + params.margin_pt
    x1 = cell.x1 - params.margin_pt
    y0 = cell.y0 + params.margin_pt
    y1 = cell.y1 - params.margin_pt

    if spine_on_right:
        x1 -= params.gutter_pt
    else:
        x0 += params.gutter_pt

    target = fitz.Rect(x0, y0, x1, y1)
    page.show_pdf_page(target, src, source_page_index, keep_proportion=True)


def _draw_crop_marks(page: fitz.Page, cell: fitz.Rect) -> None:
    """Draw a small "+" at each of `cell`'s four corners.

    `cell` is the cell's full trim boundary (not the margin-inset content
    area), so the two corners on the spine side mark the fold line (both
    cells share those points exactly, so their marks coincide), and the
    outer two corners mark the sheet's own outer edge.

    Each arm is clamped to the physical sheet (`page.rect`): at the spine
    corners, which sit mid-page, the full "+" is visible; at the sheet's
    outer corners, half of a full "+" would fall outside the sheet and be
    invisible (there's no bleed area beyond the sheet edge to draw into), so
    those become inward-pointing "L" marks instead.
    """
    half = CROP_MARK_LENGTH_PT / 2
    sheet = page.rect
    for x, y in (cell.tl, cell.tr, cell.bl, cell.br):
        x0, x1 = max(sheet.x0, x - half), min(sheet.x1, x + half)
        y0, y1 = max(sheet.y0, y - half), min(sheet.y1, y + half)
        page.draw_line((x0, y), (x1, y), color=CROP_MARK_COLOR, width=CROP_MARK_WIDTH_PT)
        page.draw_line((x, y0), (x, y1), color=CROP_MARK_COLOR, width=CROP_MARK_WIDTH_PT)


def bound_reading_order(
    page_count: int,
    signature_size_pages: int = 0,
    *,
    leading_blanks: int = 0,
    trailing_blanks: int = 0,
    separate_cover: bool = False,
) -> list[tuple[int, str] | None]:
    """Return, for every reading-order slot (0-based — slot 0 is the first
    `leading_blanks` blank page(s), then real page 1, 2, ..., then
    `trailing_blanks` and any further padding blanks), either `(sheet_index,
    side)` — which imposed sheet side (0-based, matching `impose()`'s output
    document) and which cell ("left" or "right") that slot ends up in — or
    `None` for a blank slot.

    This is the inverse of `compute_signature_order`'s physical-position
    mapping, used to reconstruct the book's actual reading order from the
    imposed sheets — see `build_bound_preview`. The returned list's length is
    the full padded page count (`leading_blanks + page_count +
    trailing_blanks`, rounded up to a full signature), not just `page_count`.

    `separate_cover=True` ignores `leading_blanks`/`trailing_blanks` and
    instead builds the composite reading order for a wrap-cover book: cover
    front alone, then the interior's own reading order (which itself starts
    and ends with a blank — the inside-cover blanks), then cover back alone
    — see `_separate_cover_order`/`ImpositionParams.separate_cover`.
    """
    if separate_cover:
        return _bound_reading_order_separate_cover(page_count, signature_size_pages)

    order = compute_signature_order(
        page_count,
        signature_size_pages,
        leading_blanks=leading_blanks,
        trailing_blanks=trailing_blanks,
    )
    result: list[tuple[int, str] | None] = [None] * len(order)
    for physical_position, source_index in enumerate(order):
        if source_index is not None:
            reading_position = leading_blanks + source_index
            side = "left" if physical_position % 2 == 0 else "right"
            result[reading_position] = (physical_position // 2, side)
    return result


def _bound_reading_order_separate_cover(page_count: int, signature_size_pages: int) -> list[tuple[int, str] | None]:
    if page_count < 2:
        raise ValueError("separate_cover requires at least 2 pages (front and back cover content)")

    interior_count = page_count - 2
    interior_mapping = bound_reading_order(
        interior_count, signature_size_pages, leading_blanks=1, trailing_blanks=1
    )

    # The cover folio is always exactly 2 output pages (1 physical sheet);
    # interior sheets follow it in the combined imposed document, so their
    # sheet indices need shifting by that many output pages.
    cover_sheet_page_count = len(build_cover_order(0, 0)) // 2  # == 2, always

    result: list[tuple[int, str] | None] = [None] * (len(interior_mapping) + 2)
    result[0] = (0, "right")  # cover front: build_cover_order puts it at physical position 1
    result[-1] = (0, "left")  # cover back: physical position 0
    for local_index, entry in enumerate(interior_mapping):
        if entry is not None:
            sheet_index, side = entry
            result[1 + local_index] = (sheet_index + cover_sheet_page_count, side)
    return result


#: Thin divider drawn down the middle of a two-page spread view, standing in
#: for the book's spine when it's open.
SPREAD_DIVIDER_COLOR = (0.75, 0.75, 0.75)
SPREAD_DIVIDER_WIDTH_PT = 0.5


def compute_bound_preview_views(slot_count: int) -> list[tuple[int, ...]]:
    """Group reading-order slot indices (0-based; a "slot" is a page,
    possibly blank — see `bound_reading_order`) into the views a reader
    would actually flip through: the first slot alone (its "verso" is the
    inside front cover, which doesn't exist as a page), then two-page
    spreads — e.g. (1,2), (3,4) — and, if `slot_count` is even, a final
    single slot alone (its "recto" would be the inside back cover).

    Without explicit leading/trailing blanks (see `ImpositionParams.
    include_endpapers`), `slot_count` is just the real page count and the
    trailing single is only there when that count is even. With them,
    `slot_count` is always a multiple of 4 (`compute_signature_order`
    rounds up to a full signature), so removing the first slot always
    leaves an odd remainder — the trailing single is then unconditionally
    guaranteed, and it's always the blank endpaper.
    """
    if slot_count <= 0:
        return []
    views: list[tuple[int, ...]] = [(0,)]
    i = 1
    while i < slot_count:
        if i + 1 < slot_count:
            views.append((i, i + 1))
            i += 2
        else:
            views.append((i,))
            i += 1
    return views


def build_bound_preview(imposed: fitz.Document, src_page_count: int, params: ImpositionParams) -> fitz.Document:
    """Reconstruct what a reader would actually see flipping through the
    bound book: single-page views at the front/back cover, two-page spreads
    everywhere else — by cropping each page's cell back out of the
    already-imposed sheets (see `compute_bound_preview_views`).

    Unlike re-rendering from the original source, this shows each page
    exactly as it will appear once printed and folded — including the
    margin/gutter shift and any crop marks — so a pagination mistake (an
    off-by-one, a swapped signature, misaligned spread, ...) shows up
    visually exactly as a reader would encounter it, instead of requiring
    the sheet order in the Imposed tab to be mentally folded/unfolded.
    """
    if params.separate_cover:
        mapping = bound_reading_order(src_page_count, params.signature_size_pages, separate_cover=True)
    else:
        endpaper_count = 1 if params.include_endpapers else 0
        mapping = bound_reading_order(
            src_page_count,
            params.signature_size_pages,
            leading_blanks=endpaper_count,
            trailing_blanks=endpaper_count,
        )
    cell_width = params.sheet_width_pt / 2
    cell_height = params.sheet_height_pt

    out = fitz.open()
    for view in compute_bound_preview_views(len(mapping)):
        if len(view) == 1:
            page = out.new_page(width=cell_width, height=cell_height)
            _copy_cell(page, imposed, mapping[view[0]], fitz.Rect(0, 0, cell_width, cell_height), cell_width)
        else:
            left_index, right_index = view
            page = out.new_page(width=cell_width * 2, height=cell_height)
            _copy_cell(page, imposed, mapping[left_index], fitz.Rect(0, 0, cell_width, cell_height), cell_width)
            _copy_cell(
                page,
                imposed,
                mapping[right_index],
                fitz.Rect(cell_width, 0, cell_width * 2, cell_height),
                cell_width,
            )
            page.draw_line(
                (cell_width, 0),
                (cell_width, cell_height),
                color=SPREAD_DIVIDER_COLOR,
                width=SPREAD_DIVIDER_WIDTH_PT,
            )
    return out


def _copy_cell(
    page: fitz.Page,
    imposed: fitz.Document,
    mapping_entry: tuple[int, str] | None,
    target_rect: fitz.Rect,
    cell_width: float,
) -> None:
    """Crop one page's cell out of the imposed sheets and place it at
    `target_rect` on a bound-preview page. `None` (a blank slot) leaves that
    area of the page blank."""
    if mapping_entry is None:
        return
    sheet_index, side = mapping_entry
    source_cell = (
        fitz.Rect(0, 0, cell_width, target_rect.height)
        if side == "left"
        else fitz.Rect(cell_width, 0, cell_width * 2, target_rect.height)
    )
    page.show_pdf_page(target_rect, imposed, sheet_index, clip=source_cell)


@dataclass(frozen=True)
class ImpositionStats:
    """Summary numbers about an imposition run, for display in the UI."""

    source_page_count: int
    signature_size_pages: int  # 0 means "single signature covering everything"
    signature_count: int  # interior signature count, when has_separate_cover
    blank_pages_added: int
    sheet_side_count: int  # number of pages in the Imposed output document
    physical_sheet_count: int  # sheet_side_count / 2 (front + back per sheet)
    has_separate_cover: bool = False
    cover_physical_sheet_count: int = 0  # always 1 when has_separate_cover


def compute_stats(page_count: int, params: ImpositionParams) -> ImpositionStats:
    if page_count <= 0:
        return ImpositionStats(0, params.signature_size_pages, 0, 0, 0, 0)

    if params.separate_cover:
        return _compute_stats_separate_cover(page_count, params)

    endpaper_count = 1 if params.include_endpapers else 0
    content_and_required_blanks = endpaper_count + page_count + endpaper_count
    size = params.signature_size_pages or _round_up_to_multiple(content_and_required_blanks, 4)
    padded_total = _round_up_to_multiple(content_and_required_blanks, size)
    sheet_side_count = padded_total // 2

    return ImpositionStats(
        source_page_count=page_count,
        signature_size_pages=params.signature_size_pages,
        signature_count=padded_total // size,
        blank_pages_added=padded_total - page_count,
        sheet_side_count=sheet_side_count,
        physical_sheet_count=sheet_side_count // 2,
    )


def _compute_stats_separate_cover(page_count: int, params: ImpositionParams) -> ImpositionStats:
    if page_count < 2:
        # Not enough pages for a front/back cover; report zeros rather than
        # raising here — impose()/build_bound_preview raise when actually run.
        return ImpositionStats(page_count, params.signature_size_pages, 0, 0, 0, 0, has_separate_cover=True)

    interior_count = page_count - 2
    content_and_required_blanks = 1 + interior_count + 1  # inside-cover blanks
    size = params.signature_size_pages or _round_up_to_multiple(content_and_required_blanks, 4)
    interior_padded_total = _round_up_to_multiple(content_and_required_blanks, size)
    interior_sheet_sides = interior_padded_total // 2

    cover_sheet_sides = 2  # 1 physical sheet, front + back
    total_sheet_sides = cover_sheet_sides + interior_sheet_sides

    return ImpositionStats(
        source_page_count=page_count,
        signature_size_pages=params.signature_size_pages,
        signature_count=interior_padded_total // size,
        # interior_padded_total already accounts for the 2 inside-cover
        # blanks (folded into content_and_required_blanks above) plus any
        # further filler padding needed to complete the last signature.
        blank_pages_added=interior_padded_total - interior_count,
        sheet_side_count=total_sheet_sides,
        physical_sheet_count=total_sheet_sides // 2,
        has_separate_cover=True,
        cover_physical_sheet_count=1,
    )
