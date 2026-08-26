"""Tests for bookwork.printing.

These never touch a real printer or open a print dialog: QPrinter is pointed
at PdfFormat + a temp file path, which exercises the exact same QPainter/
QPrinter rendering code a real print job would use, just captured as a PDF
we can inspect with pymupdf instead of sent to a spooler.
"""

from __future__ import annotations

import os

import pymupdf as fitz
import pytest
from PySide6.QtCore import QMarginsF, QRectF, QSizeF
from PySide6.QtGui import QPageLayout
from PySide6.QtPrintSupport import QPrinter

from bookwork.pdf_document import PdfDocument
from bookwork.printing import _fit_centered, configure_printer_for_sheet_size, print_document


def _make_printer(tmp_path, width_pt: float = 792.0, height_pt: float = 612.0) -> tuple[QPrinter, str]:
    out_path = str(tmp_path / "printed.pdf")
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(out_path)
    configure_printer_for_sheet_size(printer, width_pt, height_pt)
    return printer, out_path


def test_print_document_all_pages(qtbot, make_pdf, tmp_path):
    src_path = make_pdf(num_pages=4, page_size=(792, 612))
    document = PdfDocument(src_path)
    printer, out_path = _make_printer(tmp_path)

    print_document(document, printer)

    result = fitz.open(out_path)
    assert result.page_count == 4


def test_print_document_page_size_matches_sheet(qtbot, make_pdf, tmp_path):
    src_path = make_pdf(num_pages=1, page_size=(792, 612))
    document = PdfDocument(src_path)
    printer, out_path = _make_printer(tmp_path, width_pt=792.0, height_pt=612.0)

    print_document(document, printer)

    result = fitz.open(out_path)
    page_rect = result[0].rect
    assert page_rect.width == pytest.approx(792.0, abs=1.0)
    assert page_rect.height == pytest.approx(612.0, abs=1.0)


def test_configure_printer_sets_landscape_orientation_metadata(qtbot):
    # The actual bug: pageRect() came out the right shape either way, but a
    # real printer driver reads the orientation *metadata* (not just the
    # raw page rect) to decide physical feed direction -- confirmed against
    # a real printer to matter, not just a Qt-internal technicality.
    #
    # paperRect (the raw physical sheet) must match exactly; pageRect (the
    # driver's actual printable area) is deliberately *not* forced to match
    # -- see configure_printer_for_sheet_size's docstring for the clipping
    # bug that caused.
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    configure_printer_for_sheet_size(printer, width_pt=792.0, height_pt=612.0)
    assert printer.pageLayout().orientation() == QPageLayout.Orientation.Landscape
    assert printer.paperRect(QPrinter.Unit.Point).width() == pytest.approx(792.0, abs=1.0)
    assert printer.paperRect(QPrinter.Unit.Point).height() == pytest.approx(612.0, abs=1.0)


def test_configure_printer_sets_portrait_orientation_metadata(qtbot):
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    configure_printer_for_sheet_size(printer, width_pt=612.0, height_pt=792.0)
    assert printer.pageLayout().orientation() == QPageLayout.Orientation.Portrait
    assert printer.paperRect(QPrinter.Unit.Point).width() == pytest.approx(612.0, abs=1.0)
    assert printer.paperRect(QPrinter.Unit.Point).height() == pytest.approx(792.0, abs=1.0)


def test_print_document_honors_page_range(qtbot, make_pdf, tmp_path):
    src_path = make_pdf(num_pages=6, page_size=(792, 612))
    document = PdfDocument(src_path)
    printer, out_path = _make_printer(tmp_path)
    printer.setPrintRange(QPrinter.PrintRange.PageRange)
    printer.setFromTo(2, 4)

    print_document(document, printer)

    result = fitz.open(out_path)
    assert result.page_count == 3  # pages 2, 3, 4


def test_print_document_clamps_out_of_range_page_range(qtbot, make_pdf, tmp_path):
    src_path = make_pdf(num_pages=3, page_size=(792, 612))
    document = PdfDocument(src_path)
    printer, out_path = _make_printer(tmp_path)
    printer.setPrintRange(QPrinter.PrintRange.PageRange)
    printer.setFromTo(1, 999)  # beyond the document's actual page count

    print_document(document, printer)

    result = fitz.open(out_path)
    assert result.page_count == 3


def test_fit_centered_no_scaling_needed():
    size = QSizeF(100, 50)
    area = QRectF(10, 10, 100, 50)
    assert _fit_centered(size, area) == area


def test_fit_centered_shrinks_to_fit_and_centers():
    # A page-shaped size that's too big for a smaller-than-nominal printable
    # area (the real-world case: a printer's hardware margin) must shrink to
    # fit inside it, not overflow past its edges.
    size = QSizeF(792, 612)
    area = QRectF(10, 16, 772, 586)  # inset like the real printer probed above
    result = _fit_centered(size, area)
    assert result.x() >= area.x()
    assert result.y() >= area.y()
    assert result.x() + result.width() <= area.x() + area.width() + 1e-6
    assert result.y() + result.height() <= area.y() + area.height() + 1e-6


def test_print_document_does_not_clip_when_printable_area_is_smaller_than_the_sheet(qtbot, make_pdf, tmp_path):
    # Regression test for the real bug: forcing setFullPage(True) made Qt
    # claim the whole nominal sheet was printable, so a real printer's
    # hardware margin silently clipped content near the edges (confirmed
    # against a real laser printer). Simulate a printer with a real margin
    # via setPageMargins (PdfFormat output otherwise has none to test
    # against) and confirm the drawn content's own bounding box -- not just
    # the page's -- lands fully inside the resulting (smaller) printable
    # area with margin to spare, not past its edges.
    #
    # This also guards a second bug found while writing this test: without
    # setFullPage(True), QPainter's own coordinate origin is *already* the
    # printable area's top-left -- using pageRect()'s absolute (offset)
    # coordinates as the drawing rect double-applies that offset, pushing
    # content off the *opposite* edge instead of fixing the clip.
    src_path = make_pdf(num_pages=1, page_size=(792, 612))
    document = PdfDocument(src_path)
    printer, out_path = _make_printer(tmp_path)
    printer.setPageMargins(QMarginsF(20, 20, 20, 20), QPageLayout.Unit.Point)
    printable_before_print = printer.pageRect(QPrinter.Unit.Point)
    assert printable_before_print.width() < 792  # confirms the margin actually took effect

    print_document(document, printer)

    result = fitz.open(out_path)
    page_rect = result[0].rect
    assert page_rect.width == pytest.approx(792.0, abs=1.0)
    assert page_rect.height == pytest.approx(612.0, abs=1.0)

    drawn_bbox = result[0].get_image_info()[0]["bbox"]
    left, top, right, bottom = drawn_bbox
    margin = 20.0
    assert left >= margin - 1.0
    assert top >= margin - 1.0
    assert right <= page_rect.width - margin + 1.0
    assert bottom <= page_rect.height - margin + 1.0


def test_print_document_empty_document_prints_nothing(qtbot, make_pdf, tmp_path):
    src_path = make_pdf(num_pages=1)
    document = PdfDocument(src_path)
    document.delete_page(0)
    assert document.page_count == 0
    printer, out_path = _make_printer(tmp_path)

    print_document(document, printer)  # must not raise

    assert not os.path.exists(out_path) or fitz.open(out_path).page_count == 0
