"""Widget that displays a single rendered PDF page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QScrollArea


class PageView(QScrollArea):
    """Scrollable area showing one page image at a time.

    Kept deliberately dumb: it just displays whatever `QImage` it's given.
    The main window is responsible for asking the `PdfDocument` to render
    the current page and pushing the result in via `set_image`.
    """

    def __init__(self) -> None:
        super().__init__()
        self._label = QLabel("No document loaded")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidget(self._label)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_image(self, image: QImage) -> None:
        self._label.setPixmap(QPixmap.fromImage(image))
        self._label.adjustSize()

    def clear(self) -> None:
        self._label.setPixmap(QPixmap())
        self._label.setText("No document loaded")
