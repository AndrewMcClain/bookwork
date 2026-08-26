# Bookwork

A cross-platform (Windows/macOS/Linux) desktop tool for
[imposing](https://en.wikipedia.org/wiki/Imposition) a PDF for booklet/signature
printing: view a PDF, reorder and arrange pages 2-up per sheet, and produce a
print-ready file. See [DESIGN.md](DESIGN.md) for the project's design doc and roadmap.

**Status:** early development — milestone v3 done (print integration, saved
presets, first packaged build — Linux verified, Windows/macOS unverified;
see [packaging/README.md](packaging/README.md)).

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management

## Setup

```bash
uv sync
```

## Run

```bash
uv run bookwork [path/to/file.pdf]
```

The PDF path argument is optional; you can also use File → Open in the app.

## Test

```bash
uv run pytest
```

On a Linux machine with no display attached (e.g. CI, SSH session), set
`QT_QPA_PLATFORM=offscreen` first.

## Project layout

```
src/bookwork/
  app.py              # QApplication entry point
  main_window.py      # main window: menu, Source/Imposed/Bound Preview tabs
  pdf_document.py     # PyMuPDF wrapper (all `pymupdf` usage lives here)
  imposition.py       # signature order, 2-up placement, crop marks, bound
                       # preview, layout stats (no shell tools)
  printing.py         # renders an imposed PdfDocument onto a QPrinter
  presets.py           # named ImpositionParams presets, via QSettings
  widgets/
    pdf_viewer_pane.py    # thumbnail sidebar + page view, reused per tab
    page_view.py          # single-page display, scaled to fit
    page_turn_view.py     # animated page turn, for the Bound Preview tab
    thumbnail_list.py     # page thumbnail sidebar; editable on the Source tab
    imposition_panel.py   # signature/sheet/margin/gutter form, presets, stats
tests/
```

**Editing pages**: right-click a thumbnail on the Source tab to insert a
blank page before/after it, or delete it (blank or real content — e.g. to
drop a bad scan or fix a miscount). Undo/redo (Ctrl+Z / Ctrl+Shift+Z, or the
Edit menu) covers all of it. Every edit immediately regenerates the
Imposed and Bound Preview tabs, so you see the effect on signature layout
and pagination right away — this is the main tool for catching an
off-by-one before it costs you a print.

The **Bound Preview** tab simulates actually flipping through the bound book:
single-page views for the front/back cover, two-page spreads (with a spine
divider) everywhere else — cropped from the already-imposed sheets, in actual
reading order. This is the best place to spot an off-by-one or signature
ordering mistake, since it shows the book exactly as a reader would
experience it, rather than requiring you to mentally fold/unfold the Imposed
tab's sheet order.

Moving between adjacent views animates a **page turn**: a leaf rotates about
the spine carrying the page you're leaving on its front and the page you're
arriving at on its back, exactly as one physical sheet does. That pairing is
the point — it's what makes a mispaginated sheet obvious, since a leaf whose
two sides don't belong together is immediately wrong to look at. Jumping
several views at once (clicking a distant thumbnail) skips the animation
rather than implying a motion the book wouldn't make.

Turn pages by **clicking the page you want to turn** — the left page goes
back, the right page goes forward — or with the **left/right arrow keys**
once the tab has focus (switching to it focuses the book automatically). The
thumbnail sidebar and the View menu still work as before.

The turning leaf **bows** as it goes over, rather than swinging across flat
like a card, and shades along the curl. The pages already turned and those
still to come are drawn as **edge stacks** either side of the spine, at the
real thickness of that many sheets of paper — so the two stacks together
show roughly how thick the finished text block will be, and how far into it
you are. A 16-page pamphlet shows a sliver; a 500-page book shows a
substantial block. Paper is assumed to be 0.1mm (about 80gsm bond); it isn't
configurable yet.

**Add blank endpapers (case binding)**, in the Imposed tab's settings panel,
adds one real blank page at the very front and one at the very back of the
*actual printed output* (not just the preview) — for gluing the text block
into a hardcover case. It's off by default (a plain stapled/saddle-stitch
booklet doesn't need it). With it on, page 1 shifts to be the left page of
its own spread (rather than standing alone), and the very last page is
always guaranteed blank and shown alone, since padding always fills out to a
full signature.

**Separate wrap cover (first/last page)**, also in that panel, treats the
first and last source pages as a single-folio cover — one sheet, folded on
its own (outside spread: back cover left, front cover right; inside spread
blank), wrapped around the interior pages, which get imposed into their own
signature(s) as usual. This is the standard structure for a saddle-stitch
booklet printed with heavier cover stock. Mutually exclusive with the
endpapers option (the UI unchecks one when you check the other) — a case
binding's cover *is* the case, it doesn't also get a wrap folio.

**Pad last signature to full size**, also in that panel, controls what
happens when the content doesn't divide evenly into the signature size. By
default (unchecked) the leftover partial signature is padded only up to the
next multiple of 4 — the physical minimum — instead of all the way to a full
signature, to avoid wasting blank pages/sheets: a 4-page document with a
20-page signature size prints on 1 sheet instead of 5. Checking it forces
every signature, including the last, to the same full length (matching
`psbook`'s own behavior) — trading that savings for uniform signature sizes.
The layout stats below the checkboxes spell out the actual breakdown, e.g.
"20 pages/signature, 2 full signatures + 1 signature of 4 pages".

**Printing**: File → Print Imposed... (Ctrl+P) opens the system print dialog
pre-configured for the imposed sheet's exact size and duplex mode (short-edge
by default, matching this project's fold orientation). It always prints the
Imposed tab's output, regardless of which tab is currently active.

Most real printers — laser ones especially — have a hardware-imposed
unprintable margin around every edge that software can't override. Each page
is drawn at its native, unscaled size unless the printer's actual reported
printable area is too small to fit the *content* (the region inset by your
configured margin from the sheet's outer edges — where imposition already
guarantees real content stays clear of, crop marks being the exception, by
design, right at that edge). So on a typical printer, where the hardware
margin is smaller than your configured margin, nothing shrinks and no
"phantom" margin gets introduced — the crop marks nearest the edge may end
up slightly clipped instead, which is the acceptable tradeoff, not actual
page content. Only on a printer whose hardware margin exceeds your
configured margin does the whole page shrink, and only by just enough to
keep the content itself safe.

**Presets**: the Preset dropdown at the top of the Imposed tab's settings
panel saves and recalls a full set of imposition settings (signature size,
sheet size, margin, gutter, crop marks, endpapers/cover mode) under a name
you choose. Presets persist across runs in the OS's native settings store
(registry / plist / ini, via `QSettings`) and are shared by every document
you open — save one once (e.g. "Digest booklet"), and it stays available.
Picking a preset applies it immediately, unlike other field edits which wait
for Apply.

## Packaging

See [packaging/README.md](packaging/README.md) for building a standalone
desktop app with PyInstaller. Built and smoke-tested on Linux; the spec is
written to be correct on Windows/macOS too but hasn't been built or run on
either yet.

## License

Bookwork is licensed under the [GNU General Public License v3](COPYING).

**Note:** Development dependencies (pytest, pytest-qt, pyinstaller) are 
licensed under permissive licenses (MIT, GPLv2+) and are not included in 
distributed binaries.

## Known follow-ups

- The thumbnail sidebar (`widgets/thumbnail_list.py`) has some extra blank
  space in its layout that needs a pass — cosmetic, not functional.
- Windows/macOS packaged builds are unverified (no access to those OSes) —
  see packaging/README.md.
- No app icon, code signing, or notarization yet.
