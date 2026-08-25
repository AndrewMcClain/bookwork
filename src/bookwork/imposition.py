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


def compute_signature_order(page_count: int, signature_size_pages: int = 0) -> list[int | None]:
    """Return output positions -> source page index (0-based), or `None` for a
    padding blank, in signature/booklet reading order.

    This mirrors `psbook`'s behavior: pages are split into consecutive chunks
    of `signature_size_pages` (or one chunk covering everything, if 0), each
    chunk padded with blanks up to a full signature length, and each chunk
    reordered with the standard saddle-stitch formula so that printing the
    result 2-up, duplex, and folding once per signature yields correct reading
    order.
    """
    if signature_size_pages < 0:
        raise ValueError("signature_size_pages must be >= 0")
    if signature_size_pages != 0 and signature_size_pages % 4 != 0:
        raise ValueError("signature_size_pages must be 0 or a multiple of 4")
    if page_count <= 0:
        return []

    size = signature_size_pages or _round_up_to_multiple(page_count, 4)
    padded_total = _round_up_to_multiple(page_count, size)

    pages: list[int | None] = list(range(page_count))
    pages.extend([None] * (padded_total - page_count))

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


def impose(src: fitz.Document, params: ImpositionParams | None = None) -> fitz.Document:
    """Build a new document: `src`'s pages reordered into signatures and
    placed 2-up per sheet side, with margin and gutter applied.

    Blank positions (padding pages from `compute_signature_order`) are left
    as blank sheet-side halves — visibly blank in the output, not silently
    dropped, so pagination problems are visible (see DESIGN.md §3.2, §4.1).
    """
    params = params or ImpositionParams()
    order = compute_signature_order(src.page_count, params.signature_size_pages)

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
