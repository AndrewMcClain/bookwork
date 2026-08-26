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


def print_document(document: PdfDocument, printer: QPrinter, *, margin_pt: float = 0.0) -> None:
    """Render `document`'s pages onto `printer`, honoring whatever page
    range is already configured on it: `printer.printRange()` ==
    `PageRange` uses `printer.fromPage()`..`printer.toPage()` (clamped to
    the document), anything else prints every page.

    Assumes page size / duplex are already configured on `printer` by the
    caller (see `configure_printer_for_sheet_size`) — this function only
    does the render-and-draw loop.

    Each page is drawn at its native size (matching the sheet exactly — no
    scaling) unless the printer's actual printable area is too small to fit
    even the *content* — the region inset by `margin_pt` from the sheet's
    outer edges, which is where `imposition.py` guarantees real page
    content stays clear of (crop marks, by contrast, sit right at that
    outer edge by design). Content is centered within the printable area
    and never clipped; on a printer whose hardware margin exceeds
    `margin_pt`, the crop marks nearest the affected edge(s) may end up
    slightly clipped instead — an explicit, deliberate tradeoff, not a bug.
    Pass `margin_pt=0` to fall back to always shrinking to fit exactly (the
    old behavior, appropriate if there's no known content-safe margin).
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
        printer_dpi = printer.resolution()
        for offset, page_number in enumerate(range(first_page, last_page + 1)):
            if offset > 0:
                printer.newPage()
            image = document.render_page(page_number - 1, dpi=PRINT_DPI)
            target = _print_target_rect(QSizeF(image.size()), PRINT_DPI, margin_pt, printable_area, printer_dpi)
            painter.drawImage(target, image)
    finally:
        painter.end()


def _print_target_rect(
    image_size_px: QSizeF,
    image_dpi: float,
    margin_pt: float,
    printable_area_px: QRectF,
    printer_dpi: float,
) -> QRectF:
    """Where to draw a full-sheet page image (`image_size_px`, rendered at
    `image_dpi`) within `printable_area_px` (in the printer's own device
    pixels, at `printer_dpi`) so that the sheet's margin-inset *content*
    region — inset by `margin_pt` from each outer edge — is guaranteed to
    end up fully inside `printable_area_px`, scaling down from native size
    only if that region wouldn't otherwise fit. The sheet's own outer edge
    (and any crop marks there) may still end up outside `printable_area_px`
    and thus clipped — that's the point: only real content is protected.

    Kept in physical points throughout except at the very start/end (pixel
    counts in and out) specifically to avoid mixing `image_dpi` and
    `printer_dpi` pixel spaces, which are generally different resolutions —
    e.g. a page rendered at 300 DPI placed on a 1200 DPI printer device.
    """
    sheet_width_pt = image_size_px.width() * (72.0 / image_dpi)
    sheet_height_pt = image_size_px.height() * (72.0 / image_dpi)

    px_per_pt_printer = printer_dpi / 72.0
    printable_width_pt = printable_area_px.width() / px_per_pt_printer
    printable_height_pt = printable_area_px.height() / px_per_pt_printer

    safe_width_pt = sheet_width_pt - 2 * margin_pt
    safe_height_pt = sheet_height_pt - 2 * margin_pt

    scale = 1.0
    if safe_width_pt > 0 and printable_width_pt < safe_width_pt:
        scale = min(scale, printable_width_pt / safe_width_pt)
    if safe_height_pt > 0 and printable_height_pt < safe_height_pt:
        scale = min(scale, printable_height_pt / safe_height_pt)

    target_width_px = sheet_width_pt * scale * px_per_pt_printer
    target_height_px = sheet_height_pt * scale * px_per_pt_printer
    x = printable_area_px.x() + (printable_area_px.width() - target_width_px) / 2
    y = printable_area_px.y() + (printable_area_px.height() - target_height_px) / 2
    return QRectF(x, y, target_width_px, target_height_px)
