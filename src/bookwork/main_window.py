"""Main application window: menu, thumbnail sidebar, and page view."""

from __future__ import annotations

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
)

from bookwork.pdf_document import PdfDocument
from bookwork.widgets.page_view import PageView
from bookwork.widgets.thumbnail_list import ThumbnailList


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bookwork")
        self.resize(1000, 800)

        self._document: PdfDocument | None = None
        self._current_page = 0

        self._thumbnail_list = ThumbnailList()
        self._page_view = PageView()

        splitter = QSplitter()
        splitter.addWidget(self._thumbnail_list)
        splitter.addWidget(self._page_view)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self.setStatusBar(QStatusBar())

        self._thumbnail_list.page_selected.connect(self._show_page)

        self._build_menu()
        self._update_actions_enabled()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        open_action = QAction("&Open...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_file_dialog)
        file_menu.addAction(open_action)
        self._open_action = open_action

        view_menu = self.menuBar().addMenu("&View")

        self._prev_action = QAction("Previous Page", self)
        self._prev_action.setShortcut(QKeySequence.StandardKey.MoveToPreviousPage)
        self._prev_action.triggered.connect(self._go_previous)
        view_menu.addAction(self._prev_action)

        self._next_action = QAction("Next Page", self)
        self._next_action.setShortcut(QKeySequence.StandardKey.MoveToNextPage)
        self._next_action.triggered.connect(self._go_next)
        view_menu.addAction(self._next_action)

    def _open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", filter="PDF files (*.pdf)")
        if path:
            self.open_pdf(path)

    def open_pdf(self, path: str) -> None:
        try:
            document = PdfDocument(path)
        except Exception as exc:  # fitz raises plain Exception/RuntimeError on bad files
            QMessageBox.critical(self, "Failed to open PDF", f"Could not open:\n{path}\n\n{exc}")
            return

        if self._document is not None:
            self._document.close()
        self._document = document
        self._current_page = 0

        thumbnails = [document.render_thumbnail(i) for i in range(document.page_count)]
        self._thumbnail_list.set_thumbnails(thumbnails)

        self._show_page(0)
        self.setWindowTitle(f"Bookwork — {document.path.name}")

    def _show_page(self, index: int) -> None:
        if self._document is None:
            return
        index = max(0, min(index, self._document.page_count - 1))
        self._current_page = index
        image = self._document.render_page(index)
        self._page_view.set_image(image)
        self._thumbnail_list.select_page(index)
        self.statusBar().showMessage(f"Page {index + 1} of {self._document.page_count}")
        self._update_actions_enabled()

    def _go_previous(self) -> None:
        self._show_page(self._current_page - 1)

    def _go_next(self) -> None:
        self._show_page(self._current_page + 1)

    def _update_actions_enabled(self) -> None:
        has_doc = self._document is not None
        self._prev_action.setEnabled(has_doc and self._current_page > 0)
        self._next_action.setEnabled(
            has_doc and self._document is not None and self._current_page < self._document.page_count - 1
        )

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._document is not None:
            self._document.close()
        super().closeEvent(event)
