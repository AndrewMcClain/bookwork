"""A thumbnail sidebar + single-page view, bundled together.

Used twice in the main window (once for the source PDF, once for the imposed
output) so page navigation logic lives in one place instead of being
duplicated per tab.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from bookwork.pdf_document import PdfDocument
from bookwork.widgets.page_view import PageView
from bookwork.widgets.thumbnail_list import ThumbnailList


class PdfViewerPane(QWidget):
    """Emits `page_changed(current_index, page_count)` on every navigation,
    including the initial page shown after `load_document`."""

    page_changed = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.document: PdfDocument | None = None
        self.current_page = 0

        self.thumbnail_list = ThumbnailList()
        self.page_view = PageView()

        splitter = QSplitter()
        splitter.addWidget(self.thumbnail_list)
        splitter.addWidget(self.page_view)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self.thumbnail_list.page_selected.connect(self.show_page)

    def load_document(self, document: PdfDocument) -> None:
        if self.document is not None:
            self.document.close()
        self.document = document
        self.current_page = 0

        thumbnails = [document.render_thumbnail(i) for i in range(document.page_count)]
        self.thumbnail_list.set_thumbnails(thumbnails)
        self.show_page(0)

    def show_page(self, index: int) -> None:
        if self.document is None:
            return
        index = max(0, min(index, self.document.page_count - 1))
        self.current_page = index
        self.page_view.set_image(self.document.render_page(index))
        self.thumbnail_list.select_page(index)
        self.page_changed.emit(self.current_page, self.document.page_count)

    def go_previous(self) -> None:
        self.show_page(self.current_page - 1)

    def go_next(self) -> None:
        self.show_page(self.current_page + 1)

    def has_previous(self) -> bool:
        return self.document is not None and self.current_page > 0

    def has_next(self) -> bool:
        return self.document is not None and self.current_page < self.document.page_count - 1

    def clear(self) -> None:
        if self.document is not None:
            self.document.close()
            self.document = None
        self.thumbnail_list.clear()
        self.page_view.clear()
