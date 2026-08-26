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
from PySide6.QtPrintSupport import QPrinter

from bookwork.pdf_document import PdfDocument
from bookwork.printing import configure_printer_for_sheet_size, print_document


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


def test_print_document_empty_document_prints_nothing(qtbot, make_pdf, tmp_path):
    src_path = make_pdf(num_pages=1)
    document = PdfDocument(src_path)
    document.delete_page(0)
    assert document.page_count == 0
    printer, out_path = _make_printer(tmp_path)

    print_document(document, printer)  # must not raise

    assert not os.path.exists(out_path) or fitz.open(out_path).page_count == 0
