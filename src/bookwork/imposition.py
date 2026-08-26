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

"""Signature-order and 2-up imposition, reimplemented natively against PDFs.

This replaces the manual `psbook | psnup` shell pipeline (see docs/background.md)
with plain, testable Python. The signature/booklet reordering algorithm below
was verified against real `psbook` (psutils 3.3.14) output byte-for-byte,
including how it pads a trailing partial signature with blank sides — see
`tests/test_imposition.py`.

Terminology (see docs/design.md):
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

#: Crop marks: a small outward-pointing L-shaped tick drawn at each corner
#: of the actual placed page content, marking where to trim it down to —
#: see `_draw_crop_marks`. Length of each arm, and line width/color. Chosen
#: to still read clearly once the page view scales a whole landscape sheet
#: down to fit a normal window (there's no zoom control yet).
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
    #: When the content doesn't divide evenly into `signature_size_pages`,
    #: the default is to pad the trailing partial signature only up to the
    #: next multiple of 4 (the physical minimum — see
    #: `_signature_block_order`), not all the way up to a full
    #: `signature_size_pages`, to avoid wasting blank pages/sheets — e.g. a
    #: 4-page document with a 20-page signature size prints on 1 sheet
    #: instead of 5. Setting `pad_last_signature_to_full=True` forces every
    #: signature to the same full length instead (matching psbook's own
    #: behavior), trading that savings for uniformity. No effect when
    #: `signature_size_pages` is 0 (a single signature already only pads to
    #: a multiple of 4). See `_chunk_sizes`.
    pad_last_signature_to_full: bool = False

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
    pad_last_signature_to_full: bool = False,
) -> list[int | None]:
    """Return output positions -> source page index (0-based), or `None` for a
    blank (padding, or an explicit leading/trailing blank), in
    signature/booklet reading order.

    This mirrors `psbook`'s behavior: pages are split into consecutive chunks
    of `signature_size_pages` (or one chunk covering everything, if 0), each
    chunk reordered with the standard saddle-stitch formula so that printing
    the result 2-up, duplex, and folding once per signature yields correct
    reading order.

    `leading_blanks`/`trailing_blanks` insert that many guaranteed blank
    pages before/after the real content (e.g. `1`/`1` for hardcover endpapers
    — see `ImpositionParams.include_endpapers`) before the usual trailing
    padding.

    By default, a trailing partial signature is padded only up to the next
    multiple of 4 (the physical minimum), not all the way to a full
    `signature_size_pages` — pass `pad_last_signature_to_full=True` to force
    every signature to the same full length instead (matching psbook's own
    behavior) — see `ImpositionParams.pad_last_signature_to_full` and
    `_chunk_sizes`.
    """
    if signature_size_pages < 0:
        raise ValueError("signature_size_pages must be >= 0")
    if signature_size_pages != 0 and signature_size_pages % 4 != 0:
        raise ValueError("signature_size_pages must be 0 or a multiple of 4")
    if leading_blanks < 0 or trailing_blanks < 0:
        raise ValueError("leading_blanks and trailing_blanks must be >= 0")

    content_and_required_blanks = leading_blanks + max(page_count, 0) + trailing_blanks
    chunk_sizes = _chunk_sizes(content_and_required_blanks, signature_size_pages, pad_last_signature_to_full)
    if not chunk_sizes:
        return []
    padded_total = sum(chunk_sizes)

    pages: list[int | None] = [None] * leading_blanks
    pages.extend(range(page_count))
    pages.extend([None] * trailing_blanks)
    pages.extend([None] * (padded_total - content_and_required_blanks))

    order: list[int | None] = []
    start = 0
    for chunk_size in chunk_sizes:
        order.extend(_signature_block_order(pages[start : start + chunk_size]))
        start += chunk_size
    return order


def _chunk_sizes(total: int, signature_size_pages: int, pad_last_signature_to_full: bool) -> list[int]:
    """The length of each signature (always a multiple of 4) needed to
    cover `total` pages (real content plus any required leading/trailing
    blanks).

    - `signature_size_pages == 0`: one signature, padded to a multiple of 4
      (there's no "last signature" distinct from the rest, so
      `pad_last_signature_to_full` has no effect).
    - Otherwise, as many full `signature_size_pages`-length signatures as
      fit, plus — if there's a nonzero remainder — one more signature for
      it: by default just padded up to the next multiple of 4 (fewer wasted
      blank pages), or the full `signature_size_pages`
      (`pad_last_signature_to_full=True`, uniform, matching psbook's own
      behavior).
    """
    if total <= 0:
        return []
    if signature_size_pages == 0:
        return [_round_up_to_multiple(total, 4)]

    full_count, remainder = divmod(total, signature_size_pages)
    if remainder == 0:
        return [signature_size_pages] * full_count
    last_size = signature_size_pages if pad_last_signature_to_full else _round_up_to_multiple(remainder, 4)
    return [signature_size_pages] * full_count + [last_size]


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


#: A wrap cover folio is always exactly one physical sheet — 4 page slots
#: (see `build_cover_order`), i.e. 2 sheet sides — sitting in front of the
#: interior's own signature(s) in the imposed document.
_COVER_SHEET_SIDES = 2


@dataclass(frozen=True)
class _SignatureLayout:
    """`ImpositionParams` resolved against a source page count into the
    concrete arguments every signature-order caller actually needs.

    `impose`, `build_bound_preview`, and `compute_stats` all need this same
    derivation. Single-sourcing it here is deliberate: if the `impose` and
    `build_bound_preview` copies ever drifted, the Bound Preview tab would
    show a different pagination than the sheets that actually print — which
    is exactly the off-by-one class of mistake that tab exists to catch. It
    also means a newly added `ImpositionParams` field reaches every caller
    by editing one place rather than four.
    """

    #: Pages handed to `compute_signature_order`. In `separate_cover` mode
    #: this is the *interior* only — the first and last source pages are
    #: pulled out into the cover folio instead.
    page_count: int
    signature_size_pages: int
    leading_blanks: int
    trailing_blanks: int
    pad_last_signature_to_full: bool
    #: First/last source page form a wrap cover folio, prepended to the
    #: interior's own signature(s). See `build_cover_order`.
    separate_cover: bool

    @classmethod
    def resolve(cls, params: ImpositionParams, source_page_count: int) -> "_SignatureLayout":
        if params.separate_cover:
            return cls.for_separate_cover(
                source_page_count, params.signature_size_pages, params.pad_last_signature_to_full
            )
        endpaper_count = 1 if params.include_endpapers else 0
        return cls(
            page_count=source_page_count,
            signature_size_pages=params.signature_size_pages,
            leading_blanks=endpaper_count,
            trailing_blanks=endpaper_count,
            pad_last_signature_to_full=params.pad_last_signature_to_full,
            separate_cover=False,
        )

    @classmethod
    def for_separate_cover(
        cls, source_page_count: int, signature_size_pages: int, pad_last_signature_to_full: bool
    ) -> "_SignatureLayout":
        """The `separate_cover` rule in one place: the first and last source
        pages become the cover folio, and the interior gets a leading and a
        trailing blank of its own (the inside-cover blanks) — reusing the
        exact mechanism `include_endpapers` uses for hardcover endpapers,
        since the shape is identical.
        """
        if source_page_count < 2:
            raise ValueError("separate_cover requires at least 2 pages (front and back cover content)")
        return cls(
            page_count=source_page_count - 2,
            signature_size_pages=signature_size_pages,
            leading_blanks=1,
            trailing_blanks=1,
            pad_last_signature_to_full=pad_last_signature_to_full,
            separate_cover=True,
        )

    def chunk_sizes(self) -> list[int]:
        """Page count of each signature the interior is split into."""
        return _chunk_sizes(
            self.leading_blanks + self.page_count + self.trailing_blanks,
            self.signature_size_pages,
            self.pad_last_signature_to_full,
        )

    def _interior_signature_order(self) -> list[int | None]:
        return compute_signature_order(
            self.page_count,
            self.signature_size_pages,
            leading_blanks=self.leading_blanks,
            trailing_blanks=self.trailing_blanks,
            pad_last_signature_to_full=self.pad_last_signature_to_full,
        )

    def physical_order(self) -> list[int | None]:
        """Output position -> source page index (or `None` for a blank),
        including the cover folio up front when `separate_cover`."""
        interior_order = self._interior_signature_order()
        if not self.separate_cover:
            return interior_order
        # interior_order indexes into the interior alone (0-based from the
        # second source page); shift back to real source indices.
        shifted: list[int | None] = [None if index is None else index + 1 for index in interior_order]
        last_source_index = self.page_count + 1  # source_page_count - 1
        return build_cover_order(0, last_source_index) + shifted

    def reading_order(self) -> list[tuple[int, str] | None]:
        """Reading-order slot -> `(sheet_index, side)`, or `None` for a
        blank slot — the inverse of `physical_order`. See
        `bound_reading_order`, which is this exposed as public API."""
        order = self._interior_signature_order()
        interior_mapping: list[tuple[int, str] | None] = [None] * len(order)
        for physical_position, source_index in enumerate(order):
            if source_index is not None:
                reading_position = self.leading_blanks + source_index
                side = "left" if physical_position % 2 == 0 else "right"
                interior_mapping[reading_position] = (physical_position // 2, side)

        if not self.separate_cover:
            return interior_mapping

        # Interior sheets follow the cover folio in the combined imposed
        # document, so their sheet indices shift past it.
        result: list[tuple[int, str] | None] = [None] * (len(interior_mapping) + 2)
        result[0] = (0, "right")  # cover front: build_cover_order puts it at physical position 1
        result[-1] = (0, "left")  # cover back: physical position 0
        for local_index, entry in enumerate(interior_mapping):
            if entry is not None:
                sheet_index, side = entry
                result[1 + local_index] = (sheet_index + _COVER_SHEET_SIDES, side)
        return result


def impose(src: fitz.Document, params: ImpositionParams | None = None) -> fitz.Document:
    """Build a new document: `src`'s pages reordered into signatures and
    placed 2-up per sheet side, with margin and gutter applied.

    Blank positions (padding pages from `compute_signature_order`) are left
    as blank sheet-side halves — visibly blank in the output, not silently
    dropped, so pagination problems are visible (see docs/design.md).
    """
    params = params or ImpositionParams()
    order = _SignatureLayout.resolve(params, src.page_count).physical_order()
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
        left_content_rect = _place_in_cell(page, src, left_index, left_cell, params, spine_on_right=True)
        right_content_rect = _place_in_cell(page, src, right_index, right_cell, params, spine_on_right=False)

        if params.show_crop_marks:
            _draw_crop_marks(page, left_content_rect)
            _draw_crop_marks(page, right_content_rect)

    return out


def _place_in_cell(
    page: fitz.Page,
    src: fitz.Document,
    source_page_index: int | None,
    cell: fitz.Rect,
    params: ImpositionParams,
    *,
    spine_on_right: bool,
) -> fitz.Rect:
    """Place one source page (or leave blank) into one half of a sheet.

    The spine runs down the sheet's vertical centerline. `spine_on_right`
    says which edge of `cell` is adjacent to it, so the extra gutter inset
    goes on the correct side — content in the left cell is pushed left (away
    from the spine on its right); content in the right cell is pushed right
    (away from the spine on its left). `Page.show_pdf_page`'s own
    proportional-fit-and-center then handles scale-down and centering within
    whatever rect results, so no separate scale parameter is needed.

    Returns the rect the page's content actually ends up occupying (or, for
    a blank cell, the intended target rect) — see `_fitted_content_rect` and
    `_draw_crop_marks`. This is *not* necessarily `target` below: if the
    source page's aspect ratio doesn't match `target`'s, `keep_proportion`
    shrinks it further and centers it, leaving asymmetric blank space.
    """
    x0 = cell.x0 + params.margin_pt
    x1 = cell.x1 - params.margin_pt
    y0 = cell.y0 + params.margin_pt
    y1 = cell.y1 - params.margin_pt

    if spine_on_right:
        x1 -= params.gutter_pt
    else:
        x0 += params.gutter_pt

    target = fitz.Rect(x0, y0, x1, y1)
    if source_page_index is None:
        return target

    page.show_pdf_page(target, src, source_page_index, keep_proportion=True)
    return _fitted_content_rect(src[source_page_index].rect, target)


def _fitted_content_rect(source_rect: fitz.Rect, target: fitz.Rect) -> fitz.Rect:
    """The rect `source_rect` actually ends up occupying within `target` when
    placed via `show_pdf_page(target, ..., keep_proportion=True)`: scaled to
    fit (preserving aspect ratio) and centered. Reproduces PyMuPDF's own
    placement math so crop marks can be drawn at the *real* content edge
    rather than `target`'s — verified empirically to match exactly.
    """
    if source_rect.width <= 0 or source_rect.height <= 0 or target.width <= 0 or target.height <= 0:
        return target
    scale = min(target.width / source_rect.width, target.height / source_rect.height)
    width = source_rect.width * scale
    height = source_rect.height * scale
    x0 = target.x0 + (target.width - width) / 2
    y0 = target.y0 + (target.height - height) / 2
    return fitz.Rect(x0, y0, x0 + width, y0 + height)


def _draw_crop_marks(page: fitz.Page, content_rect: fitz.Rect) -> None:
    """Draw a small L-shaped tick at each of `content_rect`'s four corners,
    marking where to trim down to the real edge of the placed page content
    — not a fixed nominal boundary, which (per `_place_in_cell`) may not
    match it if the source page's aspect ratio leaves it scaled smaller and
    centered.

    Each tick's two arms point *outward* only — away from the content, into
    the surrounding blank margin — meeting the content rect at exactly one
    point (that corner) rather than crossing into it. A "+" centered on the
    corner would have half of each arm sitting on top of the actual page
    content; trimming exactly along the mark would then leave ink from it on
    the finished, cut-down page. An outward-only tick can't do that.

    Each arm is clamped to the physical sheet (`page.rect`): there's no
    bleed area beyond the sheet's own edge to draw into, so a tick whose
    content rect happens to sit exactly at that edge is simply shorter
    there rather than drawn off-page and invisible.
    """
    length = CROP_MARK_LENGTH_PT
    sheet = page.rect
    corners_and_outward_directions = (
        (content_rect.tl, -1, -1),
        (content_rect.tr, 1, -1),
        (content_rect.bl, -1, 1),
        (content_rect.br, 1, 1),
    )
    for (x, y), dx, dy in corners_and_outward_directions:
        x_end = min(max(x + dx * length, sheet.x0), sheet.x1)
        y_end = min(max(y + dy * length, sheet.y0), sheet.y1)
        page.draw_line((x, y), (x_end, y), color=CROP_MARK_COLOR, width=CROP_MARK_WIDTH_PT)
        page.draw_line((x, y), (x, y_end), color=CROP_MARK_COLOR, width=CROP_MARK_WIDTH_PT)


def bound_reading_order(
    page_count: int,
    signature_size_pages: int = 0,
    *,
    leading_blanks: int = 0,
    trailing_blanks: int = 0,
    separate_cover: bool = False,
    pad_last_signature_to_full: bool = False,
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
    — see `_SignatureLayout.for_separate_cover` and
    `ImpositionParams.separate_cover`.
    """
    if separate_cover:
        layout = _SignatureLayout.for_separate_cover(
            page_count, signature_size_pages, pad_last_signature_to_full
        )
    else:
        layout = _SignatureLayout(
            page_count=page_count,
            signature_size_pages=signature_size_pages,
            leading_blanks=leading_blanks,
            trailing_blanks=trailing_blanks,
            pad_last_signature_to_full=pad_last_signature_to_full,
            separate_cover=False,
        )
    return layout.reading_order()


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
    mapping = _SignatureLayout.resolve(params, src_page_count).reading_order()
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
    #: The actual page count of each signature, in order (e.g. `(20, 20, 4)`
    #: for 5→3 full 20-page signatures plus a shorter last one) — the
    #: interior's own signatures when has_separate_cover, not counting the
    #: cover folio. See `_chunk_sizes` and `describe_signature_sizes`.
    signature_sizes: tuple[int, ...] = ()


def compute_stats(page_count: int, params: ImpositionParams) -> ImpositionStats:
    if page_count <= 0:
        return ImpositionStats(0, params.signature_size_pages, 0, 0, 0, 0)
    if params.separate_cover and page_count < 2:
        # Not enough pages for a front/back cover; report zeros rather than
        # raising here — impose()/build_bound_preview raise when actually run.
        return ImpositionStats(page_count, params.signature_size_pages, 0, 0, 0, 0, has_separate_cover=True)

    layout = _SignatureLayout.resolve(params, page_count)
    chunk_sizes = layout.chunk_sizes()
    interior_padded_total = sum(chunk_sizes)
    total_sheet_sides = interior_padded_total // 2
    if layout.separate_cover:
        total_sheet_sides += _COVER_SHEET_SIDES

    return ImpositionStats(
        source_page_count=page_count,
        signature_size_pages=params.signature_size_pages,
        signature_count=len(chunk_sizes),
        # interior_padded_total covers the leading/trailing blanks (endpapers
        # or inside-cover blanks) plus any filler needed to complete the last
        # signature; layout.page_count is the real content those were added
        # around — the interior only, in separate_cover mode.
        blank_pages_added=interior_padded_total - layout.page_count,
        sheet_side_count=total_sheet_sides,
        physical_sheet_count=total_sheet_sides // 2,
        has_separate_cover=layout.separate_cover,
        cover_physical_sheet_count=1 if layout.separate_cover else 0,
        signature_sizes=tuple(chunk_sizes),
    )


def describe_signature_sizes(sizes: tuple[int, ...]) -> str:
    """A human-readable breakdown of `ImpositionStats.signature_sizes`, e.g.
    "20 pages/signature, 5 full signatures + 1 signature of 4 pages" when
    the last signature is shorter, or "20 pages/signature, 3 signatures"
    when they're all the same length.
    """
    if not sizes:
        return "0 signatures"

    if len(set(sizes)) == 1:
        size = sizes[0]
        count = len(sizes)
        return f"{size} pages/signature, {count} signature{'s' if count != 1 else ''}"

    # _chunk_sizes only ever produces at most one differently-sized chunk,
    # and it's always the last one.
    full_size = sizes[0]
    full_count = sum(1 for size in sizes if size == full_size)
    last_size = sizes[-1]
    full_word = f"full signature{'s' if full_count != 1 else ''}"
    return f"{full_size} pages/signature, {full_count} {full_word} + 1 signature of {last_size} pages"
