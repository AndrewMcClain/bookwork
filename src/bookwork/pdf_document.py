"""Thin wrapper around a PyMuPDF (fitz) document.

Keeps all direct `fitz` usage in one place so the rest of the app deals in
plain Python types (page counts, `QImage`s) rather than `fitz` objects
directly. This is the seam we'll extend in later milestones (imposition,
insert/delete page) without touching the viewer widgets.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
from PySide6.QtGui import QImage

#: Default resolution used when rendering a full page for on-screen display.
DEFAULT_RENDER_DPI = 150

#: Resolution used for the (smaller, faster) thumbnail sidebar renders.
THUMBNAIL_DPI = 40


class PdfDocument:
    """A loaded PDF, opened from a file path.

    Wraps a `fitz.Document` and exposes rendering as `QImage`, so PySide6
    widgets never need to import `fitz` themselves.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._doc = fitz.open(self.path)

    @classmethod
    def from_fitz_document(cls, doc: fitz.Document, display_name: str) -> "PdfDocument":
        """Wrap an already-open, in-memory `fitz.Document` (e.g. imposition
        output) that has no path of its own on disk."""
        instance = cls.__new__(cls)
        instance.path = Path(display_name)
        instance._doc = doc
        return instance

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    @property
    def fitz_document(self) -> fitz.Document:
        """The underlying `fitz.Document`, for code (like `imposition.impose`)
        that needs to operate on it directly rather than through this wrapper."""
        return self._doc

    def render_page(self, index: int, dpi: int = DEFAULT_RENDER_DPI) -> QImage:
        """Render page `index` (0-based) to a `QImage` at the given DPI."""
        page = self._doc[index]
        zoom = dpi / 72  # PDF units are 1/72 inch; fitz's default is 72 DPI.
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return _qimage_from_pixmap(pixmap)

    def render_thumbnail(self, index: int, dpi: int = THUMBNAIL_DPI) -> QImage:
        """Render a small preview of page `index`, for a thumbnail strip."""
        return self.render_page(index, dpi=dpi)

    def close(self) -> None:
        self._doc.close()

    def __enter__(self) -> "PdfDocument":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _qimage_from_pixmap(pixmap: fitz.Pixmap) -> QImage:
    """Convert a `fitz.Pixmap` to a `QImage`, copying the pixel data.

    The copy matters: `pixmap.samples` is a buffer owned by the `fitz.Pixmap`,
    which can be garbage-collected (and its memory freed/reused) once this
    function returns, so the `QImage` must not alias it.
    """
    fmt = QImage.Format.Format_RGB888 if pixmap.n == 3 else QImage.Format.Format_RGBA8888
    image = QImage(
        pixmap.samples,
        pixmap.width,
        pixmap.height,
        pixmap.stride,
        fmt,
    )
    return image.copy()
