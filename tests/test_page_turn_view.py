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


def test_leaf_is_mirrored_once_its_back_is_toward_the_reader():
    """The source's top-left corner maps to the spine throughout; when the
    outer edge crosses to the left of the spine that same corner order
    describes a flipped page, which is what the back of a sheet looks like."""
    front, _ = leaf_projection(0.25, PAGE_W, PAGE_H, SPINE_X, TOP_Y)
    back, _ = leaf_projection(0.75, PAGE_W, PAGE_H, SPINE_X, TOP_Y)
    # Corner 0 (source top-left) sits at the spine in both cases...
    assert front.at(0).x() == pytest.approx(SPINE_X)
    assert back.at(0).x() == pytest.approx(SPINE_X)
    # ...but corner 1 (source top-right) swaps sides, which is the mirroring.
    assert front.at(1).x() > SPINE_X
    assert back.at(1).x() < SPINE_X


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
    from PySide6.QtGui import QPixmap

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
    from PySide6.QtGui import QPixmap

    view = _view(qtbot)
    view.display(bound_preview, 1)
    view.display(bound_preview, 2, previous_index=1)

    for progress in (0.0, 0.25, 0.5, 0.75, 1.0):
        view.turn_progress = progress
        view.render(QPixmap(view.size()))


def test_painting_an_empty_view_does_not_raise(qtbot):
    from PySide6.QtGui import QPixmap

    view = _view(qtbot)
    view.render(QPixmap(view.size()))


def test_render_dpi_is_modest_enough_to_cache_several_views():
    """Guards the memory story: the cache holds a few spreads, so the
    per-view cost has to stay small. At US Letter landscape this is a few
    megabytes each; a large bump here would quietly make paging expensive."""
    assert PAGE_TURN_RENDER_DPI <= 150
