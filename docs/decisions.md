# Decisions

Things that aren't obvious from the code, and the failures behind them. If
you're about to change something that looks wrong, check here first.

New entries at the end of their section: what was decided, why, what broke.

## Imposition

### The last signature is padded to a multiple of 4, not to a full signature

The conventional behaviour pads full, which wastes paper — a 4-page document
at a 20-page signature size costs 5 sheets instead of 1. We pad to the physical
minimum; `pad_last_signature_to_full` restores the conventional behaviour, and
the tests pinning reference output pass that flag explicitly.

### One resolver turns parameters into signature arguments

`impose`, `build_bound_preview` and `compute_stats` need the same derivation
from `ImpositionParams`. It was written out in four places; it's now
`_SignatureLayout.resolve()`.

The reason matters: if the `impose` and `build_bound_preview` copies drifted,
**Bound Preview would show a different pagination than the sheets that print** —
exactly what that tab exists to catch. Four copies also meant a new parameter
had to be threaded through four sites, and one was missed, which is how presets
came to silently drop a field.

### Crop marks are outward L-ticks at the fitted content rect

Two fixes. They were drawn at the nominal cell boundary, so a page whose aspect
ratio didn't match got letterboxed and the marks pointed at empty space; they
now track `_fitted_content_rect`. They were also a `+` centred on each corner,
putting half of every arm *on the page* — trimming along the mark left ink on
the finished page. Both arms now point outward, meeting the content at one
point.

### Right-to-left binding is a mirror, not a reordering

`right_to_left` changes no page's signature, sheet or neighbour — only which
cell of the sheet side it lands in. Which way round a folded sheet reads is a
fact about how you hold it, not how it folds, so the saddle-stitch maths is
untouched and `compute_stats` returns identical numbers either way.

`_cell_sides` is the single definition of that mapping. `_build_sheets` places
each pair by cell *name* rather than by position, and `reading_order` uses the
same function to find them again for the preview. Naming the cells is what
makes the sharing real: an earlier draft had `_build_sheets` swapping the pair
itself and only *citing* `_cell_sides` in a comment, which is the same
duplication with a note claiming otherwise. If the two disagreed, the Bound
Preview would show a book that isn't the one being printed — the exact failure
that tab exists to catch.

The test asserts the mirror property across every combination of signature
size, endpapers and wrap cover rather than hand-writing each expected layout.
Those paths reach the cell mapping by different routes, and a hand-derived
expectation for each is the easiest place to get one of them wrong.

## Printing

### `setFullPage(True)` is never used

Printers have a hardware margin they can't image into. Forcing "full page"
doesn't grant access to it — it makes Qt claim the whole sheet is printable and
lets the driver silently clip what falls outside. Confirmed on a real laser
printer: content near the edges vanished. Leaving it unset means `pageRect()`
reports the real printable area.

### The painter's origin is already the printable area

Without `setFullPage(True)`, `QPainter`'s origin during a print job is the
printable area's top-left, not the paper's. `pageRect()` reports that area's
position in absolute paper coordinates, so using it as the drawing rect applies
the offset twice and pushes content off the opposite edge. Use its size, not
its position. Found while fixing the clipping above; otherwise it would have
just moved the clip.

### The sheet is shrunk to fit and centred on the paper

An earlier version drew at native size and protected only *content* from
clipping, reasoning that content is the artefact and marks are guidance. That's
backwards: crop marks are what you fold and cut along, so a sheet missing them
can't be trimmed accurately at all. Better a slightly smaller book you can cut
straight.

Centred on the **paper**, not the printable area. The spine runs down the
middle and the sheet is folded along it, so it must land on the paper's
centreline. Hardware margins are routinely asymmetric — the printer this was
developed against reports 16pt top, 10pt bottom — and centring in the printable
area put the sheet 3pt off and hanging over the opposite edge. Symmetric
left/right margins hid it there; asymmetric ones give a visibly off-centre fold.

Scale is bounded by the *larger* margin per axis, doubled: once centred, the
tighter side limits it. Cost: pages come out ~95% of nominal, and the scale is
per-printer, so print a book on one machine.

### Landscape needs the orientation flag, not just a wide page size

`QPageSize` treats its dimensions as *portrait-native*; orientation is a
separate flag. Passing an already-landscape 792×612 leaves it at Portrait —
`pageRect()` looks right in-app, but the metadata a driver reads for feed
direction says Portrait, and it prints portrait. Give `QPageSize` the
narrower-first size and set the flag explicitly.

## Presets

### The persisted field list is derived, not written out

`_FIELDS` was hand-maintained and didn't get `pad_last_signature_to_full`, so
presets saved with it on came back with it off — silently changing both the
imposition and the sheet count. Now derived from
`dataclasses.fields(ImpositionParams)`. Consequence: the settings schema
follows the dataclass, so *renaming* a field orphans saved values.

### Values are converted back to their declared types on load

`QSettings`' ini backend stores everything as text and returns `str` on a fresh
read; within the writing session an in-process cache returns typed values. That
masked a total failure — **saved presets didn't survive a restart at all**, with
`__post_init__` getting `"8"` instead of `8` and raising `TypeError` out of a Qt
slot, so selecting a preset silently did nothing. `bool` needs a string
comparison: Qt writes False as `"false"`, and `bool("false")` is `True`.

## Bound Preview

### It crops from the imposed sheets, never re-renders the source

Re-rendering would give an idealised preview that could agree with you while
the print disagrees. Cropping the real sheets means the preview inherits margin
shift, gutter, crop marks and padding blanks.

### The turning leaf is a curved surface, not a flat plane

A flat trapezoid swung about the spine reads as a card. The leaf is a section
of a cylinder: an arc whose tangent rotates from spine to fore edge, integrated
to place every point, scaled by `sin(theta)` so it's flat at both ends.

Two things fall out rather than needing special cases. The horizontal term
changes sign at halfway — that *is* the leaf passing edge-on and showing its
back. And a curled page still presents a sliver side-on, so it never collapses
to the zero-width shape a flat model hits at 90°, where `quadToQuad` returns
`None`.

`QTransform` maps plane to plane, so the curve is 20 flat strips. Each strip
must draw only its own slice — drawing the whole pixmap through a strip's
transform smears the page across the leaf.

### A recto and its verso are bound along opposite edges

The projection pinned the page image's top-left to the spine regardless of
face. A recto is bound along its left edge; the verso on the back of that same
sheet along its *right*. Getting it wrong drew the verso mirrored for the whole
second half of every turn, then snapped it upright when the turn ended.

### A mirrored turn reverses two things, not one

Right-to-left binding flips which face of the leaf is read backwards
(`leaf_source_x`) *and* which direction the leaf sweeps (`leaf_curve`'s
`direction`). The first composes with the recto/verso reversal above as an
XOR: a right-bound leaf's front is bound along its right edge, so it is the
face read backwards and the back face is read forwards. Applying both
reversals mirrors the text on every face; applying neither mirrors it on
exactly one. Both look like the bug that reversal was added to fix.

Everything else about the turn is genuinely mirror-symmetric — the curl, the
foreshortening, the moment it goes edge-on — which is why `direction` only
ever multiplies the horizontal term.

### Edge stacks are drawn at real paper thickness

`leaves × PAPER_CALIPER_PT` (0.1mm) at display scale — real thickness, not a
progress hint, so the stacks answer how thick the block will be. Legible across
the range: a couple of pixels for a 16-page pamphlet, ~70 for 512 pages.

Line density follows the *drawn width*, not the leaf count; one line per leaf
packs 120 hairlines into a dozen pixels and reads as a solid slab.

Caliper is a module constant. It's a real bookbinding variable and wants to be
configurable, but it isn't an imposition parameter — it changes nothing about
the output.

### The static spread is cached during a turn

Per-frame cost is fill rate, not strip count. The pages and stacks don't change
while a leaf turns and are most of the painted area; redrawing them each frame
put a 2560×1400 window at 48fps. Rendering once per turn and blitting brought
every size back above 60.

### A press does not act; a committed drag is not restarted

Click and drag share a button, so a press stays ambiguous until the pointer
does or doesn't travel — acting on press makes every drag start with a jump.

On release past halfway the drag sets its leaf running *before* telling the
pane, so `display()` must let an in-flight turn to that view land rather than
starting a second one over it. Otherwise the leaf snaps back to the start at
the moment the reader lets go.

## Application

### Every page edit re-imposes through one guarded path

`current_params()` raises `ValueError` on combinations the widgets accept — the
spinbox holds 6, which isn't a multiple of 4. That call was duplicated across
five unguarded sites, where the exception escaped a Qt slot *after* the edit had
landed: Qt logs to stderr, invisible in a packaged app, leaving Imposed and
Bound Preview showing the pre-edit layout. All five now use
`_reimpose_from_panel`.

### Arrow keys are handled by the focused widget, not as shortcuts

As application shortcuts they'd be stolen from every text cursor and spinbox in
the settings form. The view takes focus when the tab becomes visible — tied to
becoming visible, not to `display()`, which also runs while the tab is hidden
on every re-impose and would yank focus mid-edit.

## Testing

### Check that a test fails without its fix

Two bugs here were "covered" by tests that passed either way. The preset
round-trip saved and loaded within one process, hitting `QSettings`' in-process
cache and never doing a real read from disk — exactly where the bug lived;
preset tests now read through a copy of the ini at an unseen path. The
page-turn mirroring test compared renders using near-symmetric test PDFs, where
mirroring barely moves a pixel; it now uses lopsided content and asserts its
own content is asymmetric enough to mean anything.

### Geometry lives in pure functions

`leaf_curve`, `book_layout`, `edge_stack_width`, `cast_shadow_strength` and
`leaf_source_x` are module-level and take plain numbers, so most of the
page-turn suite needs no window and no running animation.

### Animations are zero-duration under test

An autouse fixture patches the turn duration to 0. Without it, tests assert
against a widget mid-animation and can tear it down while a
`QPropertyAnimation` is still driving it.

## Project

### GPL v3, with development dependencies noted

GPL v3-or-later ([COPYING](../COPYING)). PyMuPDF is AGPL v3 and PySide6 LGPL
v3, both compatible — see [third-party.md](third-party.md). `pytest`,
`pytest-qt` and `pyinstaller` aren't in distributed binaries, so their licences
don't constrain ours.
