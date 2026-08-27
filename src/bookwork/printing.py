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

"""Printing: render an already-imposed `PdfDocument` onto a `QPrinter`.

Kept separate from the actual print dialog / OS print-spooler interaction
(that lives in `main_window.py`) so the rendering logic itself — page range
handling, page size, and fitting the sheet into the printer's real printable
area — can be exercised in tests by pointing a `QPrinter` at a PDF file
instead of a real printer or dialog. See `tests/test_printing.py`.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter

from bookwork.pdf_document import PdfDocument

#: Resolution used to rasterize each page before handing it to the printer.
#: Higher than screen DPI (bookwork.pdf_document.DEFAULT_RENDER_DPI) since
#: this is the actual print output, not an on-screen preview.
PRINT_DPI = 300

DEFAULT_DUPLEX_MODE = QPrinter.DuplexMode.DuplexShortSide


def configure_printer_for_sheet_size(printer: QPrinter, width_pt: float, height_pt: float) -> None:
    """Set `printer`'s page size to exactly `width_pt` x `height_pt` (PDF
    points) — the imposed sheet size, not a named paper size.

    `QPageSize`'s own width/height is always treated as the page's
    *portrait-native* size — `QPrinter`'s separate orientation flag is what
    actually swaps it round for landscape. Passing an already-landscape
    `width_pt > height_pt` straight through leaves that flag at its
    Portrait default: `pageRect()` still ends up the right shape in-app, but
    the orientation *metadata* a real printer driver reads to decide
    physical feed direction says Portrait, and it prints portrait,
    confirmed against a real printer. So: always give `QPageSize` the
    narrower-first (portrait-native) size, and set the orientation flag
    explicitly to match what's actually wanted.

    Deliberately does *not* call `setFullPage(True)`: most real printers
    (confirmed against a real laser printer here) have a hardware-imposed
    unprintable margin around every edge that software can't override —
    forcing "full page" doesn't make the engine able to image there, it
    just makes Qt claim the whole nominal sheet is printable and let the
    driver silently clip whatever falls in its real margin. Leaving this
    unset means `printer.pageRect()` reports the driver's actual printable
    area, which `print_document` fits into — see there.
    """
    is_landscape = width_pt > height_pt
    portrait_width, portrait_height = (height_pt, width_pt) if is_landscape else (width_pt, height_pt)
    printer.setPageSize(QPageSize(QSizeF(portrait_width, portrait_height), QPageSize.Unit.Point))
    printer.setPageOrientation(
        QPageLayout.Orientation.Landscape if is_landscape else QPageLayout.Orientation.Portrait
    )


def print_document(document: PdfDocument, printer: QPrinter) -> None:
    """Render `document`'s pages onto `printer`, honoring whatever page
    range is already configured on it: `printer.printRange()` ==
    `PageRange` uses `printer.fromPage()`..`printer.toPage()` (clamped to
    the document), anything else prints every page.

    Assumes page size / duplex are already configured on `printer` by the
    caller (see `configure_printer_for_sheet_size`) — this function only
    does the render-and-draw loop.

    Each sheet is shrunk to fit whatever the printer can actually image and
    centred on the paper — see `_print_target_rect`.
    """
    if document.page_count == 0:
        return

    first_page, last_page = 1, document.page_count
    if printer.printRange() == QPrinter.PrintRange.PageRange:
        first_page = max(1, printer.fromPage())
        last_page = min(document.page_count, printer.toPage())
        if first_page > last_page:
            first_page, last_page = 1, document.page_count

    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError("Could not start printing (QPainter.begin failed)")
    try:
        # QPainter's own coordinate origin, since setFullPage(True) is never
        # used (see configure_printer_for_sheet_size), is *already* the
        # printable area's top-left corner — not the raw paper's. Both rects
        # below are in absolute paper coordinates; _print_target_rect returns
        # a rect in the painter's, and that offset is how it converts.
        paper = printer.paperRect(QPrinter.Unit.DevicePixel)
        printable = printer.pageRect(QPrinter.Unit.DevicePixel)
        for offset, page_number in enumerate(range(first_page, last_page + 1)):
            if offset > 0:
                printer.newPage()
            image = document.render_page(page_number - 1, dpi=PRINT_DPI)
            target = _print_target_rect(QSizeF(image.size()), PRINT_DPI, paper, printable, printer.resolution())
            painter.drawImage(target, image)
    finally:
        painter.end()


def _print_target_rect(
    image_size_px: QSizeF,
    image_dpi: float,
    paper_px: QRectF,
    printable_px: QRectF,
    printer_dpi: float,
) -> QRectF:
    """Where to draw a full-sheet page image so that it is centred on the
    *paper* and fits inside what the printer can actually image.

    Returned in the painter's coordinates, whose origin is the printable
    area's top-left (see `print_document`).

    Two things this has to get right, and the second is easy to miss.

    **Centred on the paper, not on the printable area.** The spine runs down
    the middle of the sheet, and the sheet is folded along it, so the spine
    has to land on the paper's own centreline or every fold is off centre.
    Printers' hardware margins are routinely asymmetric — the laser printer
    this was developed against reports 16pt at the top and 10pt at the
    bottom — so centring within the printable area silently shifts the sheet
    by half that difference, and pushes it off the opposite edge of the
    paper entirely.

    **Shrunk to fit.** Drawing at native size leaves the sheet's outer edge
    inside the printer's unprintable margin, which is exactly where the crop
    marks are. Marks are what you fold and cut along, so losing them defeats
    their purpose — better a slightly smaller book that can be trimmed
    accurately than a full-size one that cannot. Everything scales together,
    marks included, so cutting on the marks still yields consistent pages.

    Note the scale is bounded by the *larger* margin on each axis, doubled:
    once the sheet is centred on the paper, the tighter side is what limits
    it, and the extra room on the looser side cannot be used without moving
    off centre.

    Kept in physical points except at the very edges (pixels in and out) to
    avoid mixing `image_dpi` and `printer_dpi` pixel spaces, which are
    generally different resolutions.
    """
    px_per_pt = printer_dpi / 72.0
    if px_per_pt <= 0 or image_size_px.width() <= 0 or image_size_px.height() <= 0:
        return QRectF(printable_px.x() * 0, 0, printable_px.width(), printable_px.height())

    sheet_w = image_size_px.width() * (72.0 / image_dpi)
    sheet_h = image_size_px.height() * (72.0 / image_dpi)
    paper_w, paper_h = paper_px.width() / px_per_pt, paper_px.height() / px_per_pt

    left, top = printable_px.x() / px_per_pt, printable_px.y() / px_per_pt
    right = paper_w - left - printable_px.width() / px_per_pt
    bottom = paper_h - top - printable_px.height() / px_per_pt

    usable_w = paper_w - 2 * max(left, right)
    usable_h = paper_h - 2 * max(top, bottom)
    scale = min(1.0, usable_w / sheet_w, usable_h / sheet_h)

    drawn_w, drawn_h = sheet_w * scale, sheet_h * scale
    # Centre on the paper, then express that in the painter's coordinates by
    # subtracting where the printable area starts.
    x = (paper_w - drawn_w) / 2 - left
    y = (paper_h - drawn_h) / 2 - top
    return QRectF(x * px_per_pt, y * px_per_pt, drawn_w * px_per_pt, drawn_h * px_per_pt)
