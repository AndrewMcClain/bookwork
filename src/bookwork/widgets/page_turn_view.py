"""Bound-preview page display that animates a physical page turn.

Stands in for `PageView` on the Bound Preview tab only (see
`PdfViewerPane`'s `animate_page_turns`). The other tabs show sheets, not a
bound book, so a turn animation would be actively misleading there.

The unit of navigation is unchanged: one page of the bound-preview document
= one thing the reader looks at, which is a two-page spread except at the
covers. What this adds is the leaf *between* two of those views. A physical
leaf has a page on each side, so turning from view N to view N+1 rotates a
single sheet whose front is the right-hand page of N and whose back is the
left-hand page of N+1 — that pairing is the whole point, since it's what a
reader actually experiences and what makes an off-by-one obvious.

Deliberately no OpenGL or QML: `QTransform.quadToQuad` gives a real
projective transform, so mapping the page rectangle onto a narrowing
trapezoid is enough for a convincing turn through plain `QPainter`, at a
measured ~6.5ms/frame on the software rasteriser.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPixmap, QPolygonF, QTransform
from PySide6.QtWidgets import QWidget

from bookwork.pdf_document import PdfDocument

#: Resolution the bound-preview views are rasterised at for display. Fixed
#: rather than derived from the widget size so resizing doesn't re-render:
#: pages are scaled down by the painter instead. A spread at this DPI is
#: roughly 4.5MB, and only a few are held at once (see `_prune_cache`).
PAGE_TURN_RENDER_DPI = 110

#: How long one page turn takes. Long enough to read as a physical motion,
#: short enough not to be in the way when paging through quickly.
TURN_DURATION_MS = 420

#: How far the leaf's outer edge is drawn inward, vertically, at the midpoint
#: of the turn — the foreshortening that reads as perspective. A fraction of
#: page height, so it holds up at any window size.
LEAF_LIFT_FRACTION = 0.045

#: Below this projected width the leaf is edge-on: `quadToQuad` has no
#: solution for a degenerate (zero-width) quad and returns None, and there
#: would be nothing meaningful to draw anyway.
_MIN_LEAF_WIDTH_PX = 1.0

_BACKGROUND = QColor(236, 236, 239)
_PAGE_EDGE = QColor(190, 190, 196)
_EMPTY_TEXT = "No document loaded"

#: Source quad corner order used throughout: top-left, top-right,
#: bottom-right, bottom-left.
_SRC_CORNERS = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


def leaf_projection(
    progress: float, page_w: float, page_h: float, spine_x: float, top_y: float
) -> tuple[QPolygonF, bool] | None:
    """Where the turning leaf lands at `progress` (0 = lying on the right,
    1 = lying on the left), as `(destination_quad, showing_back)`.

    The leaf rotates about the spine, so its projected width is
    `cos(theta)` of a full page and it passes edge-on at the halfway point,
    after which its *back* face is what's toward the reader — mirrored, as
    the back of a real sheet is. The outer edge is drawn slightly inset
    vertically (it's farther from the eye than the spine edge), which is
    what makes the flat trapezoid read as a page tilting rather than merely
    a rectangle being squashed.

    Returns `None` when the leaf is edge-on and has no drawable area — see
    `_MIN_LEAF_WIDTH_PX`.

    Kept a module-level pure function so the geometry can be exercised
    directly, without a window or a running animation.
    """
    theta = progress * math.pi
    projected_w = abs(math.cos(theta)) * page_w
    if projected_w < _MIN_LEAF_WIDTH_PX:
        return None

    showing_back = progress > 0.5
    lift = LEAF_LIFT_FRACTION * page_h * math.sin(theta)
    outer_x = spine_x - projected_w if showing_back else spine_x + projected_w

    # Which of the page's own edges meets the spine flips at the halfway
    # point, and that is what keeps the back face readable rather than
    # mirrored. A recto is bound along its left edge, so its left-hand
    # corners sit at the spine; the verso on the other side of the same
    # sheet is bound along its *right* edge, so its right-hand corners do.
    # Pinning the source's top-left corner to the spine throughout would
    # instead show the verso reversed for the whole second half of the turn
    # and then snap it upright the moment the turn ended.
    #
    # Either way it is the outer edge — the one away from the spine — that
    # gets foreshortened by `lift`, since that is the edge farther from the
    # eye. Corners are returned in `_SRC_CORNERS` order.
    spine_top = (spine_x, top_y)
    spine_bottom = (spine_x, top_y + page_h)
    outer_top = (outer_x, top_y + lift)
    outer_bottom = (outer_x, top_y + page_h - lift)
    corners = (
        (outer_top, spine_top, spine_bottom, outer_bottom)
        if showing_back
        else (spine_top, outer_top, outer_bottom, spine_bottom)
    )
    return QPolygonF([QPointF(x, y) for x, y in corners]), showing_back


def book_layout(widget_w: int, widget_h: int, page_w: float, page_h: float) -> tuple[float, float, float]:
    """Fit an open book — two pages side by side — into the widget,
    returning `(scaled_page_w, scaled_page_h, scale)`.

    Always reserves the full two-page width even when the view being shown
    is a lone cover, so the spine stays at the same place on screen and
    pages don't jump around between views.
    """
    if page_w <= 0 or page_h <= 0 or widget_w <= 0 or widget_h <= 0:
        return 0.0, 0.0, 0.0
    margin = 0.04
    available_w = widget_w * (1 - margin * 2)
    available_h = widget_h * (1 - margin * 2)
    scale = min(available_w / (page_w * 2), available_h / page_h)
    return page_w * scale, page_h * scale, scale


class _Turn:
    """The four page faces involved in one turn, extracted once when the
    turn starts rather than re-cropped every frame."""

    def __init__(
        self,
        left_static: QPixmap | None,
        right_static: QPixmap | None,
        leaf_front: QPixmap | None,
        leaf_back: QPixmap | None,
    ) -> None:
        self.left_static = left_static
        self.right_static = right_static
        self.leaf_front = leaf_front
        self.leaf_back = leaf_back


class PageTurnView(QWidget):
    """Shows one bound-preview view, animating a leaf when moving between
    adjacent views. See the module docstring."""

    #: Asks to move `delta` views (-1 back, +1 forward). Emitted rather than
    #: navigating directly so the view stays ignorant of the document's
    #: bounds and of the thumbnail strip that has to stay in step —
    #: `PdfViewerPane` owns both.
    step_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._document: PdfDocument | None = None
        self._index = 0
        self._cache: dict[int, QPixmap] = {}
        self._spread_width_pt = 0.0
        self._page_height_pt = 0.0
        self._turn: _Turn | None = None
        self._progress = 0.0
        self._turn_duration_ms = TURN_DURATION_MS

        self._animation = QPropertyAnimation(self, b"turn_progress", self)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.finished.connect(self._on_turn_finished)

        self.setMinimumSize(240, 180)
        self.setAutoFillBackground(False)
        # Clicking a page turns it, so take focus on click and accept the
        # arrow keys once focused.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    # --- Animation plumbing ---

    def _get_turn_progress(self) -> float:
        return self._progress

    def _set_turn_progress(self, value: float) -> None:
        self._progress = value
        self.update()

    #: Driven by `_animation`; assigning it repaints.
    turn_progress = Property(float, _get_turn_progress, _set_turn_progress)

    def set_turn_duration_ms(self, duration_ms: int) -> None:
        """Set the turn length. `0` disables animation entirely, so a
        navigation lands on its final state synchronously — which is what
        tests want, since they assert immediately after navigating and
        would otherwise race a running animation."""
        self._turn_duration_ms = max(0, duration_ms)

    def _on_turn_finished(self) -> None:
        self._turn = None
        self._prune_cache()
        self.update()

    def finish_turn(self) -> None:
        """Jump any in-flight turn straight to its end state."""
        if self._animation.state() == QPropertyAnimation.State.Running:
            self._animation.stop()
            self._on_turn_finished()

    # --- Content ---

    def display(self, document: PdfDocument, index: int, previous_index: int | None = None) -> None:
        """Show view `index`, animating the leaf when it's adjacent to
        `previous_index` and jumping otherwise (a thumbnail click can land
        anywhere, and animating a ten-page jump would misrepresent the
        book as much as showing no motion at all)."""
        document_changed = document is not self._document
        if document_changed:
            self._cache.clear()
            self._measure(document)
        self._document = document

        step = 0 if previous_index is None or document_changed else index - previous_index
        self._index = index

        if abs(step) == 1 and self._turn_duration_ms > 0 and not self._is_empty():
            self._start_turn(forward=step > 0)
        else:
            self.finish_turn()
            self._turn = None
            self._prune_cache()
            self.update()

    def clear(self) -> None:
        self._animation.stop()
        self._document = None
        self._turn = None
        self._cache.clear()
        self.update()

    def _measure(self, document: PdfDocument) -> None:
        """Record the spread and page dimensions this document is built
        from. A bound-preview document is a mix of full spreads and
        half-width lone covers, so the widest page defines the spread."""
        if document.page_count == 0:
            self._spread_width_pt = self._page_height_pt = 0.0
            return
        sizes = [document.page_size(i) for i in range(document.page_count)]
        self._spread_width_pt = max(width for width, _ in sizes)
        self._page_height_pt = max(height for _, height in sizes)

    def _is_empty(self) -> bool:
        return self._document is None or self._document.page_count == 0

    def _is_single(self, index: int) -> bool:
        """Whether view `index` is a lone page rather than a spread."""
        if self._document is None or self._spread_width_pt <= 0:
            return False
        width, _ = self._document.page_size(index)
        return width < self._spread_width_pt * 0.75

    def _view_pixmap(self, index: int) -> QPixmap | None:
        if self._document is None or not (0 <= index < self._document.page_count):
            return None
        if index not in self._cache:
            self._cache[index] = QPixmap.fromImage(
                self._document.render_page(index, dpi=PAGE_TURN_RENDER_DPI)
            )
        return self._cache[index]

    def _prune_cache(self) -> None:
        """Hold only the current view and its immediate neighbours. A whole
        book's worth of spreads at display resolution is far too much to
        keep — a few megabytes each — and only the adjacent ones can be
        reached by the next turn anyway."""
        keep = {self._index - 1, self._index, self._index + 1}
        for index in list(self._cache):
            if index not in keep:
                del self._cache[index]

    def _halves(self, index: int) -> tuple[QPixmap | None, QPixmap | None]:
        """The `(left, right)` page faces of view `index`; either may be
        `None`. A lone cover occupies only one side — the first view is a
        recto (it sits to the right of the spine, its verso being the inside
        front cover, which isn't a page), and a trailing lone view is the
        matching verso."""
        pixmap = self._view_pixmap(index)
        if pixmap is None:
            return None, None
        if self._is_single(index):
            return (None, pixmap) if index == 0 else (pixmap, None)
        half = pixmap.width() // 2
        return (
            pixmap.copy(0, 0, half, pixmap.height()),
            pixmap.copy(half, 0, pixmap.width() - half, pixmap.height()),
        )

    def _start_turn(self, *, forward: bool) -> None:
        """Set up the leaf between the previous view and `self._index`.

        A backward turn is the same leaf as the forward one between the same
        pair of views, played in reverse — so both directions are described
        by a single forward setup plus the direction the progress runs.
        """
        earlier = self._index - 1 if forward else self._index
        later = self._index if forward else self._index + 1

        left_static, leaf_front = self._halves(earlier)
        leaf_back, right_static = self._halves(later)
        self._turn = _Turn(left_static, right_static, leaf_front, leaf_back)

        self._animation.stop()
        self._animation.setDuration(self._turn_duration_ms)
        self._animation.setStartValue(0.0 if forward else 1.0)
        self._animation.setEndValue(1.0 if forward else 0.0)
        self._progress = self._animation.startValue()
        self._animation.start()

    # --- Painting ---

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.fillRect(self.rect(), _BACKGROUND)
        if self._is_empty():
            painter.setPen(QColor(120, 120, 126))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _EMPTY_TEXT)
            return

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        page_w, page_h, _ = book_layout(
            self.width(), self.height(), self._spread_width_pt / 2, self._page_height_pt
        )
        if page_w <= 0:
            return
        spine_x = self.width() / 2
        top_y = (self.height() - page_h) / 2

        if self._turn is None:
            left, right = self._halves(self._index)
            self._draw_page(painter, left, spine_x - page_w, top_y, page_w, page_h)
            self._draw_page(painter, right, spine_x, top_y, page_w, page_h)
            return

        self._draw_page(painter, self._turn.left_static, spine_x - page_w, top_y, page_w, page_h)
        self._draw_page(painter, self._turn.right_static, spine_x, top_y, page_w, page_h)
        self._draw_leaf(painter, spine_x, top_y, page_w, page_h)

    def _draw_page(
        self, painter: QPainter, pixmap: QPixmap | None, x: float, y: float, w: float, h: float
    ) -> None:
        if pixmap is None:
            return
        target = QRect(round(x), round(y), round(w), round(h))
        painter.drawPixmap(target, pixmap)
        painter.setPen(_PAGE_EDGE)
        painter.drawRect(target)

    def _draw_leaf(self, painter: QPainter, spine_x: float, top_y: float, page_w: float, page_h: float) -> None:
        projection = leaf_projection(self._progress, page_w, page_h, spine_x, top_y)
        if projection is None:
            return
        destination, showing_back = projection
        face = self._turn.leaf_back if showing_back else self._turn.leaf_front
        if face is None or face.isNull():
            return

        source = QPolygonF(
            [QPointF(fx * face.width(), fy * face.height()) for fx, fy in _SRC_CORNERS]
        )
        transform = QTransform.quadToQuad(source, destination)
        if transform is None:  # degenerate despite the width guard
            return
        painter.save()
        painter.setTransform(transform)
        painter.drawPixmap(0, 0, face)
        painter.restore()
        painter.setPen(_PAGE_EDGE)
        painter.drawPolygon(destination)

    # --- Navigation ---

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Click a page to turn it: the left page goes back, the right page
        goes forward — the same halves you would physically take hold of."""
        if event.button() != Qt.MouseButton.LeftButton or self._is_empty():
            super().mousePressEvent(event)
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.step_requested.emit(-1 if event.position().x() < self.width() / 2 else 1)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Left/Right page through the book, matching the direction the
        pages themselves move."""
        steps = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}
        step = steps.get(Qt.Key(event.key()))
        if step is None or self._is_empty():
            super().keyPressEvent(event)
            return
        event.accept()
        self.step_requested.emit(step)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Take focus when the tab becomes visible, so the arrow keys work
        without having to click first. Deliberately tied to becoming visible
        rather than to `display()`, which also runs while this tab is hidden
        every time the imposition is regenerated — grabbing focus then would
        yank it out of whatever field the user was editing."""
        super().showEvent(event)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
