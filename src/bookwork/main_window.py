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

"""Main application window: menu, Source/Imposed/Bound Preview tabs, and
imposition settings.
"""

from __future__ import annotations

from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence
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
        self.setAcceptDrops(True)

        self._source_pane = PdfViewerPane()
        self._imposed_pane = PdfViewerPane()
        self._bound_preview_pane = PdfViewerPane(animate_page_turns=True)
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

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept drags that carry at least one local `.pdf` file.

        The extension check happens here so the cursor already shows the drop
        is refused before the mouse is released, instead of accepting the drop
        and then showing an error dialog.
        """
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf") for url in urls):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """Open the first local `.pdf` from the drop; ignore everything else."""
        urls = event.mimeData().urls()
        for url in urls:
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf"):
                self.open_pdf(url.toLocalFile())
                event.acceptProposedAction()
                return
        event.ignore()

    def open_pdf(self, path: str) -> None:
        try:
            document = PdfDocument(path)
        except Exception as exc:  # noqa: BLE001 -- any bad file must surface as a dialog, not a crash
            QMessageBox.critical(self, "Failed to open PDF", f"Could not open:\n{path}\n\n{exc}")
            return

        self._source_pane.load_document(document)
        self.setWindowTitle(f"Bookwork — {document.path.name}")
        self._reimpose_from_panel()

    def _reimpose_from_panel(self) -> None:
        """Re-impose using whatever the settings panel's fields currently
        hold, surfacing an invalid combination as a warning.

        Every caller goes through here rather than passing
        `current_params()` straight to `_regenerate_imposed`, because that
        call raises `ValueError` on a combination the widgets still accept
        (the signature-size spinbox happily holds 6, which isn't a multiple
        of 4). Unguarded, that exception escapes a Qt slot *after* the
        source document has already been edited — Qt swallows it to stderr,
        so the Imposed and Bound Preview tabs are left showing a stale
        layout for the pre-edit document with nothing shown to the user.
        """
        try:
            params = self._imposition_panel.current_params()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid imposition settings", str(exc))
            return
        self._regenerate_imposed(params)

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

        # Before loading, so the first paint is already the right way round.
        self._bound_preview_pane.set_reading_direction(params.right_to_left)
        bound_doc = build_bound_preview(imposed_doc, source_doc.page_count, params)
        self._bound_preview_pane.load_document(PdfDocument.from_fitz_document(bound_doc, "bound-preview.pdf"))

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
        self._reimpose_from_panel()

    def _delete_page(self, index: int) -> None:
        document = self._source_pane.document
        if document is None:
            return
        if document.page_count <= 1:
            QMessageBox.warning(self, "Cannot delete page", "A document must have at least one page.")
            return
        document.delete_page(index)
        self._source_pane.refresh()
        self._reimpose_from_panel()

    def _undo(self) -> None:
        document = self._source_pane.document
        if document is None or not document.can_undo():
            return
        document.undo()
        self._source_pane.refresh()
        self._reimpose_from_panel()

    def _redo(self) -> None:
        document = self._source_pane.document
        if document is None or not document.can_redo():
            return
        document.redo()
        self._source_pane.refresh()
        self._reimpose_from_panel()

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
