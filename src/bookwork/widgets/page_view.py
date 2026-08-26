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

    def display(self, document, index: int, previous_index: int | None = None) -> None:
        """Show page `index` of `document`.

        The seam `PdfViewerPane` drives every page view through. This one
        ignores `previous_index` — it has no transition to run — but
        `PageTurnView` uses it to decide whether the move is a page turn.
        """
        self.set_image(document.render_page(index))

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
