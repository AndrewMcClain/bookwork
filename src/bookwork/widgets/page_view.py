"""Widget that displays a single rendered PDF page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap, QResizeEvent
from PySide6.QtWidgets import QLabel, QScrollArea


class PageView(QScrollArea):
    """Scrollable area showing one page image at a time, scaled to fit.

    Kept deliberately dumb about page content: it just displays whatever
    `QImage` it's given, scaled to fit the viewport while preserving aspect
    ratio. This matters for imposed/landscape sheets, which are wider than a
    typical window — without fit-to-view, the second (right) page of a 2-up
    sheet would be scrolled off-screen and easy to miss.
    """

    def __init__(self) -> None:
        super().__init__()
        self._original_image: QImage | None = None

        self._label = QLabel("No document loaded")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidget(self._label)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_image(self, image: QImage) -> None:
        self._original_image = image
        self._update_displayed_pixmap()

    def clear(self) -> None:
        self._original_image = None
        self._label.setPixmap(QPixmap())
        self._label.setText("No document loaded")

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._update_displayed_pixmap()

    def _update_displayed_pixmap(self) -> None:
        if self._original_image is None:
            return
        pixmap = QPixmap.fromImage(self._original_image)
        target_size = self.viewport().size()
        if target_size.width() > 0 and target_size.height() > 0:
            pixmap = pixmap.scaled(
                target_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._label.setPixmap(pixmap)
