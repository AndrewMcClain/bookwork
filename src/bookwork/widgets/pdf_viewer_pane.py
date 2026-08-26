"""A thumbnail sidebar + single-page view, bundled together.

Used twice in the main window (once for the source PDF, once for the imposed
output) so page navigation logic lives in one place instead of being
duplicated per tab.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from bookwork.pdf_document import PdfDocument
from bookwork.widgets.page_turn_view import PageTurnView
from bookwork.widgets.page_view import PageView
from bookwork.widgets.thumbnail_list import ThumbnailList


class PdfViewerPane(QWidget):
    """Emits `page_changed(current_index, page_count)` on every navigation,
    including the initial page shown after `load_document`."""

    page_changed = Signal(int, int)

    def __init__(self, *, animate_page_turns: bool = False) -> None:
        """`animate_page_turns` swaps the flat page display for one that
        animates a leaf turning between adjacent views — meaningful only for
        the Bound Preview tab, which shows a book. The Source and Imposed
        tabs show flat sheets, where a turn animation would imply a physical
        structure that isn't there."""
        super().__init__()
        self.document: PdfDocument | None = None
        self.current_page = 0

        self.thumbnail_list = ThumbnailList()
        self.page_view = PageTurnView() if animate_page_turns else PageView()

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

        self._rebuild_thumbnails()
        self.show_page(0)  # a fresh document has nothing to turn from

    def refresh(self) -> None:
        """Re-render thumbnails and the current page from `self.document`,
        which was just mutated in place (insert/delete/undo/redo) rather
        than replaced. Unlike `load_document`, this doesn't touch the
        document's own undo/redo state or close/replace it."""
        if self.document is None:
            return
        self._rebuild_thumbnails()
        self.show_page(self.current_page)

    def _rebuild_thumbnails(self) -> None:
        """Re-render the whole thumbnail strip from `self.document`. Shared
        by `load_document` and `refresh` so both always render thumbnails
        the same way — a change made to only one of them would leave pages
        looking different after an edit than they did on open."""
        if self.document is None:
            return
        self.thumbnail_list.set_thumbnails(
            [self.document.render_thumbnail(i) for i in range(self.document.page_count)]
        )

    def show_page(self, index: int) -> None:
        if self.document is None:
            return
        if self.document.page_count == 0:
            self.current_page = 0
            self.page_view.clear()
            self.page_changed.emit(0, 0)
            return
        index = max(0, min(index, self.document.page_count - 1))
        previous_index = self.current_page
        self.current_page = index
        self.page_view.display(self.document, index, previous_index)
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
