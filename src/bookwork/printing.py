"""Printing: render an already-imposed `PdfDocument` onto a `QPrinter`.

Kept separate from the actual print dialog / OS print-spooler interaction
(that lives in `main_window.py`) so the rendering logic itself — page range
handling, page size, full-bleed drawing — can be exercised in tests by
pointing a `QPrinter` at a PDF file instead of a real printer or dialog. See
`tests/test_printing.py`.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtGui import QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter

from bookwork.pdf_document import PdfDocument

#: Resolution used to rasterize each page before handing it to the printer.
#: Higher than screen DPI (bookwork.pdf_document.DEFAULT_RENDER_DPI) since
#: this is the actual print output, not an on-screen preview.
PRINT_DPI = 300

#: The imposition pipeline already accounts for margin and the binding
#: gutter itself (see imposition.py) — the printer must not additionally
#: impose its own driver-default page margins on top of that, or content
#: would be pushed off-position. configure_printer_for_sheet_size always
#: pairs setPageSize with setFullPage(True) for this reason.
DEFAULT_DUPLEX_MODE = QPrinter.DuplexMode.DuplexShortSide


def configure_printer_for_sheet_size(printer: QPrinter, width_pt: float, height_pt: float) -> None:
    """Set `printer`'s page size to exactly `width_pt` x `height_pt` (PDF
    points) — the imposed sheet size, not a named paper size — and disable
    the printer driver's own default margins, since the imposed content
    already fills the full sheet (crop marks and all) by design.
    """
    printer.setPageSize(QPageSize(QSizeF(width_pt, height_pt), QPageSize.Unit.Point))
    printer.setFullPage(True)


def print_document(document: PdfDocument, printer: QPrinter) -> None:
    """Render `document`'s pages onto `printer`, honoring whatever page
    range is already configured on it: `printer.printRange()` ==
    `PageRange` uses `printer.fromPage()`..`printer.toPage()` (clamped to
    the document), anything else prints every page.

    Assumes page size / full-page / duplex are already configured on
    `printer` by the caller (see `configure_printer_for_sheet_size`) — this
    function only does the render-and-draw loop.
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
        target = QRectF(printer.pageRect(QPrinter.Unit.DevicePixel))
        for offset, page_number in enumerate(range(first_page, last_page + 1)):
            if offset > 0:
                printer.newPage()
            image = document.render_page(page_number - 1, dpi=PRINT_DPI)
            painter.drawImage(target, image)
    finally:
        painter.end()
