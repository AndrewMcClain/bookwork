"""Tests for bookwork.widgets.page_turn_view.

The geometry is exercised through the module-level pure functions, which
need neither a window nor a running animation. The widget tests then check
the part that actually carries meaning: which page ends up on which face of
the turning leaf. Getting that pairing wrong would misrepresent the book in
exactly the way the Bound Preview tab exists to catch.
"""

from __future__ import annotations

import pymupdf as fitz
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap

from bookwork.imposition import ImpositionParams, build_bound_preview, impose
from bookwork.pdf_document import PdfDocument
from bookwork.widgets.page_turn_view import (
    PAGE_TURN_RENDER_DPI,
    PageTurnView,
    book_layout,
    leaf_projection,
)

PAGE_W, PAGE_H, SPINE_X, TOP_Y = 200.0, 300.0, 500.0, 40.0


def _quad_x(polygon) -> list[float]:
    return [polygon.at(i).x() for i in range(4)]


def _quad_y(polygon) -> list[float]:
    return [polygon.at(i).y() for i in range(4)]


# --- Geometry ---


def test_leaf_starts_flat_on_the_right():
    quad, showing_back = leaf_projection(0.0, PAGE_W, PAGE_H, SPINE_X, TOP_Y)
    assert showing_back is False
    assert min(_quad_x(quad)) == pytest.approx(SPINE_X)
    assert max(_quad_x(quad)) == pytest.approx(SPINE_X + PAGE_W)
    # Flat against the page: no foreshortening yet.
    assert min(_quad_y(quad)) == pytest.approx(TOP_Y)
    assert max(_quad_y(quad)) == pytest.approx(TOP_Y + PAGE_H)


def test_leaf_ends_flat_on_the_left_showing_its_back():
    quad, showing_back = leaf_projection(1.0, PAGE_W, PAGE_H, SPINE_X, TOP_Y)
    assert showing_back is True
    assert max(_quad_x(quad)) == pytest.approx(SPINE_X)
    assert min(_quad_x(quad)) == pytest.approx(SPINE_X - PAGE_W)


@pytest.mark.parametrize("progress", [0.55, 0.75, 0.95, 1.0])
def test_back_face_is_never_mirrored(progress):
    """Regression: the verso used to be drawn reversed for the whole second
    half of the turn, then snap upright when the turn ended.

    A sheet's two sides are bound along opposite edges — a recto along its
    left, the verso on its back along its right — so which of the page's own
    corners sits at the spine has to swap at the halfway point. Pinning the
    source's top-left corner there throughout mirrors the back face.
    """
    quad, showing_back = leaf_projection(progress, PAGE_W, PAGE_H, SPINE_X, TOP_Y)
    assert showing_back is True
    top_left, top_right = quad.at(0), quad.at(1)
    assert top_left.x() < top_right.x(), "back face is mirrored"


@pytest.mark.parametrize("progress", [0.0, 0.05, 0.25, 0.45])
def test_front_face_is_never_mirrored(progress):
    quad, showing_back = leaf_projection(progress, PAGE_W, PAGE_H, SPINE_X, TOP_Y)
    assert showing_back is False
    assert quad.at(0).x() < quad.at(1).x(), "front face is mirrored"


def test_the_page_edge_meeting_the_spine_swaps_with_the_face():
    """A recto is bound along its left edge, its verso along its right."""
    front, _ = leaf_projection(0.25, PAGE_W, PAGE_H, SPINE_X, TOP_Y)
    back, _ = leaf_projection(0.75, PAGE_W, PAGE_H, SPINE_X, TOP_Y)
    assert front.at(0).x() == pytest.approx(SPINE_X)  # recto's left edge
    assert back.at(1).x() == pytest.approx(SPINE_X)  # verso's right edge


def test_finished_turn_lands_exactly_on_the_left_page_slot():
    """At full progress the leaf must coincide with where the static left
    page is drawn, or the end of the turn visibly jumps."""
    quad, _ = leaf_projection(1.0, PAGE_W, PAGE_H, SPINE_X, TOP_Y)
    assert min(_quad_x(quad)) == pytest.approx(SPINE_X - PAGE_W)
    assert max(_quad_x(quad)) == pytest.approx(SPINE_X)
    assert min(_quad_y(quad)) == pytest.approx(TOP_Y)
    assert max(_quad_y(quad)) == pytest.approx(TOP_Y + PAGE_H)


def test_leaf_narrows_toward_the_middle_of_the_turn():
    widths = [
        max(_quad_x(leaf_projection(p, PAGE_W, PAGE_H, SPINE_X, TOP_Y)[0]))
        - min(_quad_x(leaf_projection(p, PAGE_W, PAGE_H, SPINE_X, TOP_Y)[0]))
        for p in (0.0, 0.2, 0.4)
    ]
    assert widths == sorted(widths, reverse=True)


def test_leaf_outer_edge_is_foreshortened_mid_turn():
    """The perspective cue: the edge away from the spine is drawn inset
    vertically, so the page reads as tilting rather than being squashed."""
    quad, _ = leaf_projection(0.3, PAGE_W, PAGE_H, SPINE_X, TOP_Y)
    spine_top, outer_top = quad.at(0).y(), quad.at(1).y()
    spine_bottom, outer_bottom = quad.at(3).y(), quad.at(2).y()
    assert outer_top > spine_top
    assert outer_bottom < spine_bottom


def test_leaf_is_none_when_edge_on():
    """A zero-width quad has no projective solution -- QTransform.quadToQuad
    returns None for it, which would crash the paint path."""
    assert leaf_projection(0.5, PAGE_W, PAGE_H, SPINE_X, TOP_Y) is None


def test_book_layout_reserves_two_pages_and_preserves_aspect():
    page_w, page_h, scale = book_layout(1000, 400, PAGE_W, PAGE_H)
    assert page_w * 2 <= 1000 and page_h <= 400
    assert page_w / page_h == pytest.approx(PAGE_W / PAGE_H)
    assert page_w == pytest.approx(PAGE_W * scale)


def test_book_layout_is_degenerate_safe():
    assert book_layout(0, 0, PAGE_W, PAGE_H) == (0.0, 0.0, 0.0)
    assert book_layout(800, 600, 0, 0) == (0.0, 0.0, 0.0)


# --- Widget behaviour ---


@pytest.fixture
def bound_preview(make_pdf):
    """A real bound-preview document, built through the actual imposition
    pipeline so the views are the genuine single/spread/.../single mix."""
    path = make_pdf(num_pages=12)
    params = ImpositionParams(signature_size_pages=12)
    source = PdfDocument(path)
    imposed = impose(source.fitz_document, params)
    return PdfDocument.from_fitz_document(build_bound_preview(imposed, 12, params), "bp.pdf")


def _view(qtbot, duration_ms=200):
    view = PageTurnView()
    qtbot.addWidget(view)
    view.resize(900, 500)
    view.set_turn_duration_ms(duration_ms)
    return view


def test_adjacent_navigation_starts_a_turn(qtbot, bound_preview):
    view = _view(qtbot)
    view.display(bound_preview, 0)
    assert view._turn is None  # first display has nothing to turn from

    view.display(bound_preview, 1, previous_index=0)
    assert view._turn is not None


def test_non_adjacent_navigation_jumps_without_a_turn(qtbot, bound_preview):
    """A thumbnail click can land anywhere; animating a multi-page jump
    would misrepresent the book as badly as showing no motion at all."""
    view = _view(qtbot)
    view.display(bound_preview, 0)

    view.display(bound_preview, 4, previous_index=0)

    assert view._turn is None


def test_zero_duration_lands_on_the_final_state_synchronously(qtbot, bound_preview):
    view = _view(qtbot, duration_ms=0)
    view.display(bound_preview, 0)

    view.display(bound_preview, 1, previous_index=0)

    assert view._turn is None
    assert view._index == 1


def _image_bytes(pixmap):
    image = pixmap.toImage()
    return image.constBits().tobytes()


def test_leaf_pairs_the_right_page_of_one_view_with_the_left_of_the_next(qtbot, bound_preview):
    """The heart of the feature: a physical leaf carries the recto of the
    spread you're leaving on its front and the verso of the spread you're
    arriving at on its back. Any other pairing would show the reader a
    sheet that can't exist in the bound book.
    """
    view = _view(qtbot)
    view.display(bound_preview, 1)
    expected_front = view._halves(1)[1]  # right-hand page of view 1
    expected_back = view._halves(2)[0]  # left-hand page of view 2

    view.display(bound_preview, 2, previous_index=1)

    assert _image_bytes(view._turn.leaf_front) == _image_bytes(expected_front)
    assert _image_bytes(view._turn.leaf_back) == _image_bytes(expected_back)


def test_turning_back_uses_the_same_leaf_as_turning_forward(qtbot, bound_preview):
    """Going back across the same gap must move the same physical sheet --
    it's one leaf, whichever way the reader flips it."""
    view = _view(qtbot)
    view.display(bound_preview, 1)
    view.display(bound_preview, 2, previous_index=1)
    forward = (_image_bytes(view._turn.leaf_front), _image_bytes(view._turn.leaf_back))

    view.display(bound_preview, 1, previous_index=2)
    backward = (_image_bytes(view._turn.leaf_front), _image_bytes(view._turn.leaf_back))

    assert forward == backward


def test_static_pages_are_the_outer_halves_of_the_pair(qtbot, bound_preview):
    view = _view(qtbot)
    view.display(bound_preview, 1)
    expected_left = view._halves(1)[0]
    expected_right = view._halves(2)[1]

    view.display(bound_preview, 2, previous_index=1)

    assert _image_bytes(view._turn.left_static) == _image_bytes(expected_left)
    assert _image_bytes(view._turn.right_static) == _image_bytes(expected_right)


def test_first_view_is_a_lone_recto_to_the_right_of_the_spine(qtbot, bound_preview):
    """View 0's verso is the inside front cover, which isn't a page -- so it
    sits alone on the right, as a closed book's first page does."""
    view = _view(qtbot)
    view.display(bound_preview, 0)

    left, right = view._halves(0)

    assert left is None
    assert right is not None


def test_trailing_lone_view_sits_to_the_left_of_the_spine(qtbot, bound_preview):
    view = _view(qtbot)
    last = bound_preview.page_count - 1
    view.display(bound_preview, last)

    left, right = view._halves(last)

    assert left is not None
    assert right is None


def test_cache_stays_bounded_while_paging_through(qtbot, bound_preview):
    """A whole book of spreads at display resolution is far too much to
    hold; only the reachable neighbours are worth keeping."""
    view = _view(qtbot, duration_ms=0)
    view.display(bound_preview, 0)
    for index in range(1, bound_preview.page_count):
        view.display(bound_preview, index, previous_index=index - 1)
        assert len(view._cache) <= 3


def test_switching_documents_drops_the_previous_cache(qtbot, bound_preview, make_pdf):
    view = _view(qtbot, duration_ms=0)
    view.display(bound_preview, 1)
    view.render(QPixmap(view.size()))  # rendering is what populates the cache
    assert view._cache

    other = PdfDocument(make_pdf(num_pages=2))
    view.display(other, 0, previous_index=1)

    assert set(view._cache) <= {0}


def test_switching_documents_never_animates_across_them(qtbot, bound_preview, make_pdf):
    """Index adjacency across two different documents is meaningless -- the
    pages aren't neighbours in any book."""
    view = _view(qtbot)
    view.display(bound_preview, 1)

    other = PdfDocument(make_pdf(num_pages=6))
    view.display(other, 2, previous_index=1)

    assert view._turn is None


def test_clear_releases_document_and_cache(qtbot, bound_preview):
    view = _view(qtbot)
    view.display(bound_preview, 1)

    view.clear()

    assert view._document is None
    assert view._cache == {}


def test_painting_mid_turn_does_not_raise(qtbot, bound_preview):
    """Covers the degenerate edge-on frame, which has no projective
    transform and would otherwise blow up inside paintEvent."""
    view = _view(qtbot)
    view.display(bound_preview, 1)
    view.display(bound_preview, 2, previous_index=1)

    for progress in (0.0, 0.25, 0.5, 0.75, 1.0):
        view.turn_progress = progress
        view.render(QPixmap(view.size()))


def test_painting_an_empty_view_does_not_raise(qtbot):
    view = _view(qtbot)
    view.render(QPixmap(view.size()))


def test_render_dpi_is_modest_enough_to_cache_several_views():
    """Guards the memory story: the cache holds a few spreads, so the
    per-view cost has to stay small. At US Letter landscape this is a few
    megabytes each; a large bump here would quietly make paging expensive."""
    assert PAGE_TURN_RENDER_DPI <= 150


def _fraction_differing(a, b, tolerance=12):
    """Fraction of sampled pixels whose channels differ by more than
    `tolerance`. A loose comparison on purpose: the leaf is resampled through
    a projective transform while a static page is a plain scaled blit, so
    they differ slightly at edges even when they coincide geometrically."""
    assert (a.width(), a.height()) == (b.width(), b.height())
    differing = total = 0
    for y in range(0, a.height(), 3):
        for x in range(0, a.width(), 3):
            pa, pb = a.pixelColor(x, y), b.pixelColor(x, y)
            total += 1
            if max(
                abs(pa.red() - pb.red()), abs(pa.green() - pb.green()), abs(pa.blue() - pb.blue())
            ) > tolerance:
                differing += 1
    return differing / max(total, 1)


def test_end_of_turn_matches_the_state_it_lands_in(qtbot, lopsided_bound_preview):
    """Regression for the visible snap at the end of a turn.

    At full progress the leaf covers the left page slot exactly, so the last
    animated frame has to look like the static view that replaces it. It
    didn't: the back face was drawn mirrored, so the verso flipped upright
    the instant the animation finished.
    """
    view = _view(qtbot)
    view.display(lopsided_bound_preview, 1)
    view.display(lopsided_bound_preview, 2, previous_index=1)
    view._animation.stop()

    view.turn_progress = 1.0
    last_frame = QPixmap(view.size())
    view.render(last_frame)

    view._on_turn_finished()  # what the animation does when it completes
    settled = QPixmap(view.size())
    view.render(settled)

    assert _fraction_differing(last_frame.toImage(), settled.toImage()) < 0.02


@pytest.fixture
def lopsided_bound_preview(tmp_path):
    """A bound preview whose pages are strongly asymmetric left-to-right.

    The stock test PDFs are close to horizontally symmetric — a little text
    at the top left of an otherwise blank page — so mirroring one barely
    changes the pixels and a flip is undetectable. Anything checking
    orientation needs content that plainly has a left and a right.
    """
    document = fitz.open()
    for index in range(8):
        page = document.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(40, 40, 260, 750), color=None, fill=(0.15, 0.2, 0.55))
        page.insert_text((300, 400), f"{index + 1}", fontsize=180)
    path = tmp_path / "lopsided.pdf"
    document.save(path)

    params = ImpositionParams(signature_size_pages=8)
    source = PdfDocument(path)
    imposed = impose(source.fitz_document, params)
    return PdfDocument.from_fitz_document(build_bound_preview(imposed, 8, params), "lopsided-bp.pdf")


# --- Click and keyboard navigation ---


def test_clicking_the_right_page_goes_forward(qtbot, bound_preview):
    view = _view(qtbot, duration_ms=0)
    view.display(bound_preview, 1)

    with qtbot.waitSignal(view.step_requested) as caught:
        qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(view.width() * 3 // 4, view.height() // 2))

    assert caught.args == [1]


def test_clicking_the_left_page_goes_back(qtbot, bound_preview):
    view = _view(qtbot, duration_ms=0)
    view.display(bound_preview, 1)

    with qtbot.waitSignal(view.step_requested) as caught:
        qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(view.width() // 4, view.height() // 2))

    assert caught.args == [-1]


@pytest.mark.parametrize(
    ("key", "expected"), [(Qt.Key.Key_Right, 1), (Qt.Key.Key_Left, -1)]
)
def test_arrow_keys_page_through_the_book(qtbot, bound_preview, key, expected):
    view = _view(qtbot, duration_ms=0)
    view.display(bound_preview, 1)

    with qtbot.waitSignal(view.step_requested) as caught:
        qtbot.keyClick(view, key)

    assert caught.args == [expected]


def test_unrelated_keys_are_left_alone(qtbot, bound_preview):
    """Other keys must keep reaching the rest of the app rather than being
    swallowed here."""
    view = _view(qtbot, duration_ms=0)
    view.display(bound_preview, 1)

    received = []
    view.step_requested.connect(received.append)
    qtbot.keyClick(view, Qt.Key.Key_Up)
    qtbot.keyClick(view, Qt.Key.Key_A)

    assert received == []


def test_clicking_an_empty_view_does_nothing(qtbot):
    view = _view(qtbot)
    received = []
    view.step_requested.connect(received.append)

    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    qtbot.keyClick(view, Qt.Key.Key_Right)

    assert received == []
