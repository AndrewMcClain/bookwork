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


def _rects(paper_w, paper_h, left, top, right, bottom, dpi=300):
    """Paper and printable rects in device pixels, from margins in points."""
    s = dpi / 72.0
    paper = QRectF(0, 0, paper_w * s, paper_h * s)
    printable = QRectF(
        left * s, top * s, (paper_w - left - right) * s, (paper_h - top - bottom) * s
    )
    return paper, printable


def _sheet(width_pt=792, height_pt=612, dpi=300):
    return QSizeF(width_pt / 72 * dpi, height_pt / 72 * dpi)


def _on_paper(target, printable, dpi=300):
    """Convert a painter-coordinate target back to paper coordinates. The
    painter's origin is the printable area's top-left."""
    s = 72.0 / dpi
    return QRectF(
        target.x() * s + printable.x() * s,
        target.y() * s + printable.y() * s,
        target.width() * s,
        target.height() * s,
    )


def test_sheet_is_centred_on_the_paper_not_the_printable_area(qtbot):
    """The spine runs down the middle of the sheet and the sheet is folded
    along it, so the spine has to land on the paper's own centreline.

    Printers' hardware margins are routinely asymmetric — the laser printer
    this was developed against reports 16pt top and 10pt bottom — and
    centring within the printable area shifts the sheet by half that
    difference, which is an off-centre fold.
    """
    paper, printable = _rects(792, 612, left=30, top=16, right=10, bottom=10)
    target = _print_target_rect(_sheet(), 300, paper, printable, 300)
    drawn = _on_paper(target, printable)

    assert drawn.x() + drawn.width() / 2 == pytest.approx(792 / 2, abs=0.1)
    assert drawn.y() + drawn.height() / 2 == pytest.approx(612 / 2, abs=0.1)


def test_whole_sheet_including_crop_marks_lands_inside_the_printable_area(qtbot):
    """Marks sit at the sheet's outer edge and are what you fold and cut
    along, so losing them defeats their purpose."""
    paper, printable = _rects(792, 612, left=10, top=16, right=10, bottom=10)
    target = _print_target_rect(_sheet(), 300, paper, printable, 300)
    drawn = _on_paper(target, printable)

    assert drawn.x() >= 10 - 0.1
    assert drawn.y() >= 16 - 0.1
    assert drawn.x() + drawn.width() <= 792 - 10 + 0.1
    assert drawn.y() + drawn.height() <= 612 - 10 + 0.1


def test_scale_is_bounded_by_the_larger_margin_on_each_axis(qtbot):
    """Once the sheet is centred on the paper, the tighter side limits it —
    the extra room on the looser side cannot be used without moving off
    centre."""
    paper, printable = _rects(792, 612, left=40, top=0, right=0, bottom=0)
    target = _print_target_rect(_sheet(), 300, paper, printable, 300)
    drawn = _on_paper(target, printable)

    # 40pt on one side means 40pt reserved on both: 792 - 80 usable.
    assert drawn.width() == pytest.approx(792 - 80, abs=0.5)


def test_no_shrink_when_the_printer_has_no_hardware_margin(qtbot):
    """A borderless device, or PDF output, should print at full size."""
    paper, printable = _rects(792, 612, left=0, top=0, right=0, bottom=0)
    target = _print_target_rect(_sheet(), 300, paper, printable, 300)
    drawn = _on_paper(target, printable)

    assert drawn.width() == pytest.approx(792, abs=0.1)
    assert drawn.height() == pytest.approx(612, abs=0.1)


def test_sheet_is_never_enlarged(qtbot):
    paper, printable = _rects(2000, 2000, left=0, top=0, right=0, bottom=0)
    target = _print_target_rect(_sheet(), 300, paper, printable, 300)
    drawn = _on_paper(target, printable)

    assert drawn.width() == pytest.approx(792, abs=0.1)


def test_aspect_ratio_is_preserved(qtbot):
    paper, printable = _rects(792, 612, left=10, top=40, right=10, bottom=5)
    target = _print_target_rect(_sheet(), 300, paper, printable, 300)

    assert target.width() / target.height() == pytest.approx(792 / 612, rel=1e-6)


def test_handles_different_image_and_printer_dpi(qtbot):
    """The page is rasterised at PRINT_DPI; the printer device reports its
    own, often much higher, resolution. Mixing the two pixel spaces was a
    real bug."""
    paper, printable = _rects(792, 612, left=0, top=0, right=0, bottom=0, dpi=1200)
    target = _print_target_rect(_sheet(dpi=300), 300, paper, printable, 1200)

    # Same physical size, expressed in the printer's 1200 DPI pixels.
    assert target.width() == pytest.approx(792 / 72 * 1200, abs=1.0)
    assert target.height() == pytest.approx(612 / 72 * 1200, abs=1.0)


def test_print_document_centres_the_sheet_on_asymmetric_margins(qtbot, make_pdf, tmp_path):
    """End to end: the drawn image must sit centred on the page with equal
    margins, even though the printer's own are lopsided."""
    src_path = make_pdf(num_pages=1, page_size=(792, 612))
    document = PdfDocument(src_path)
    printer, out_path = _make_printer(tmp_path)
    printer.setPageMargins(QMarginsF(30, 16, 10, 10), QPageLayout.Unit.Point)

    print_document(document, printer)

    page = fitz.open(out_path)[0]
    left, top, right, bottom = page.get_image_info()[0]["bbox"]
    assert left == pytest.approx(page.rect.width - right, abs=1.0), "not centred horizontally"
    assert top == pytest.approx(page.rect.height - bottom, abs=1.0), "not centred vertically"


def test_print_document_keeps_the_whole_sheet_printable(qtbot, make_pdf, tmp_path):
    src_path = make_pdf(num_pages=1, page_size=(792, 612))
    document = PdfDocument(src_path)
    printer, out_path = _make_printer(tmp_path)
    printer.setPageMargins(QMarginsF(30, 16, 10, 10), QPageLayout.Unit.Point)

    print_document(document, printer)

    page = fitz.open(out_path)[0]
    left, top, right, bottom = page.get_image_info()[0]["bbox"]
    # Nothing may fall inside any hardware margin, so the tightest bound on
    # each axis applies to both sides.
    assert left >= 30 - 1.0 and right <= page.rect.width - 30 + 1.0
    assert top >= 16 - 1.0 and bottom <= page.rect.height - 16 + 1.0


def test_print_document_empty_document_prints_nothing(qtbot, make_pdf, tmp_path):
    src_path = make_pdf(num_pages=1)
    document = PdfDocument(src_path)
    document.delete_page(0)
    assert document.page_count == 0
    printer, out_path = _make_printer(tmp_path)

    print_document(document, printer)  # must not raise

    assert not os.path.exists(out_path) or fitz.open(out_path).page_count == 0
