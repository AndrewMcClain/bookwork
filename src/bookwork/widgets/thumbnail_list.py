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

"""Sidebar list of page thumbnails, for jumping to a page.

Reused for all three viewer tabs (Source, Imposed, Bound Preview), but only
the Source tab's list is editable (see `set_editable`) — the other two are
regenerated output, not something a user inserts/deletes pages in directly.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMenu

_THUMB_ICON_SIZE = QSize(96, 128)


class ThumbnailList(QListWidget):
    """Emits `page_selected(index)` (0-based) when the user picks a page.

    When editable (see `set_editable`), also emits `insert_before_requested`,
    `insert_after_requested`, and `delete_requested` (all `int`, 0-based)
    from a right-click context menu on a thumbnail.
    """

    page_selected = Signal(int)
    insert_before_requested = Signal(int)
    insert_after_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setIconSize(_THUMB_ICON_SIZE)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.TopToBottom)
        self.setWrapping(False)
        self.setMovement(QListWidget.Movement.Static)
        self.setFixedWidth(_THUMB_ICON_SIZE.width() + 40)
        self.currentRowChanged.connect(self._on_row_changed)
        self._editable = False
        self._context_menu_connected = False

    def set_editable(self, editable: bool) -> None:
        self._editable = editable
        self.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu if editable else Qt.ContextMenuPolicy.DefaultContextMenu
        )
        if editable and not self._context_menu_connected:
            self.customContextMenuRequested.connect(self._show_context_menu)
            self._context_menu_connected = True
        elif not editable and self._context_menu_connected:
            self.customContextMenuRequested.disconnect(self._show_context_menu)
            self._context_menu_connected = False

    def set_thumbnails(self, images: list[QImage]) -> None:
        self.clear()
        for i, image in enumerate(images):
            item = QListWidgetItem(QIcon(QPixmap.fromImage(image)), str(i + 1))
            self.addItem(item)

    def select_page(self, index: int) -> None:
        self.blockSignals(True)
        self.setCurrentRow(index)
        self.blockSignals(False)

    def _on_row_changed(self, row: int) -> None:
        if row >= 0:
            self.page_selected.emit(row)

    def _show_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        index = self.row(item)

        menu = QMenu(self)
        insert_before_action = menu.addAction("Insert Blank Page Before")
        insert_after_action = menu.addAction("Insert Blank Page After")
        menu.addSeparator()
        delete_action = menu.addAction("Delete Page")

        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is insert_before_action:
            self.insert_before_requested.emit(index)
        elif chosen is insert_after_action:
            self.insert_after_requested.emit(index)
        elif chosen is delete_action:
            self.delete_requested.emit(index)
