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
from typing import NamedTuple

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
)
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

#: How far the turning leaf bends, in radians of arc across its width, at
#: the point of the turn where it is most curled. A real page does not stay
#: rigid: it bows away from the spine under its own weight and the hand
#: turning it, and that bow is most of what distinguishes a turning page
#: from a flat card being swung around. Scaled by `sin(theta)` so the leaf
#: is genuinely flat at both ends of the turn.
LEAF_CURL_RADIANS = 1.15

#: The curved leaf is drawn as this many flat strips. `QTransform` maps a
#: quad to a quad, which is a plane, so a curve has to be approximated
#: piecewise. Enough strips to read as smooth, few enough to stay cheap.
LEAF_STRIP_COUNT = 20

#: A strip narrower than this has no drawable area and no projective
#: solution — `QTransform.quadToQuad` returns None for a degenerate quad.
_MIN_STRIP_WIDTH_PX = 0.25

#: Thickness of one sheet, used to draw the page-edge stacks. 0.1mm is
#: about right for 80gsm bond. The stacks are drawn to this scale rather
#: than stylised, so their width answers a real question — how thick is the
#: finished text block — instead of merely hinting at progress. That holds up
#: across realistic sizes: a 16-page pamphlet shows a couple of pixels, a
#: 512-page book about seventy.
PAPER_CALIPER_PT = 0.1 * 72 / 25.4

#: A stack never vanishes entirely while leaves remain on that side, and
#: never grows so wide it competes with the pages themselves.
_MIN_STACK_PX = 1.5
_MAX_STACK_FRACTION_OF_PAGE = 0.22

#: Individual leaf edges stop being distinguishable long before a thick
#: book's leaf count, and drawing thousands of hairlines just muddies the
#: band; past this the fill alone carries the thickness.
_MAX_STACK_LINES = 80

#: Leaf edges are drawn no closer together than this. Density has to follow
#: the drawn width, not the leaf count: a 240-page book packs its 120 leaves
#: into about a dozen pixels, and one line per leaf there merges into a flat
#: grey band that reads as a solid slab rather than a stack of paper.
_MIN_STACK_LINE_SPACING_PX = 2.5

#: How dark the turning leaf gets toward the spine, and how dark a shadow it
#: casts on the page beneath. Both peak side-on and vanish when the leaf is
#: flat, which is what stops a flat page from looking tinted for no reason.
_LEAF_SHADE_ALPHA = 46
_CAST_SHADOW_ALPHA = 52
_CAST_SHADOW_REACH = 0.45

#: Pointer travel before a press counts as a drag rather than a click. Below
#: this a click still pages, so the two gestures coexist on one button.
_DRAG_THRESHOLD_PX = 5

#: Released past this much of the turn, the leaf carries on and the page
#: changes; short of it, it falls back where it came from. Half is the
#: honest place for it — the leaf goes wherever it was nearer to.
_DRAG_COMMIT_FRACTION = 0.5

_BACKGROUND = QColor(236, 236, 239)
_PAGE_EDGE = QColor(190, 190, 196)
_STACK_FILL = QColor(246, 245, 242)
_STACK_FILL_OUTER = QColor(206, 204, 198)
_STACK_LINE = QColor(178, 176, 170)
_EMPTY_TEXT = "No document loaded"

#: Source quad corner order used throughout: top-left, top-right,
#: bottom-right, bottom-left.
_SRC_CORNERS = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


class _LeafSample(NamedTuple):
    """One cross-section of the turning leaf.

    `u` runs 0 at the spine to 1 at the fore edge. `x` is where that point
    lands on screen, `inset` how far the page's top and bottom edges pull
    in there (foreshortening), and `depth` how far out of the flat book
    plane it has risen — used for shading, since the bulge of the curl
    catches more light than the trough by the spine.
    """

    u: float
    x: float
    inset: float
    depth: float


class LeafCurve(NamedTuple):
    """The turning leaf's shape at one instant, sampled across its width."""

    samples: tuple[_LeafSample, ...]
    showing_back: bool

    def outline(self, top_y: float, page_h: float) -> QPolygonF:
        """The leaf's silhouette — down the top edge and back along the
        bottom — for drawing its border as one continuous curve rather than
        per strip, which would show seams."""
        top = [QPointF(sample.x, top_y + sample.inset) for sample in self.samples]
        bottom = [
            QPointF(sample.x, top_y + page_h - sample.inset) for sample in reversed(self.samples)
        ]
        return QPolygonF(top + bottom)


def leaf_curve(
    progress: float,
    page_w: float,
    page_h: float,
    spine_x: float,
    top_y: float,
    strips: int = LEAF_STRIP_COUNT,
) -> LeafCurve:
    """Sample the turning leaf across its width at `progress` (0 = lying on
    the right, 1 = lying on the left).

    The leaf is modelled as a section of a cylinder: its cross-section is an
    arc of `LEAF_CURL_RADIANS` (scaled by how far through the turn it is),
    with the tangent rotating steadily from one end to the other. Integrating
    that tangent gives the position of every point along the page, which is
    why the spine end stays put while the fore edge sweeps across — exactly
    how a bound page has to move.

    Two things fall out of this rather than needing special cases. The
    horizontal term changes sign past the halfway point, which *is* the leaf
    passing edge-on and beginning to show its back. And because a curled page
    still presents a sliver of itself side-on, the leaf never collapses to
    the zero-width shape a flat model degenerates to at exactly 90 degrees.

    `top_y` is accepted for symmetry with the rest of the drawing code; the
    samples are vertical-offset-free and are positioned against it by the
    caller.
    """
    theta = progress * math.pi
    curl = LEAF_CURL_RADIANS * math.sin(theta)
    start_angle = theta - curl / 2

    samples = []
    for step in range(strips + 1):
        u = step / strips
        if abs(curl) < 1e-6:
            # Straight-page limit: the arc formulae below are 0/0 here.
            x_fraction = u * math.cos(theta)
            depth = u * math.sin(theta)
        else:
            angle = start_angle + curl * u
            x_fraction = (math.sin(angle) - math.sin(start_angle)) / curl
            depth = (math.cos(start_angle) - math.cos(angle)) / curl
        samples.append(
            _LeafSample(
                u=u,
                x=spine_x + page_w * x_fraction,
                inset=LEAF_LIFT_FRACTION * page_h * depth,
                depth=depth,
            )
        )
    return LeafCurve(tuple(samples), showing_back=math.cos(theta) < 0)


def leaf_source_x(u: float, face_width: float, showing_back: bool) -> float:
    """Where `u` — measured from the spine — falls on the page image.

    A recto is bound along its left edge, so `u` runs left to right across
    it. The verso on the back of that same sheet is bound along its *right*
    edge, so it runs the other way. Reversing here is what keeps the back
    face readable instead of mirrored once the leaf passes edge-on.
    """
    return (1.0 - u) * face_width if showing_back else u * face_width


def edge_stack_width(leaves: int, scale: float, page_w: float) -> float:
    """Drawn width of a stack of `leaves` sheets at display `scale`.

    Real thickness, not a stylised progress hint: `leaves` sheets of
    `PAPER_CALIPER_PT` each, scaled the same way the pages are. That is
    what lets the two stacks answer how thick the finished block will be,
    and it stays legible across realistic sizes — a 16-page pamphlet
    shows a couple of pixels, a 512-page book about seventy.

    Clamped at both ends: never invisible while leaves remain on that
    side, and never wide enough to compete with the pages themselves
    (the cap only bites for implausibly thick books, where the exact
    width has stopped being informative anyway).
    """
    if leaves <= 0 or page_w <= 0 or scale <= 0:
        return 0.0
    true_width = leaves * PAPER_CALIPER_PT * scale
    return min(max(true_width, _MIN_STACK_PX), page_w * _MAX_STACK_FRACTION_OF_PAGE)

def cast_shadow_strength(progress: float) -> float:
    """How strongly the raised leaf darkens the page beneath it.

    Follows `|sin(2*theta)|`, which falls to nothing at three points:
    flat at either end of the turn, where a page resting on the stack
    casts no visible shadow, and straight up in the middle. That last one
    is the important one — the shadow has to change sides as the leaf
    passes vertical, and fading it out exactly there is what stops the
    switch from reading as a flicker.
    """
    return abs(math.sin(2 * progress * math.pi))

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
    turn starts rather than re-cropped every frame, plus the pair of views
    it runs between (which fixes how many leaves are stacked on each side
    while one is in the air)."""

    def __init__(
        self,
        left_static: QPixmap | None,
        right_static: QPixmap | None,
        leaf_front: QPixmap | None,
        leaf_back: QPixmap | None,
        earlier_index: int,
        later_index: int,
        forward: bool,
    ) -> None:
        self.left_static = left_static
        self.right_static = right_static
        self.leaf_front = leaf_front
        self.leaf_back = leaf_back
        self.earlier_index = earlier_index
        self.later_index = later_index
        self.forward = forward

    @property
    def target_index(self) -> int:
        """The view this turn arrives at if it runs to completion."""
        return self.later_index if self.forward else self.earlier_index

    @property
    def settled_progress(self) -> float:
        """The progress value at which this turn has completed."""
        return 1.0 if self.forward else 0.0

    @property
    def start_progress(self) -> float:
        return 0.0 if self.forward else 1.0


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
        self._backdrop: QPixmap | None = None
        self._progress = 0.0
        self._press_origin: QPointF | None = None
        self._dragging = False
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
        self._backdrop = None
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

        # A drag that was released past the halfway point already set its
        # leaf running toward this very view before telling the pane. Left to
        # itself the pane would then start a second turn over the top of it,
        # snapping the leaf back to the start; instead let the one in flight
        # land.
        if not document_changed and self._turn is not None and self._turn.target_index == index:
            self._index = index
            return

        self._index = index
        self._backdrop = None

        if abs(step) == 1 and self._turn_duration_ms > 0 and not self._is_empty():
            self._start_turn(forward=step > 0)
        else:
            self.finish_turn()
            self._turn = None
            self._prune_cache()
            self.update()

    def clear(self) -> None:
        self._animation.stop()
        self._press_origin = None
        self._dragging = False
        self._document = None
        self._turn = None
        self._backdrop = None
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

    def _prepare_turn(self, earlier: int, later: int, *, forward: bool) -> bool:
        """Assemble the leaf between two adjacent views, ready to be driven
        either by the animation or by a drag. Returns False when there is no
        such leaf — at either end of the book there is nothing to turn.

        A backward turn is the same physical leaf as the forward one across
        the same gap, so both directions share this one setup and differ
        only in which end the progress runs toward.
        """
        if self._document is None or earlier < 0 or later >= self._document.page_count:
            return False
        left_static, leaf_front = self._halves(earlier)
        leaf_back, right_static = self._halves(later)
        self._turn = _Turn(
            left_static, right_static, leaf_front, leaf_back, earlier, later, forward
        )
        self._backdrop = None  # the static pages either side of the leaf changed
        return True

    def _start_turn(self, *, forward: bool) -> None:
        """Set up and animate the leaf between the previous view and
        `self._index`, which `display` has already moved to the target."""
        earlier = self._index - 1 if forward else self._index
        later = self._index if forward else self._index + 1
        if not self._prepare_turn(earlier, later, forward=forward):
            return
        self._animate_to(self._turn.settled_progress, from_progress=self._turn.start_progress)

    def _animate_to(self, end: float, *, from_progress: float | None = None) -> None:
        """Run the leaf to `end`, over a duration proportional to how far it
        still has to go — a leaf released close to the stack should drop
        onto it rather than take a full turn's worth of time to cover the
        last sliver."""
        start = self._progress if from_progress is None else from_progress
        self._progress = start
        remaining = abs(end - start)
        self._animation.stop()
        self._animation.setDuration(max(int(self._turn_duration_ms * remaining), 0))
        self._animation.setStartValue(start)
        self._animation.setEndValue(end)
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

        page_w, page_h, scale = book_layout(
            self.width(), self.height(), self._spread_width_pt / 2, self._page_height_pt
        )
        if page_w <= 0:
            return
        spine_x = self.width() / 2
        top_y = (self.height() - page_h) / 2

        if self._turn is None:
            painter.fillRect(self.rect(), _BACKGROUND)
            self._paint_spread(painter, spine_x, top_y, page_w, page_h, scale)
            return

        # Everything but the leaf is identical from frame to frame, and it is
        # most of the painted area — the pages, their edge stacks, the
        # background. Redrawing it per frame is what put a large window under
        # 60fps, so it is rendered once per turn and blitted after that.
        painter.drawPixmap(0, 0, self._backdrop_for(spine_x, top_y, page_w, page_h, scale))
        self._draw_cast_shadow(painter, spine_x, top_y, page_w, page_h)
        self._draw_leaf(painter, spine_x, top_y, page_w, page_h)

    def _backdrop_for(
        self, spine_x: float, top_y: float, page_w: float, page_h: float, scale: float
    ) -> QPixmap:
        """The static half of the scene, rendered once and reused for every
        frame of the current turn."""
        ratio = self.devicePixelRatioF()
        expected = QSize(round(self.width() * ratio), round(self.height() * ratio))
        if self._backdrop is not None and self._backdrop.size() == expected:
            return self._backdrop

        backdrop = QPixmap(expected)
        backdrop.setDevicePixelRatio(ratio)
        backdrop.fill(_BACKGROUND)
        into = QPainter(backdrop)
        into.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        into.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_spread(into, spine_x, top_y, page_w, page_h, scale)
        into.end()
        self._backdrop = backdrop
        return backdrop

    def _paint_spread(
        self, painter: QPainter, spine_x: float, top_y: float, page_w: float, page_h: float, scale: float
    ) -> None:
        """Both pages and the edge stacks behind them — the parts that hold
        still while a leaf turns."""
        leaves_left, leaves_right = self.leaf_counts()
        if self._turn is None:
            left, right = self._halves(self._index)
        else:
            left, right = self._turn.left_static, self._turn.right_static

        for pixmap, leaves, side in ((left, leaves_left, -1), (right, leaves_right, 1)):
            page_x = spine_x - page_w if side < 0 else spine_x
            self._draw_edge_stack(
                painter,
                leaves=leaves,
                fore_edge_x=page_x if side < 0 else page_x + page_w,
                side=side,
                top_y=top_y,
                page_h=page_h,
                page_w=page_w,
                scale=scale,
            )
            self._draw_page(painter, pixmap, page_x, top_y, page_w, page_h)

    def leaf_counts(self) -> tuple[int, int]:
        """How many leaves are stacked on each side, `(left, right)`.

        Each step between adjacent views is exactly one leaf, so the view
        index *is* the count already turned. While a turn is running the
        leaf in flight belongs to neither stack — it is drawn separately —
        so the two counts and the flying leaf together still account for
        every leaf in the book.
        """
        if self._is_empty():
            return 0, 0
        total_leaves = self._document.page_count - 1
        if self._turn is None:
            return self._index, total_leaves - self._index
        return self._turn.earlier_index, total_leaves - self._turn.later_index

    def _draw_edge_stack(
        self,
        painter: QPainter,
        *,
        leaves: int,
        fore_edge_x: float,
        side: int,
        top_y: float,
        page_h: float,
        page_w: float,
        scale: float,
    ) -> None:
        """Draw the edges of the leaves stacked behind one page, along its
        fore edge — the side away from the spine.

        Width is the real thickness of that many sheets (`PAPER_CALIPER_PT`)
        at the current display scale, so the two stacks together show how
        thick the finished block will be and how far through it you are.
        Seen straight on a stack of identical pages would show no thickness
        at all, so the band is tapered slightly toward its outer edge — the
        small amount of "seen from above" needed for it to read as depth.
        """
        width = edge_stack_width(leaves, scale, page_w)
        if width <= 0:
            return
        outer_x = fore_edge_x + side * width
        taper = min(width * 0.5, page_h * 0.02)

        band = QPolygonF(
            [
                QPointF(fore_edge_x, top_y),
                QPointF(outer_x, top_y + taper),
                QPointF(outer_x, top_y + page_h - taper),
                QPointF(fore_edge_x, top_y + page_h),
            ]
        )
        gradient = QLinearGradient(fore_edge_x, 0.0, outer_x, 0.0)
        gradient.setColorAt(0.0, _STACK_FILL)
        gradient.setColorAt(1.0, _STACK_FILL_OUTER)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawPolygon(band)

        # Individual leaf edges, while they are still far enough apart to
        # tell apart; beyond that the fill alone carries the thickness.
        line_count = min(leaves, _MAX_STACK_LINES, int(width / _MIN_STACK_LINE_SPACING_PX))
        if line_count > 1:
            painter.setPen(QPen(_STACK_LINE, 0.7))
            for step in range(1, line_count):
                fraction = step / line_count
                x = fore_edge_x + side * width * fraction
                inset = taper * fraction
                painter.drawLine(QPointF(x, top_y + inset), QPointF(x, top_y + page_h - inset))

        painter.setPen(QPen(_PAGE_EDGE, 0.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(band)
        painter.restore()

    def _draw_cast_shadow(
        self, painter: QPainter, spine_x: float, top_y: float, page_w: float, page_h: float
    ) -> None:
        """Darken the page beneath the raised leaf, strongest at the spine.

        Strength follows `sin(2*theta)`, which peaks when the leaf leans
        about halfway over the page beneath and falls to nothing at three
        points: flat at either end of the turn, where a page resting on the
        stack casts no visible shadow, and straight up in the middle. That
        last one matters — the shadow has to change sides as the leaf passes
        vertical, and fading it out exactly there is what stops the switch
        from reading as a flicker.
        """
        lift = cast_shadow_strength(self._progress)
        if lift <= 0.01:
            return
        side = -1 if self._progress > 0.5 else 1
        reach = page_w * _CAST_SHADOW_REACH
        gradient = QLinearGradient(spine_x, 0.0, spine_x + side * reach, 0.0)
        gradient.setColorAt(0.0, QColor(0, 0, 0, int(_CAST_SHADOW_ALPHA * lift)))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        left = spine_x if side > 0 else spine_x - reach
        painter.drawRect(QRectF(left, top_y, reach, page_h))
        painter.restore()

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
        curve = leaf_curve(self._progress, page_w, page_h, spine_x, top_y)
        face = self._turn.leaf_back if curve.showing_back else self._turn.leaf_front
        if face is None or face.isNull():
            return

        shade_strength = math.sin(self._progress * math.pi)
        deepest = max((sample.depth for sample in curve.samples), default=0.0)

        painter.save()
        # Strips share exact edges; antialiasing them would leave a hairline
        # seam down every join. The pixmap sampling stays smooth.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for near, far in zip(curve.samples, curve.samples[1:]):
            self._draw_leaf_strip(
                painter, face, curve.showing_back, near, far, top_y, page_h, shade_strength, deepest
            )
        painter.restore()

        painter.setPen(_PAGE_EDGE)
        painter.drawPolygon(curve.outline(top_y, page_h))

    def _draw_leaf_strip(
        self,
        painter: QPainter,
        face: QPixmap,
        showing_back: bool,
        near: _LeafSample,
        far: _LeafSample,
        top_y: float,
        page_h: float,
        shade_strength: float,
        deepest: float,
    ) -> None:
        """Draw one flat slice of the curved leaf.

        Each strip is a plane, which is all `QTransform` can map to; the
        curve comes from there being many of them. The source slice is taken
        by `u` rather than by screen position, so the reversal that keeps the
        back face readable is handled in one place.
        """
        if abs(far.x - near.x) < _MIN_STRIP_WIDTH_PX:
            return
        near_source = leaf_source_x(near.u, face.width(), showing_back)
        far_source = leaf_source_x(far.u, face.width(), showing_back)

        source = QPolygonF(
            [
                QPointF(near_source, 0.0),
                QPointF(far_source, 0.0),
                QPointF(far_source, float(face.height())),
                QPointF(near_source, float(face.height())),
            ]
        )
        destination = QPolygonF(
            [
                QPointF(near.x, top_y + near.inset),
                QPointF(far.x, top_y + far.inset),
                QPointF(far.x, top_y + page_h - far.inset),
                QPointF(near.x, top_y + page_h - near.inset),
            ]
        )
        transform = QTransform.quadToQuad(source, destination)
        if transform is None:
            return

        painter.save()
        painter.setTransform(transform)
        # Draw only this strip's slice, positioned where it sits in the page
        # image. Drawing the whole pixmap would smear the entire page through
        # a transform built for one narrow slice of it.
        slice_rect = QRectF(
            min(near_source, far_source), 0.0, abs(far_source - near_source), float(face.height())
        )
        painter.drawPixmap(slice_rect, face, slice_rect)
        # Shade by how deep in the curl this strip sits: the trough against
        # the spine catches least light, the crest of the bow most.
        if shade_strength > 0.01 and deepest > 1e-6:
            depth_fraction = (near.depth + far.depth) / 2 / deepest
            alpha = int(_LEAF_SHADE_ALPHA * shade_strength * (1.0 - depth_fraction))
            if alpha > 0:
                painter.fillRect(slice_rect, QColor(0, 0, 0, alpha))
        painter.restore()

    # --- Navigation ---

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Take hold of a page. Nothing moves yet — whether this becomes a
        click or a drag is only known once the pointer does or doesn't
        travel (see `mouseMoveEvent`)."""
        if event.button() != Qt.MouseButton.LeftButton or self._is_empty():
            super().mousePressEvent(event)
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._press_origin = event.position()
        self._dragging = False

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Drag a page across and the leaf follows the pointer, so the turn
        happens at whatever pace the hand moves rather than a fixed one."""
        if self._press_origin is None:
            super().mouseMoveEvent(event)
            return
        if not self._dragging:
            travelled = (event.position() - self._press_origin).manhattanLength()
            if travelled < _DRAG_THRESHOLD_PX:
                return
            if not self._begin_drag():
                self._press_origin = None  # nothing to turn on that side
                return
        self._animation.stop()
        self.turn_progress = self._progress_at(event.position().x())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Let go. A press that never travelled is a click and pages as
        before; a drag settles whichever way it was nearer to."""
        if event.button() != Qt.MouseButton.LeftButton or self._press_origin is None:
            super().mouseReleaseEvent(event)
            return
        origin, dragging = self._press_origin, self._dragging
        self._press_origin = None
        self._dragging = False
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        if not dragging:
            self.step_requested.emit(-1 if origin.x() < self.width() / 2 else 1)
            return
        self._settle_drag()

    def _begin_drag(self) -> bool:
        """Assemble the leaf under the pointer. Which one it is follows the
        half of the spread the press landed on — the same halves a click
        uses, and the ones you would physically take hold of."""
        forward = self._press_origin.x() >= self.width() / 2
        earlier = self._index if forward else self._index - 1
        later = self._index + 1 if forward else self._index
        if not self._prepare_turn(earlier, later, forward=forward):
            return False
        self._dragging = True
        self._progress = self._turn.start_progress
        self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        return True

    def _progress_at(self, pointer_x: float) -> float:
        """Where in the turn the leaf has to be for its fore edge to sit
        under the pointer.

        The fore edge follows `cos(theta)` across a page width either side of
        the spine (see `leaf_curve`), so inverting that puts the edge of the
        page under the finger — which is what makes the drag feel attached to
        the paper rather than merely correlated with it.

        Inverting `cos` alone ignores the slight foreshortening the curl adds,
        which is not invertible in closed form. Measured, that leaves the edge
        at most about 2% of a page width from the pointer, exact at both ends
        and at the spine — far below anything the hand notices, and not worth
        iterating for.
        """
        page_w, _, _ = book_layout(
            self.width(), self.height(), self._spread_width_pt / 2, self._page_height_pt
        )
        if page_w <= 0:
            return self._progress
        fraction = (pointer_x - self.width() / 2) / page_w
        return math.acos(max(-1.0, min(1.0, fraction))) / math.pi

    def _settle_drag(self) -> None:
        """Run the released leaf to whichever end it was nearer, and tell
        the pane only if the page actually changed."""
        if self._turn is None:
            return
        turn = self._turn
        past_halfway = (
            self._progress > _DRAG_COMMIT_FRACTION
            if turn.forward
            else self._progress < _DRAG_COMMIT_FRACTION
        )
        if not past_halfway:
            self._animate_to(turn.start_progress)
            return

        # Start the leaf on its way *before* announcing the move: `display`
        # spots the turn already heading for this view and lets it land
        # instead of starting another.
        self._animate_to(turn.settled_progress)
        self.step_requested.emit(1 if turn.forward else -1)

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

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._backdrop = None

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Take focus when the tab becomes visible, so the arrow keys work
        without having to click first. Deliberately tied to becoming visible
        rather than to `display()`, which also runs while this tab is hidden
        every time the imposition is regenerated — grabbing focus then would
        yank it out of whatever field the user was editing."""
        super().showEvent(event)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
