"""Main application window: menu, Source/Imposed/Bound Preview tabs, and
imposition settings.
"""

from __future__ import annotations

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QWidget,
)

from bookwork.imposition import ImpositionParams, build_bound_preview, compute_stats, impose
from bookwork.pdf_document import PdfDocument
from bookwork.printing import DEFAULT_DUPLEX_MODE, configure_printer_for_sheet_size, print_document
from bookwork.widgets.imposition_panel import ImpositionPanel
from bookwork.widgets.pdf_viewer_pane import PdfViewerPane


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bookwork")
        self.resize(1100, 800)

        self._source_pane = PdfViewerPane()
        self._imposed_pane = PdfViewerPane()
        self._bound_preview_pane = PdfViewerPane()
        self._imposition_panel = ImpositionPanel()
        self._imposition_panel.params_changed.connect(self._regenerate_imposed)
        # The params that actually produced the current Imposed document —
        # used at print time for sheet size, independent of whatever the
        # panel's fields currently show (which might have unapplied edits).
        self._current_imposition_params: ImpositionParams | None = None

        self._panes = [self._source_pane, self._imposed_pane, self._bound_preview_pane]

        self._tabs = QTabWidget()
        self._tabs.addTab(self._source_pane, "Source")
        self._tabs.addTab(self._make_imposed_tab(), "Imposed")
        self._tabs.addTab(self._bound_preview_pane, "Bound Preview")
        self._tabs.currentChanged.connect(lambda _index: self._update_actions_enabled())
        self.setCentralWidget(self._tabs)

        self.setStatusBar(QStatusBar())

        for pane in self._panes:
            pane.page_changed.connect(self._on_page_changed)

        # Only the Source tab's pages can be edited — Imposed/Bound Preview
        # are always regenerated output.
        self._source_pane.thumbnail_list.set_editable(True)
        self._source_pane.thumbnail_list.insert_before_requested.connect(
            lambda index: self._insert_blank_page(index)
        )
        self._source_pane.thumbnail_list.insert_after_requested.connect(
            lambda index: self._insert_blank_page(index + 1)
        )
        self._source_pane.thumbnail_list.delete_requested.connect(self._delete_page)

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

        self._print_action = QAction("&Print Imposed...", self)
        self._print_action.setShortcut(QKeySequence.StandardKey.Print)
        self._print_action.triggered.connect(self._print_imposed)
        file_menu.addAction(self._print_action)

        edit_menu = self.menuBar().addMenu("&Edit")

        self._undo_action = QAction("&Undo", self)
        self._undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self._undo_action.triggered.connect(self._undo)
        edit_menu.addAction(self._undo_action)

        self._redo_action = QAction("&Redo", self)
        self._redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self._redo_action.triggered.connect(self._redo)
        edit_menu.addAction(self._redo_action)

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
        source_doc = self._source_pane.document.fitz_document
        try:
            imposed_doc = impose(source_doc, params)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid imposition settings", str(exc))
            return

        self._imposed_pane.load_document(PdfDocument.from_fitz_document(imposed_doc, "imposed.pdf"))

        bound_doc = build_bound_preview(imposed_doc, source_doc.page_count, params)
        self._bound_preview_pane.load_document(
            PdfDocument.from_fitz_document(bound_doc, "bound-preview.pdf")
        )

        self._imposition_panel.set_stats(compute_stats(source_doc.page_count, params))
        self._current_imposition_params = params
        self._update_actions_enabled()

    def _print_imposed(self) -> None:
        document = self._imposed_pane.document
        if document is None or document.page_count == 0:
            QMessageBox.information(self, "Nothing to print", "Open a PDF and impose it first.")
            return
        params = self._current_imposition_params or self._imposition_panel.current_params()

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        configure_printer_for_sheet_size(printer, params.sheet_width_pt, params.sheet_height_pt)
        printer.setDuplex(DEFAULT_DUPLEX_MODE)
        printer.setFromTo(1, document.page_count)
        if self._source_pane.document is not None:
            printer.setDocName(self._source_pane.document.path.stem)

        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle("Print Imposed Pages")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            print_document(document, printer)
        except RuntimeError as exc:
            QMessageBox.critical(self, "Print failed", str(exc))

    def _insert_blank_page(self, index: int) -> None:
        document = self._source_pane.document
        if document is None:
            return
        document.insert_blank_page(index)
        self._source_pane.refresh()
        self._source_pane.show_page(index)
        self._regenerate_imposed(self._imposition_panel.current_params())

    def _delete_page(self, index: int) -> None:
        document = self._source_pane.document
        if document is None:
            return
        if document.page_count <= 1:
            QMessageBox.warning(self, "Cannot delete page", "A document must have at least one page.")
            return
        document.delete_page(index)
        self._source_pane.refresh()
        self._regenerate_imposed(self._imposition_panel.current_params())

    def _undo(self) -> None:
        document = self._source_pane.document
        if document is None or not document.can_undo():
            return
        document.undo()
        self._source_pane.refresh()
        self._regenerate_imposed(self._imposition_panel.current_params())

    def _redo(self) -> None:
        document = self._source_pane.document
        if document is None or not document.can_redo():
            return
        document.redo()
        self._source_pane.refresh()
        self._regenerate_imposed(self._imposition_panel.current_params())

    def _current_pane(self) -> PdfViewerPane:
        return self._panes[self._tabs.currentIndex()]

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

        source_document = self._source_pane.document
        self._undo_action.setEnabled(source_document is not None and source_document.can_undo())
        self._redo_action.setEnabled(source_document is not None and source_document.can_redo())

        imposed_document = self._imposed_pane.document
        self._print_action.setEnabled(imposed_document is not None and imposed_document.page_count > 0)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        for pane in self._panes:
            pane.clear()
        super().closeEvent(event)
