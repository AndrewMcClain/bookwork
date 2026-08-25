"""Main application window: menu, Source/Imposed tabs, and imposition settings."""

from __future__ import annotations

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QWidget,
)

from bookwork.imposition import ImpositionParams, impose
from bookwork.pdf_document import PdfDocument
from bookwork.widgets.imposition_panel import ImpositionPanel
from bookwork.widgets.pdf_viewer_pane import PdfViewerPane


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bookwork")
        self.resize(1100, 800)

        self._source_pane = PdfViewerPane()
        self._imposed_pane = PdfViewerPane()
        self._imposition_panel = ImpositionPanel()
        self._imposition_panel.params_changed.connect(self._regenerate_imposed)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._source_pane, "Source")
        self._tabs.addTab(self._make_imposed_tab(), "Imposed")
        self._tabs.currentChanged.connect(lambda _index: self._update_actions_enabled())
        self.setCentralWidget(self._tabs)

        self.setStatusBar(QStatusBar())

        self._source_pane.page_changed.connect(self._on_page_changed)
        self._imposed_pane.page_changed.connect(self._on_page_changed)

        self._build_menu()
        self._update_actions_enabled()

    def _make_imposed_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._imposition_panel)
        layout.addWidget(self._imposed_pane, stretch=1)
        return tab

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

        self._source_pane.load_document(document)
        self.setWindowTitle(f"Bookwork — {document.path.name}")
        self._regenerate_imposed(self._imposition_panel.current_params())

    def _regenerate_imposed(self, params: ImpositionParams) -> None:
        if self._source_pane.document is None:
            return
        try:
            imposed_doc = impose(self._source_pane.document.fitz_document, params)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid imposition settings", str(exc))
            return
        self._imposed_pane.load_document(
            PdfDocument.from_fitz_document(imposed_doc, "imposed.pdf")
        )
        self._update_actions_enabled()

    def _current_pane(self) -> PdfViewerPane:
        return self._source_pane if self._tabs.currentIndex() == 0 else self._imposed_pane

    def _go_previous(self) -> None:
        self._current_pane().go_previous()

    def _go_next(self) -> None:
        self._current_pane().go_next()

    def _on_page_changed(self, current: int, total: int) -> None:
        # Only reflect the pane the user is actually looking at.
        if self.sender() is self._current_pane():
            self.statusBar().showMessage(f"Page {current + 1} of {total}")
        self._update_actions_enabled()

    def _update_actions_enabled(self) -> None:
        pane = self._current_pane()
        self._prev_action.setEnabled(pane.has_previous())
        self._next_action.setEnabled(pane.has_next())
        if pane.document is not None:
            self.statusBar().showMessage(f"Page {pane.current_page + 1} of {pane.document.page_count}")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._source_pane.clear()
        self._imposed_pane.clear()
        super().closeEvent(event)
