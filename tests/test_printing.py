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
from bookwork.printing import _print_target_rect, configure_printer_for_sheet_size, print_document


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


def test_print_target_rect_no_shrink_when_printable_area_covers_content(qtbot):
    # Printable area smaller than the full sheet, but still bigger than the
    # margin-inset content region (18pt margin > 10pt simulated hardware
    # margin) -> draw at full native size, no shrink. The sheet's own outer
    # edge (2pt beyond the printable area on each side) would get clipped
    # by a real device, but that's only where crop marks live, not content.
    sheet_px = QSizeF(792 / 72 * 300, 612 / 72 * 300)  # 792x612pt at 300 DPI
    printable_area_px = QRectF(10, 10, (792 - 20) / 72 * 300, (612 - 20) / 72 * 300)  # 10pt margin
    target = _print_target_rect(sheet_px, 300, 18.0, printable_area_px, 300)
    assert target.width() == pytest.approx(sheet_px.width(), abs=1.0)
    assert target.height() == pytest.approx(sheet_px.height(), abs=1.0)


def test_print_target_rect_shrinks_only_enough_to_protect_content(qtbot):
    # Printable area smaller than even the margin-inset content region (40pt
    # simulated hardware margin > 18pt content margin) -> must shrink, but
    # only as much as needed to keep the *content* (not the full sheet)
    # inside the printable area.
    sheet_px = QSizeF(792 / 72 * 300, 612 / 72 * 300)
    printable_area_px = QRectF(40, 40, (792 - 80) / 72 * 300, (612 - 80) / 72 * 300)
    target = _print_target_rect(sheet_px, 300, 18.0, printable_area_px, 300)

    assert target.width() < sheet_px.width()  # did shrink

    # The content region (margin_pt inset from target's own edges, scaled
    # along with everything else) must land fully inside printable_area_px.
    scale = target.width() / sheet_px.width()
    margin_px = 18.0 / 72 * 300 * scale
    content_left = target.x() + margin_px
    content_right = target.x() + target.width() - margin_px
    assert content_left >= printable_area_px.x() - 1.0
    assert content_right <= printable_area_px.x() + printable_area_px.width() + 1.0


def test_print_target_rect_zero_margin_always_shrinks_to_fit(qtbot):
    # margin_pt=0 (the default) means there's no known content-safe region,
    # so it falls back to protecting the whole sheet -- the old behavior.
    sheet_px = QSizeF(792 / 72 * 300, 612 / 72 * 300)
    printable_area_px = QRectF(10, 10, (792 - 20) / 72 * 300, (612 - 20) / 72 * 300)
    target = _print_target_rect(sheet_px, 300, 0.0, printable_area_px, 300)
    assert target.width() < sheet_px.width()


def test_print_target_rect_never_upscales(qtbot):
    sheet_px = QSizeF(100, 100)
    printable_area_px = QRectF(0, 0, 500, 500)  # much bigger than the sheet
    target = _print_target_rect(sheet_px, 300, 0.0, printable_area_px, 300)
    assert target.width() == pytest.approx(100.0, abs=1e-6)
    assert target.height() == pytest.approx(100.0, abs=1e-6)


def test_print_target_rect_handles_different_image_and_printer_dpi(qtbot):
    # The image is rendered at 300 DPI; the printer device may report a
    # completely different resolution (e.g. a real printer's 1200 DPI) --
    # mixing the two pixel spaces without converting was an earlier bug.
    sheet_px_at_300dpi = QSizeF(792 / 72 * 300, 612 / 72 * 300)
    printable_area_px_at_1200dpi = QRectF(0, 0, 792 / 72 * 1200, 612 / 72 * 1200)
    target = _print_target_rect(sheet_px_at_300dpi, 300, 0.0, printable_area_px_at_1200dpi, 1200)
    # Same physical size (792x612pt), expressed in the printer's own 1200
    # DPI pixel space -- not the image's 300 DPI one.
    assert target.width() == pytest.approx(792 / 72 * 1200, abs=1.0)
    assert target.height() == pytest.approx(612 / 72 * 1200, abs=1.0)


def test_print_document_protects_content_but_lets_marks_clip_on_real_hardware_margin(
    qtbot, make_pdf, tmp_path
):
    # End-to-end regression test for the real bug report: with a content
    # margin (18pt) bigger than the printer's simulated hardware margin
    # (10pt) -- the realistic case bookwork's own default margin covers --
    # the page draws at full native size, completely unscaled/unshifted, so
    # no "unintended margin" is introduced. (Simulate the hardware margin
    # via setPageMargins; PdfFormat output otherwise has none to test
    # against.)
    src_path = make_pdf(num_pages=1, page_size=(792, 612))
    document = PdfDocument(src_path)
    printer, out_path = _make_printer(tmp_path)
    printer.setPageMargins(QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Point)

    print_document(document, printer, margin_pt=18.0)

    out = fitz.open(out_path)
    bbox = out[0].get_image_info()[0]["bbox"]
    assert bbox == pytest.approx((0.0, 0.0, 792.0, 612.0), abs=1.0)


def test_print_document_shrinks_to_protect_content_when_hardware_margin_exceeds_it(
    qtbot, make_pdf, tmp_path
):
    # Now the simulated hardware margin (40pt) exceeds our content margin
    # (18pt): content must still not be clipped, so this time it does shrink.
    src_path = make_pdf(num_pages=1, page_size=(792, 612))
    document = PdfDocument(src_path)
    printer, out_path = _make_printer(tmp_path)
    printer.setPageMargins(QMarginsF(40, 40, 40, 40), QPageLayout.Unit.Point)

    print_document(document, printer, margin_pt=18.0)

    out = fitz.open(out_path)
    bbox = out[0].get_image_info()[0]["bbox"]
    left, top, right, bottom = bbox
    assert right - left < 792.0  # did shrink, unlike the case above
    content_margin = 18.0 * (right - left) / 792.0  # scaled along with the sheet
    assert left + content_margin >= 40.0 - 1.0
    assert top + content_margin >= 40.0 - 1.0
    assert right - content_margin <= 792.0 - 40.0 + 1.0
    assert bottom - content_margin <= 612.0 - 40.0 + 1.0


def test_print_document_empty_document_prints_nothing(qtbot, make_pdf, tmp_path):
    src_path = make_pdf(num_pages=1)
    document = PdfDocument(src_path)
    document.delete_page(0)
    assert document.page_count == 0
    printer, out_path = _make_printer(tmp_path)

    print_document(document, printer)  # must not raise

    assert not os.path.exists(out_path) or fitz.open(out_path).page_count == 0
