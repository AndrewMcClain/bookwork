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
    LEAF_STRIP_COUNT,
    PAGE_TURN_RENDER_DPI,
    PageTurnView,
    book_layout,
    cast_shadow_strength,
    edge_stack_width,
    leaf_curve,
    leaf_source_x,
)

PAGE_W, PAGE_H, SPINE_X, TOP_Y = 200.0, 300.0, 500.0, 40.0


def _curve(progress, strips=LEAF_STRIP_COUNT):
    return leaf_curve(progress, PAGE_W, PAGE_H, SPINE_X, TOP_Y, strips)


def _xs(curve):
    return [sample.x for sample in curve.samples]


# --- Leaf geometry ---


def test_leaf_starts_flat_on_the_right():
    curve = _curve(0.0)
    assert curve.showing_back is False
    assert _xs(curve)[0] == pytest.approx(SPINE_X)
    assert _xs(curve)[-1] == pytest.approx(SPINE_X + PAGE_W)
    assert all(sample.inset == pytest.approx(0.0) for sample in curve.samples)


def test_leaf_ends_flat_on_the_left_showing_its_back():
    curve = _curve(1.0)
    assert curve.showing_back is True
    assert _xs(curve)[0] == pytest.approx(SPINE_X)
    assert _xs(curve)[-1] == pytest.approx(SPINE_X - PAGE_W)
    assert all(sample.inset == pytest.approx(0.0) for sample in curve.samples)


def test_spine_end_of_the_leaf_never_moves():
    """It is bound there. If it drifted, the page would look torn loose."""
    for progress in (0.0, 0.2, 0.5, 0.8, 1.0):
        assert _curve(progress).samples[0].x == pytest.approx(SPINE_X)


def test_leaf_lies_flat_at_both_ends_and_curls_in_between():
    """The bow is what separates a turning page from a flat card being
    swung around, but a page resting on the stack has to be flat again."""
    def bow(curve):
        # How far the middle of the page departs from the straight line
        # between its two ends.
        xs = _xs(curve)
        midpoint = len(xs) // 2
        straight = (xs[0] + xs[-1]) / 2
        return abs(xs[midpoint] - straight)

    assert bow(_curve(0.0)) == pytest.approx(0.0, abs=1e-6)
    assert bow(_curve(1.0)) == pytest.approx(0.0, abs=1e-6)
    assert bow(_curve(0.5)) > PAGE_W * 0.05


def test_leaf_is_never_degenerate_even_edge_on():
    """A flat model collapses to zero width at exactly 90 degrees, where
    `quadToQuad` has no solution. A curled page still presents a sliver of
    itself, so the curve has real extent right through the crossover."""
    curve = _curve(0.5)
    span = max(_xs(curve)) - min(_xs(curve))
    assert span > 1.0


@pytest.mark.parametrize("progress", [0.55, 0.75, 0.95, 1.0])
def test_back_face_is_never_mirrored(progress):
    """Regression: the verso used to be drawn reversed for the whole second
    half of the turn, then snap upright when the turn ended.

    A sheet's two sides are bound along opposite edges — a recto along its
    left, the verso on its back along its right — so the page image has to
    be read in the opposite direction once the leaf shows its back.
    """
    curve = _curve(progress)
    assert curve.showing_back is True
    at_spine = leaf_source_x(0.0, 100.0, curve.showing_back)
    at_fore_edge = leaf_source_x(1.0, 100.0, curve.showing_back)
    assert at_spine == pytest.approx(100.0), "verso's right edge belongs at the spine"
    assert at_fore_edge == pytest.approx(0.0)


@pytest.mark.parametrize("progress", [0.0, 0.05, 0.25, 0.45])
def test_front_face_is_never_mirrored(progress):
    curve = _curve(progress)
    assert curve.showing_back is False
    assert leaf_source_x(0.0, 100.0, curve.showing_back) == pytest.approx(0.0)
    assert leaf_source_x(1.0, 100.0, curve.showing_back) == pytest.approx(100.0)


def test_the_face_shown_flips_at_the_halfway_point():
    assert _curve(0.49).showing_back is False
    assert _curve(0.51).showing_back is True


def test_leaf_outer_edge_is_foreshortened_mid_turn():
    """The perspective cue: points lifted out of the book plane have their
    top and bottom edges pulled in."""
    curve = _curve(0.3)
    assert curve.samples[0].inset == pytest.approx(0.0)  # pinned at the spine
    assert curve.samples[-1].inset > 0
    assert curve.samples[-1].depth > curve.samples[0].depth


def test_finished_turn_lands_exactly_on_the_left_page_slot():
    """At full progress the leaf must coincide with where the static left
    page is drawn, or the end of the turn visibly jumps."""
    curve = _curve(1.0)
    assert min(_xs(curve)) == pytest.approx(SPINE_X - PAGE_W)
    assert max(_xs(curve)) == pytest.approx(SPINE_X)


def test_leaf_is_sampled_into_the_requested_number_of_strips():
    assert len(_curve(0.5, strips=8).samples) == 9  # n strips need n+1 edges


# --- Edge stacks ---


def test_edge_stack_is_absent_with_no_leaves():
    assert edge_stack_width(0, scale=1.0, page_w=400.0) == 0.0


def test_edge_stack_width_tracks_real_paper_thickness():
    """The stacks are drawn to scale so their width answers a real question
    — how thick the finished block will be — rather than merely hinting at
    progress. Doubling the leaves doubles the thickness."""
    thin = edge_stack_width(50, scale=1.0, page_w=4000.0)
    thick = edge_stack_width(100, scale=1.0, page_w=4000.0)
    assert thick == pytest.approx(thin * 2)


def test_edge_stack_scales_with_the_view():
    assert edge_stack_width(100, scale=2.0, page_w=4000.0) == pytest.approx(
        edge_stack_width(100, scale=1.0, page_w=4000.0) * 2
    )


def test_edge_stack_stays_visible_for_a_thin_pamphlet():
    """Eight leaves is under a millimetre of paper; honest scaling would
    round it away to nothing."""
    assert edge_stack_width(8, scale=1.0, page_w=400.0) > 0


def test_edge_stack_never_competes_with_the_pages():
    huge = edge_stack_width(100_000, scale=1.0, page_w=400.0)
    assert huge <= 400.0 * 0.25


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


# --- Leaf counts and stacks in the widget ---


def test_leaf_counts_split_the_book_at_the_current_view(qtbot, bound_preview):
    view = _view(qtbot, duration_ms=0)
    total_leaves = bound_preview.page_count - 1

    for index in range(bound_preview.page_count):
        view.display(bound_preview, index)
        left, right = view.leaf_counts()
        assert left == index
        assert left + right == total_leaves


def test_no_leaves_behind_the_covers(qtbot, bound_preview):
    view = _view(qtbot, duration_ms=0)

    view.display(bound_preview, 0)
    assert view.leaf_counts()[0] == 0, "nothing has been turned yet"

    view.display(bound_preview, bound_preview.page_count - 1)
    assert view.leaf_counts()[1] == 0, "nothing is left to turn"


def test_the_leaf_in_flight_belongs_to_neither_stack(qtbot, bound_preview):
    """It is drawn separately, so counting it in a stack too would show one
    more sheet of paper than the book actually has."""
    view = _view(qtbot)
    total_leaves = bound_preview.page_count - 1
    view.display(bound_preview, 2)
    view.display(bound_preview, 3, previous_index=2)

    left, right = view.leaf_counts()

    assert left + right + 1 == total_leaves


def test_leaf_counts_are_the_same_whichever_way_the_turn_runs(qtbot, bound_preview):
    """Turning back across a gap moves the same sheet, so the stacks either
    side of it must be the same as when turning forward."""
    view = _view(qtbot)
    view.display(bound_preview, 2)
    view.display(bound_preview, 3, previous_index=2)
    forward = view.leaf_counts()

    view.display(bound_preview, 2, previous_index=3)

    assert view.leaf_counts() == forward


# --- Backdrop cache ---


def test_backdrop_is_reused_across_frames_of_one_turn(qtbot, bound_preview):
    """The pages and their stacks are most of the painted area and do not
    change while a leaf turns; re-rendering them per frame is what put a
    large window under 60fps."""
    view = _view(qtbot)
    view.display(bound_preview, 1)
    view.display(bound_preview, 2, previous_index=1)

    view.turn_progress = 0.2
    view.render(QPixmap(view.size()))
    first = view._backdrop
    assert first is not None

    view.turn_progress = 0.8
    view.render(QPixmap(view.size()))

    assert view._backdrop is first


def test_backdrop_is_dropped_when_the_view_changes(qtbot, bound_preview):
    view = _view(qtbot)
    view.display(bound_preview, 1)
    view.display(bound_preview, 2, previous_index=1)
    view.render(QPixmap(view.size()))
    assert view._backdrop is not None

    view.display(bound_preview, 3, previous_index=2)

    assert view._backdrop is None


def test_backdrop_is_rebuilt_at_the_new_size_after_a_resize(qtbot, bound_preview):
    """A stale backdrop would be blitted at the wrong size behind the leaf.
    Guarded by the cached size rather than by resizeEvent alone, which Qt
    does not deliver to a widget that has never been shown.
    """
    view = _view(qtbot)
    view.display(bound_preview, 1)
    view.display(bound_preview, 2, previous_index=1)
    view.render(QPixmap(view.size()))

    view.resize(view.width() + 160, view.height() + 80)
    view.render(QPixmap(view.size()))

    ratio = view.devicePixelRatioF()
    assert view._backdrop.size().width() == round(view.width() * ratio)
    assert view._backdrop.size().height() == round(view.height() * ratio)


# --- Cast shadow continuity ---


def test_no_shadow_while_a_page_lies_flat():
    """A page resting on the stack casts nothing visible on the one under it."""
    assert cast_shadow_strength(0.0) == pytest.approx(0.0)
    assert cast_shadow_strength(1.0) == pytest.approx(0.0)


def test_shadow_fades_out_where_it_has_to_change_sides():
    """The leaf shadows the right page for the first half of the turn and
    the left page for the second. Fading to nothing exactly at the crossover
    is what keeps that switch from reading as a flicker."""
    assert cast_shadow_strength(0.5) == pytest.approx(0.0)
    assert cast_shadow_strength(0.49) == pytest.approx(cast_shadow_strength(0.51), abs=1e-9)
    assert cast_shadow_strength(0.45) < cast_shadow_strength(0.3)


def test_shadow_is_strongest_when_the_leaf_leans_over_the_page():
    assert cast_shadow_strength(0.25) == pytest.approx(1.0)
    assert cast_shadow_strength(0.75) == pytest.approx(1.0)


def test_shadow_strength_is_continuous(qtbot):
    """No step anywhere across the turn — a jump would show as a flicker."""
    steps = [cast_shadow_strength(i / 200) for i in range(201)]
    assert max(abs(b - a) for a, b in zip(steps, steps[1:])) < 0.05
