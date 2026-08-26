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

"""Thin wrapper around a PyMuPDF (fitz) document.

Keeps all direct `fitz` usage in one place so the rest of the app deals in
plain Python types (page counts, `QImage`s) rather than `fitz` objects
directly. `imposition.py` is the one other module that touches `fitz`, since
it composes pages rather than merely displaying them.
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
        self._adopt(fitz.open(Path(path)), Path(path))

    @classmethod
    def from_fitz_document(cls, doc: fitz.Document, display_name: str) -> "PdfDocument":
        """Wrap an already-open, in-memory `fitz.Document` (e.g. imposition
        output) that has no path of its own on disk."""
        instance = cls.__new__(cls)
        instance._adopt(doc, Path(display_name))
        return instance

    def _adopt(self, doc: fitz.Document, path: Path) -> None:
        """The single place instance state is established.

        `from_fitz_document` has to bypass `__init__` (it already holds an
        open document, and `__init__`'s job is to open one from a path), so
        both constructors funnel through here instead of each setting the
        fields up themselves — otherwise a field added to one is silently
        missing on documents built by the other, which is every Imposed and
        Bound Preview document, surfacing only as an AttributeError from
        whatever code later touches it.
        """
        self.path = path
        self._doc = doc
        self._undo_stack: list[bytes] = []
        self._redo_stack: list[bytes] = []

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    @property
    def fitz_document(self) -> fitz.Document:
        """The underlying `fitz.Document`, for code (like `imposition.impose`)
        that needs to operate on it directly rather than through this wrapper."""
        return self._doc

    def page_size(self, index: int) -> tuple[float, float]:
        """Page `index`'s `(width, height)` in PDF points.

        Lets callers reason about page geometry without rendering — the
        bound preview mixes full spreads with half-width lone covers, and
        the turn view needs to tell them apart to know which side of the
        spine a page sits on.
        """
        rect = self._doc[index].rect
        return rect.width, rect.height

    def render_page(self, index: int, dpi: int = DEFAULT_RENDER_DPI) -> QImage:
        """Render page `index` (0-based) to a `QImage` at the given DPI."""
        page = self._doc[index]
        zoom = dpi / 72  # PDF units are 1/72 inch; fitz's default is 72 DPI.
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return _qimage_from_pixmap(pixmap)

    def render_thumbnail(self, index: int, dpi: int = THUMBNAIL_DPI) -> QImage:
        """Render a small preview of page `index`, for a thumbnail strip."""
        return self.render_page(index, dpi=dpi)

    # --- Editing (insert/delete pages) and undo/redo ---
    #
    # Edits happen in memory only (the file on disk is never touched here —
    # see docs/design.md). Undo/redo works by snapshotting the whole document
    # as bytes before each edit rather than trying to record/invert
    # individual page operations: simpler and safer to get right, at the
    # cost of an extra full-document copy per edit, which is fine at the
    # document sizes this tool targets.

    def insert_blank_page(self, index: int) -> None:
        """Insert a blank page so it becomes page `index` (0-based) —
        anything currently at `index` and after shifts later. The new
        page's size matches the page it's being inserted next to, so it
        doesn't look mismatched among otherwise-uniform pages."""
        self._push_undo()
        width, height = self._size_for_new_page_at(index)
        self._doc.insert_page(index, width=width, height=height)

    def delete_page(self, index: int) -> None:
        """Delete page `index` (0-based) — blank or real content."""
        self._push_undo()
        self._doc.delete_page(index)

    def _size_for_new_page_at(self, index: int) -> tuple[float, float]:
        if self.page_count == 0:
            return 612.0, 792.0  # US Letter, portrait
        reference_index = max(0, min(index, self.page_count - 1))
        rect = self._doc[reference_index].rect
        return rect.width, rect.height

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(self._doc.tobytes())
        self._load_from_bytes(self._undo_stack.pop())

    def redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(self._doc.tobytes())
        self._load_from_bytes(self._redo_stack.pop())

    def _push_undo(self) -> None:
        self._undo_stack.append(self._doc.tobytes())
        self._redo_stack.clear()

    def _load_from_bytes(self, data: bytes) -> None:
        self._doc.close()
        self._doc = fitz.open(stream=data, filetype="pdf")

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
