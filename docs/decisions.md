# Decisions

Choices that are not obvious from reading the code, and the failures that
motivated them. If you are about to change something here, the entry probably
explains why it looks the way it does.

New entries go at the end of their section. Say what was decided, why, and what
broke if something did.

## Imposition

### The last signature is padded to a multiple of 4, not to a full signature

`psbook` always pads a trailing partial signature up to the full signature
length. That is uniform but wasteful: a 4-page document at a 20-page signature
size costs 5 sheets instead of 1. Bookwork pads only to the physical minimum by
default, with `pad_last_signature_to_full` to restore `psbook`'s behaviour.

The tests that pin exact `psbook` output pass that flag explicitly, so they
still verify compatibility rather than quietly encoding the new default.

### One resolver turns parameters into signature arguments

`impose`, `build_bound_preview` and `compute_stats` all need the same
derivation from `ImpositionParams` — leading/trailing blanks, whether a cover
folio is split off, padding mode. That was originally written out in four
places.

It is now `_SignatureLayout.resolve()`. The reason matters: if the `impose` copy
and the `build_bound_preview` copy ever drifted, **Bound Preview would show a
different pagination than the sheets that actually print** — precisely the class
of bug that tab exists to catch. Four copies also meant a new parameter had to
be threaded through four call sites, and one was missed, which is how presets
came to silently drop a field.

### Crop marks are outward L-ticks at the fitted content rect

Two separate fixes ended up here.

They were originally drawn at the nominal cell boundary. After aspect-ratio
fitting, a page that does not match its cell's proportions is letterboxed, so
the marks pointed at empty space. They now track `_fitted_content_rect`, which
reproduces PyMuPDF's own placement maths.

They were also a `+` centred on each corner, which puts half of every arm *on
the page*. Trimming along the mark left ink on the finished page. Both arms now
point outward into the margin, meeting the content at exactly one point.

## Printing

### `setFullPage(True)` is never used

Most real printers — laser especially — have a hardware margin they cannot image
into. Forcing "full page" does not grant access to it; it makes Qt claim the
whole sheet is printable and lets the driver silently clip whatever falls
outside. Confirmed against a real laser printer: content near the edges simply
vanished.

Leaving it unset means `pageRect()` reports the real printable area, which
`print_document` fits into.

### The painter's origin is already the printable area

Without `setFullPage(True)`, `QPainter`'s coordinate origin during a print job
is the top-left of the *printable area*, not the paper. `pageRect()` reports
that area's position in absolute paper coordinates. Using it directly as the
drawing rect therefore applies the offset twice, pushing content off the
opposite edge by the amount it was pulled in on this one.

Use its size, not its position. This was found while fixing the clipping above
and would otherwise have just moved the clip to the other edge.

### Content is protected from clipping; crop marks are not

Shrinking every page to fit the printable area works but introduces a phantom
margin, making the trim size slightly smaller than configured. Since imposition
already guarantees content stays `margin_pt` clear of the sheet edge, print time
computes the minimum scale needed to keep *that region* inside the printable
area — usually 1.0, i.e. no shrink at all.

The trade: on a printer whose hardware margin exceeds the configured margin, the
crop marks nearest that edge may clip. That is deliberate. Marks are guidance;
content is the artefact.

### Landscape needs the orientation flag, not just a wide page size

`QPageSize` treats its width/height as the page's *portrait-native* size.
`QPrinter` has a separate orientation flag. Passing an already-landscape
792×612 leaves that flag at Portrait: `pageRect()` comes out the right shape, so
it looks correct in-app, but the metadata a driver reads to decide feed
direction says Portrait — and it prints portrait. Confirmed on real hardware.

Always give `QPageSize` the narrower-first size and set the orientation flag
explicitly.

## Presets

### The persisted field list is derived, not written out

`_FIELDS` used to be a hand-maintained tuple. When
`pad_last_signature_to_full` was added it was not, so presets saved with it on
came back with it off — silently changing both the imposition and the sheet
count from what was saved.

It is now derived from `dataclasses.fields(ImpositionParams)`. Note the
consequence: the settings schema follows the dataclass, so *renaming* a field
orphans previously-saved values under the old key.

### Values are converted back to their declared types on load

`QSettings`' ini backend — what Qt uses natively on Linux, and what the tests
use everywhere — stores everything as text and returns `str` on a genuinely
fresh read. Within the session that wrote them, an in-process cache returns the
original typed values.

That masked a total failure: **saved presets did not survive an application
restart at all.** On restart `ImpositionParams.__post_init__` received `"8"`
instead of `8` and raised `TypeError` out of a Qt slot, so selecting a preset
silently did nothing.

`load_preset` now converts using the declared field types. `bool` needs an
explicit string comparison — Qt writes False as the literal `"false"`, and
`bool("false")` is `True`.

## Bound Preview

### It crops from the imposed sheets, never re-renders the source

Re-rendering from the source would produce an idealised preview that could agree
with you while the actual print disagrees. Cropping the already-imposed sheets
means the preview inherits every real effect — margin shift, gutter, crop marks,
padding blanks — so a pagination mistake shows up exactly as a reader would meet
it.

### The turning leaf is a curved surface, not a flat plane

A flat trapezoid swung about the spine reads as a card, not paper. The leaf is
modelled as a section of a cylinder: the cross-section is an arc whose tangent
rotates steadily from spine to fore edge, integrated to place every point, with
the bend scaled by `sin(theta)` so the page is genuinely flat at both ends.

Two things fall out of the model rather than needing special cases. The
horizontal term changes sign at the halfway point, which *is* the leaf passing
edge-on and starting to show its back. And a curled page still presents a sliver
of itself side-on, so the leaf never collapses to the zero-width shape a flat
model degenerates to at exactly 90° — where `QTransform.quadToQuad` has no
solution and returns `None`.

`QTransform` maps a plane to a plane, so the curve is drawn as 20 flat strips.
Each strip must draw only its own slice; drawing the whole pixmap through a
strip's transform smears the entire page across the leaf.

### A recto and its verso are bound along opposite edges

The projection originally pinned the page image's top-left corner to the spine
regardless of which face was toward the reader. A recto is bound along its left
edge, but the verso on the back of that same sheet is bound along its *right*.
Getting this wrong drew the verso mirrored for the whole second half of every
turn, then snapped it upright the moment the turn ended.

### Edge stacks are drawn at real paper thickness

The stacks either side of the spine are `leaves × PAPER_CALIPER_PT` (0.1mm,
about 80gsm bond) at display scale — not a stylised progress hint. Drawn to
scale they answer an actual bookbinding question: how thick will the block be.
This stays legible across the realistic range, a couple of pixels for a 16-page
pamphlet up to about seventy for a 512-page book.

Line density follows the *drawn width*, not the leaf count. One line per leaf
packs 120 hairlines into a dozen pixels and reads as a solid slab.

Paper caliper is currently a module constant. It is a real bookbinding variable
and wants to be configurable, but it is not an imposition parameter — it changes
nothing about the output — so it does not belong in `ImpositionParams`.

### The static spread is cached during a turn

Per-frame cost is dominated by fill rate, not strip count. The pages and their
stacks do not change while a leaf turns and are most of the painted area;
redrawing them every frame put a 2560×1400 window at 48fps. Rendering them once
per turn and blitting brought every size back above 60fps on the software
rasteriser.

### A press does not act; a committed drag is not restarted

Click and drag share one mouse button, so a press has to stay ambiguous until
the pointer does or does not travel. Acting on press would make every drag start
with a jump.

On release past halfway, the drag sets its leaf running *before* telling the
pane. `display()` therefore has to notice a turn already heading for that view
and let it land, rather than starting a second one over the top — which snaps
the leaf back to the beginning at the exact moment the reader lets go. Invisible
in the code, glaring on screen.

## Application

### Every page edit re-imposes through one guarded path

`current_params()` raises `ValueError` on a combination the widgets still accept
— the signature-size spinbox will hold 6, which is not a multiple of 4. That
call was originally duplicated across five unguarded call sites.

Unguarded, the exception escapes a Qt slot *after* the page edit has landed. Qt
logs it to stderr, invisible in a packaged app, and the Imposed and Bound
Preview tabs are left showing the pre-edit layout. All five now route through
`_reimpose_from_panel`.

### Arrow keys are handled by the focused widget, not as shortcuts

The Bound Preview claims Left/Right. As application shortcuts those would be
stolen from every text cursor and spinbox in the settings form. It takes focus
when the tab becomes visible — tied to becoming visible rather than to
`display()`, which also runs while the tab is hidden on every re-impose and
would yank focus out of whatever field was being edited.

## Testing

### Check that a test fails without its fix

Two bugs here were "covered" by tests that passed either way.

The preset round-trip test saved and loaded within one process, so it hit
`QSettings`' in-process cache and never exercised a real read from disk — which
is exactly where the bug lived. Preset tests now read through a copy of the ini
at a path the process has not seen.

The page-turn mirroring test compared rendered frames using the standard test
PDFs, which are nearly symmetric left-to-right. A mirrored page barely changes
those pixels. That test now uses deliberately lopsided content and asserts its
own content is asymmetric enough for the comparison to mean anything.

### Geometry lives in pure functions

`leaf_curve`, `book_layout`, `edge_stack_width`, `cast_shadow_strength` and
`leaf_source_x` are module-level and take plain numbers. Most of the page-turn
test suite needs no window and no running animation as a result.

### Animations are zero-duration under test

An autouse fixture patches the turn duration to 0. Without it, tests assert
against a widget mid-animation and can tear it down while a `QPropertyAnimation`
is still driving it.

## Project

### GPL v3, with development dependencies noted

The project is GPL v3 (see [`COPYING`](../COPYING)). PyMuPDF is AGPL v3 and
PySide6 is LGPL v3, both compatible.

`pytest`, `pytest-qt` and `pyinstaller` are permissively licensed and are *not*
included in distributed binaries — they are build and test tooling only, which
is why their licences do not constrain the project's own.
