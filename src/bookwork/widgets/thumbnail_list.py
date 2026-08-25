"""Sidebar list of page thumbnails, for jumping to a page.

v0 scope: display thumbnails and emit which page was clicked. Later
milestones (page insert/delete, v2) will add a context menu here rather
than replacing this widget.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem

_THUMB_ICON_SIZE = QSize(96, 128)


class ThumbnailList(QListWidget):
    """Emits `page_selected(index)` (0-based) when the user picks a page."""

    page_selected = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setIconSize(_THUMB_ICON_SIZE)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.TopToBottom)
        self.setWrapping(False)
        self.setMovement(QListWidget.Movement.Static)
        self.setFixedWidth(_THUMB_ICON_SIZE.width() + 40)
        self.currentRowChanged.connect(self._on_row_changed)

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
