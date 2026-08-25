"""Shared test fixtures.

Tests avoid depending on any real-world PDF asset: `make_pdf` builds a
minimal in-memory-generated PDF on disk with `fitz` itself, with a page
count and page size we control.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
import pytest


@pytest.fixture
def make_pdf(tmp_path: Path):
    def _make(num_pages: int = 3, page_size: tuple[float, float] = (612, 792)) -> Path:
        doc = fitz.open()
        for i in range(num_pages):
            page = doc.new_page(width=page_size[0], height=page_size[1])
            page.insert_text((72, 72), f"Page {i + 1}")
        out_path = tmp_path / "test.pdf"
        doc.save(out_path)
        doc.close()
        return out_path

    return _make
