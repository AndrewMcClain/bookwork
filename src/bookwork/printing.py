"""Printing: render an already-imposed `PdfDocument` onto a `QPrinter`.

Kept separate from the actual print dialog / OS print-spooler interaction
(that lives in `main_window.py`) so the rendering logic itself — page range
handling, page size, full-bleed drawing — can be exercised in tests by
pointing a `QPrinter` at a PDF file instead of a real printer or dialog. See
`tests/test_printing.py`.
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

    Each page is scaled to fit `printer.pageRect()` — the driver's actual
    reported printable area, not the full nominal sheet — preserving aspect
    ratio and centered, rather than stretched to exactly fill it. On a
    printer with no real hardware margin (or a PDF-format "printer") this is
    a no-op; on real hardware whose margins aren't perfectly symmetric it
    avoids distorting the page to fill a rect shaped slightly differently
    than the sheet itself. Either way, nothing gets clipped.
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
        # printable area's top-left corner — not the raw paper's. pageRect()
        # reports that area's position in absolute paper coordinates (e.g.
        # x=20 for a 20pt left margin); using it directly as the drawing
        # rect double-applies the offset (paint 20pt in, on top of the
        # painter's own 20pt built-in offset), pushing content off the
        # opposite edge by the same amount it was pulled in on this one —
        # confirmed empirically before relying on this. So: only its size.
        page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
        printable_area = QRectF(0, 0, page_rect.width(), page_rect.height())
        for offset, page_number in enumerate(range(first_page, last_page + 1)):
            if offset > 0:
                printer.newPage()
            image = document.render_page(page_number - 1, dpi=PRINT_DPI)
            target = _fit_centered(QSizeF(image.size()), printable_area)
            painter.drawImage(target, image)
    finally:
        painter.end()


def _fit_centered(size: QSizeF, area: QRectF) -> QRectF:
    """`size` scaled to fit within `area` (preserving aspect ratio, never
    enlarged past `area`'s bounds) and centered within it."""
    if size.width() <= 0 or size.height() <= 0 or area.width() <= 0 or area.height() <= 0:
        return area
    scale = min(area.width() / size.width(), area.height() / size.height())
    width = size.width() * scale
    height = size.height() * scale
    x = area.x() + (area.width() - width) / 2
    y = area.y() + (area.height() - height) / 2
    return QRectF(x, y, width, height)
